import asyncio
import json
import logging
import time
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..config import settings
from ..db import sqlite
from ..models import ChatRequest, ChatResponse, SessionDetail, SessionSummary
from ..services import agentic
from ..services import agents as agents_service
from ..services import aliases
from ..services import attachments as attachments_service
from ..services import generate as generate_service
from ..services.rerank import TOP_N as RERANK_TOP_N
from ..services.rerank import rerank
from ..services.query import is_situation
from ..services.retrieval import detect_article_no, expand_query, rewrite_followup

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])

CANDIDATE_K = 20
# a companion search backs one idea, so it contributes its best couple of articles
FACET_K = 2


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/sessions", response_model=list[SessionSummary])
async def sessions():
    return [SessionSummary(**row) for row in sqlite.list_sessions()]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def session_detail(session_id: str):
    messages = sqlite.get_session_messages(session_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionDetail(id=session_id, messages=messages)


@router.delete("/sessions/{session_id}")
async def remove_session(session_id: str):
    sqlite.delete_session(session_id)
    return {"deleted": session_id}


def _user_text(payload: ChatRequest) -> str:
    if payload.attachment:
        return f"[Fayl: {payload.attachment.name}] {payload.question}"
    return payload.question


async def _facet_hits(retriever, agent, hits: list, wanted: bool) -> list:
    """The norms that shape the outcome, which the question's own words never reach.

    They are searched separately and appended rather than fused in: fusing would let
    them compete with the articles that actually answer the question, and the point is
    to add the mitigating or limitation article underneath, not to promote it.
    """
    if not agent.facets or not wanted:
        return hits

    filters = agent.filters()
    found = await asyncio.gather(
        *(retriever.hybrid_search(facet, k=FACET_K, filters=filters) for facet in agent.facets)
    )
    seen = {hit.chunk_id for hit in hits}
    extra = []
    for ranking in found:
        for hit in ranking:
            if hit.chunk_id not in seen:
                seen.add(hit.chunk_id)
                extra.append(hit)
    if extra:
        logger.info("agent %s added %s companion chunk(s)", agent.key, len(extra))
    return hits + extra


async def _retrieve(request: Request, payload: ChatRequest, agent, history) -> list:
    """The plain-question path: rewrite, expand, retrieve, rerank, add companions."""
    retriever = request.app.state.retriever
    llm = request.app.state.llm

    search_query = await rewrite_followup(payload.question, history, llm)

    # a question that names an article or a code is already precisely targeted,
    # so paraphrasing it only spends quota
    targeted = bool(detect_article_no(search_query) or aliases.detect_documents(search_query))
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
    return await _facet_hits(
        retriever, agent, hits, wanted=not targeted and is_situation(payload.question)
    )


async def _prepare_attachment(request: Request, payload: ChatRequest, agent) -> tuple:
    """Read the document, derive corpus queries from it, retrieve matching norms."""
    llm = request.app.state.llm
    retriever = request.app.state.retriever

    try:
        prepared = attachments_service.prepare(payload.attachment)
    except attachments_service.AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    analysis = await attachments_service.analyze(prepared, payload.question, llm)
    queries = analysis.get("queries") or []
    search_query = queries[0] if queries else payload.question
    hits = await retriever.hybrid_search(
        search_query, k=CANDIDATE_K, filters=agent.filters(), variants=queries[1:]
    )
    if hits and settings.enable_rerank:
        hits = await rerank(payload.question, hits, llm)
    else:
        hits = hits[:RERANK_TOP_N]
    # an uploaded contract or ruling is the user's own situation by definition
    hits = await _facet_hits(retriever, agent, hits, wanted=True)

    block = attachments_service.prompt_block(prepared, analysis)
    return hits, block, prepared.parts or None


@router.post("/chat/agentic", response_model=ChatResponse)
async def chat_agentic(request: Request, payload: ChatRequest):
    """The model drives the search itself and may reach lex.uz when the base falls short.

    Tool calls interleave with generation, so there is nothing to stream until the model
    stops calling; this path always answers in one piece.
    """
    started = time.monotonic()
    llm = request.app.state.llm
    agent = agents_service.get_agent(payload.agent)
    session_id = sqlite.ensure_session(payload.session_id, agent.key)
    history = sqlite.get_history(session_id)
    sqlite.add_message(session_id, "user", _user_text(payload))

    # a greeting does not need the tool loop either
    if payload.attachment is None and generate_service.is_conversational(payload.question):
        answer = await generate_service.conversational_answer(payload.question, llm, history)
        sqlite.add_message(session_id, "assistant", answer)
        return ChatResponse(answer=answer, sources=[], used_agent=agent.key, session_id=session_id)

    attachment_block = None
    extra_parts = None
    if payload.attachment:
        try:
            prepared = attachments_service.prepare(payload.attachment)
        except attachments_service.AttachmentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        analysis = await attachments_service.analyze(prepared, payload.question, llm)
        attachment_block = attachments_service.prompt_block(prepared, analysis)
        extra_parts = prepared.parts or None

    answer, sources, calls = await agentic.answer_with_tools(
        payload.question,
        request.app.state.retriever,
        llm,
        history,
        agent,
        attachment_block=attachment_block,
        extra_parts=extra_parts,
    )
    if not generate_service.answer_is_grounded(answer):
        sources = []
    else:
        sources = generate_service.filter_cited_sources(answer, sources)
    sqlite.add_message(session_id, "assistant", answer, sources)
    logger.info(
        "agentic agent=%s tools=%s latency=%.2fs",
        agent.key,
        [call["tool"] for call in calls],
        time.monotonic() - started,
    )
    return ChatResponse(
        answer=answer, sources=sources, used_agent=agent.key, session_id=session_id
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest):
    started = time.monotonic()
    llm = request.app.state.llm
    agent = agents_service.get_agent(payload.agent)
    session_id = sqlite.ensure_session(payload.session_id, agent.key)
    history = sqlite.get_history(session_id)

    conversational = payload.attachment is None and generate_service.is_conversational(
        payload.question
    )

    attachment_block = None
    extra_parts = None
    if conversational:
        hits = []
    elif payload.attachment:
        hits, attachment_block, extra_parts = await _prepare_attachment(request, payload, agent)
    else:
        hits = await _retrieve(request, payload, agent, history)

    sources = generate_service.build_sources(hits)
    sqlite.add_message(session_id, "user", _user_text(payload))

    if not payload.stream:
        if conversational:
            answer = await generate_service.conversational_answer(payload.question, llm, history)
            sources = []
        else:
            answer = await generate_service.generate_answer(
                payload.question, hits, llm, history, agent.prompt,
                attachment_block, extra_parts,
            )
            if not generate_service.answer_is_grounded(answer):
                sources = []
            else:
                sources = generate_service.filter_cited_sources(answer, sources)
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
        final_sources: list[dict] = []
        yield _sse("meta", {"session_id": session_id, "used_agent": agent.key})
        try:
            if conversational:
                pieces = generate_service.stream_conversational(payload.question, llm, history)
            else:
                pieces = generate_service.stream_answer(
                    payload.question, hits, llm, history, agent.prompt,
                    attachment_block, extra_parts,
                )
            async for piece in pieces:
                collected.append(piece)
                yield _sse("token", {"text": piece})
        except Exception as exc:
            logger.exception("streaming failed")
            yield _sse("error", {"message": str(exc)})
        else:
            answer_text = "".join(collected)
            if not conversational and generate_service.answer_is_grounded(answer_text):
                final_sources = generate_service.filter_cited_sources(answer_text, sources)
            yield _sse("sources", {"sources": final_sources})
        finally:
            answer = "".join(collected)
            if answer:
                sqlite.add_message(session_id, "assistant", answer, final_sources)
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
