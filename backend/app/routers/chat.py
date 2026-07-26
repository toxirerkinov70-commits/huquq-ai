import json
import logging
import time
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..config import settings
from ..db import sqlite
from ..models import ChatRequest, ChatResponse
from ..services import agents as agents_service
from ..services import aliases
from ..services import generate as generate_service
from ..services.rerank import TOP_N as RERANK_TOP_N
from ..services.rerank import rerank
from ..services.retrieval import detect_article_no, expand_query, rewrite_followup

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])

CANDIDATE_K = 20


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _prepare(request: Request, payload: ChatRequest) -> tuple:
    """Rewrite the question, retrieve candidates and rerank them."""
    agent = agents_service.get_agent(payload.agent)
    session_id = sqlite.ensure_session(payload.session_id, agent.key)
    history = sqlite.get_history(session_id)

    retriever = request.app.state.retriever
    llm = request.app.state.llm

    search_query = await rewrite_followup(payload.question, history, llm)

    # a question that names an article or a code is already precisely targeted,
    # so paraphrasing it only spends quota
    targeted = detect_article_no(search_query) or aliases.detect_documents(search_query)
    variants = (
        await expand_query(search_query, llm)
        if settings.enable_query_expansion and not targeted
        else []
    )

    hits = await retriever.hybrid_search(
        search_query, k=CANDIDATE_K, filters=agent.filters(), variants=variants
    )
    if settings.enable_rerank:
        hits = await rerank(search_query, hits, llm)
    else:
        hits = hits[:RERANK_TOP_N]
    return agent, session_id, history, hits


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest):
    started = time.monotonic()
    agent, session_id, history, hits = await _prepare(request, payload)
    llm = request.app.state.llm
    sources = generate_service.build_sources(hits)
    sqlite.add_message(session_id, "user", payload.question)

    if not payload.stream:
        answer = await generate_service.generate_answer(
            payload.question, hits, llm, history, agent.prompt
        )
        if not generate_service.answer_is_grounded(answer):
            sources = []
        sqlite.add_message(session_id, "assistant", answer, sources)
        logger.info(
            "chat agent=%s hits=%s latency=%.2fs tokens=%s/%s",
            agent.key,
            len(hits),
            time.monotonic() - started,
            llm.prompt_tokens,
            llm.output_tokens,
        )
        return ChatResponse(
            answer=answer, sources=sources, used_agent=agent.key, session_id=session_id
        )

    async def event_stream() -> AsyncIterator[str]:
        collected: list[str] = []
        yield _sse("meta", {"session_id": session_id, "used_agent": agent.key})
        try:
            async for piece in generate_service.stream_answer(
                payload.question, hits, llm, history, agent.prompt
            ):
                collected.append(piece)
                yield _sse("token", {"text": piece})
        except Exception as exc:
            logger.exception("streaming failed")
            yield _sse("error", {"message": str(exc)})
        else:
            grounded = generate_service.answer_is_grounded("".join(collected))
            yield _sse("sources", {"sources": sources if grounded else []})
        finally:
            answer = "".join(collected)
            if answer:
                sqlite.add_message(session_id, "assistant", answer, sources)
            logger.info(
                "chat(stream) agent=%s hits=%s latency=%.2fs tokens=%s/%s",
                agent.key,
                len(hits),
                time.monotonic() - started,
                llm.prompt_tokens,
                llm.output_tokens,
            )
            yield _sse("done", {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
