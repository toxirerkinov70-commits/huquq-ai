import asyncio
import json
import time
from typing import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..config import settings
from ..db import sqlite
from ..models import (
    ChatRequest,
    ChatResponse,
    SessionDetail,
    SessionSummary,
    SessionUpdateRequest,
)
from ..services import agentic
from ..services import agents as agents_service
from ..services import aliases, auth, intent, selfinfo, usage
from ..services import attachments as attachments_service
from ..services import drafting
from ..services import generate as generate_service
from ..services.auth import Principal
from ..services.query import is_situation, looks_russian
from ..services.rerank import TOP_N as RERANK_TOP_N
from ..services.rerank import rerank
from ..services.retrieval import detect_article_no, expand_query, rewrite_followup

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])

CANDIDATE_K = 20
# a companion search backs one idea, so it contributes its best couple of articles
FACET_K = 2
# a drafted document cites its grounds inside itself; the list under the chat is there
# to let the person verify them, not to repeat the whole retrieval
DRAFT_SOURCES = 6


async def _nothing() -> AsyncIterator[str]:
    """A stream with nothing left to send, for answers produced in one piece."""
    return
    yield  # pragma: no cover — makes this a generator


async def _draft(
    payload: ChatRequest,
    hits: list,
    llm,
    history: list[dict] | None,
) -> dict | None:
    """Draft the document, or return None so the normal answer path takes over.

    A drafting failure should cost the person their document, not their answer.
    """
    try:
        return await drafting.draft(payload.question, hits, llm, history)
    except Exception as exc:  # noqa: BLE001 — falling back is the whole point
        logger.warning("drafting failed, answering normally", error=str(exc))
        return None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/sessions", response_model=list[SessionSummary])
async def sessions(principal: Principal = Depends(auth.current_principal)):
    return [SessionSummary(**row) for row in sqlite.list_sessions(principal.id)]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def session_detail(
    session_id: str, principal: Principal = Depends(auth.current_principal)
):
    messages = sqlite.get_session_messages(session_id, principal.id)
    # a session belonging to somebody else is reported as missing rather than forbidden,
    # so the endpoint cannot be used to discover which ids exist
    if messages is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return SessionDetail(id=session_id, messages=messages)


@router.patch("/sessions/{session_id}")
async def edit_session(
    session_id: str,
    payload: SessionUpdateRequest,
    principal: Principal = Depends(auth.current_principal),
):
    """Rename a conversation or pin it to the top of the list."""
    if payload.title is None and payload.pinned is None:
        raise HTTPException(
            status_code=400, detail={"error": "nothing_to_update"}
        )
    if not sqlite.update_session(session_id, principal.id, payload.title, payload.pinned):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return {"updated": session_id}


@router.delete("/sessions/{session_id}")
async def remove_session(
    session_id: str, principal: Principal = Depends(auth.current_principal)
):
    if not sqlite.delete_session(session_id, principal.id):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return {"deleted": session_id}


def _user_text(payload: ChatRequest) -> str:
    if payload.attachment:
        return f"[Fayl: {payload.attachment.name}] {payload.question}"
    return payload.question


def _attachment_bytes(payload: ChatRequest) -> int:
    """Decoded size, from the base64 length, without decoding the whole thing first."""
    if payload.attachment is None:
        return 0
    return len(payload.attachment.data) * 3 // 4


def _authorise(payload: ChatRequest, principal: Principal, agentic_mode: bool) -> None:
    """Everything the plan has to permit before any work starts.

    The daily allowance is not charged here: what a message costs depends on what it
    turns out to be, and that is only known after it has been classified.
    """
    # the offer is a condition of use, so it is enforced where use happens rather than
    # only on the screen that shows the checkbox
    if principal.user.get("terms_version") != settings.terms_version:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "terms_required",
                "message": "Davom etish uchun ommaviy oferta shartlarini qabul qiling.",
            },
        )
    if payload.attachment is not None:
        usage.check_attachment(principal.plan, _attachment_bytes(payload))
    if agentic_mode:
        usage.check_agentic(principal.plan)


# saying hello, or being told the assistant cannot discuss football, is not a legal
# question and does not come out of the daily allowance
FREE_INTENTS = {intent.CONVERSATION, intent.ACCOUNT, intent.OFF_TOPIC}


def _charge(principal: Principal, label: str) -> None:
    if label in FREE_INTENTS:
        usage.check_conversational(principal.id, principal.plan)
    else:
        usage.check_quota(principal.id, principal.plan)


def _kind(label: str, payload: ChatRequest, agentic_mode: bool) -> str:
    if payload.attachment is not None:
        return "attachment"
    if label in FREE_INTENTS:
        return "conversational"
    if label == intent.DRAFT:
        return "draft"
    return "agentic" if agentic_mode else "question"


FAILURE_MESSAGES = {
    "auth": (
        "Til modeliga ulanib bo'lmadi — xizmat kalitida muammo. "
        "Administrator bilan bog'laning."
    ),
    "quota": (
        "Bugungi model kvotasi tugadi. Bir ozdan keyin yoki ertaga qaytadan urinib ko'ring."
    ),
    "provider": "Til modeli vaqtincha javob bermayapti. Bir daqiqadan keyin urinib ko'ring.",
    "network": "Tarmoqqa ulanib bo'lmadi. Ulanishni tekshirib, qaytadan urining.",
}


def _failure_message(exc: Exception) -> str:
    reason = getattr(exc, "reason", None)
    return FAILURE_MESSAGES.get(
        reason, "Javob olishda xatolik yuz berdi. Qaytadan urinib ko'ring."
    )


def _account_reply(payload: ChatRequest, principal: Principal) -> str:
    return selfinfo.account_answer(
        principal.user,
        principal.plan,
        usage.snapshot(principal.id, principal.plan),
        payload.question,
    )


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
        logger.info("companion chunks added", agent=agent.key, count=len(extra))
    return hits + extra


async def _retrieve(request: Request, payload: ChatRequest, agent, history) -> list:
    """The plain-question path: rewrite, expand, retrieve, rerank, add companions."""
    retriever = request.app.state.retriever
    llm = request.app.state.llm

    search_query = await rewrite_followup(payload.question, history, llm)

    # a question that names an article or a code is already precisely targeted,
    # so paraphrasing it only spends quota — unless it is in Russian, where the
    # expansion is what produces the Uzbek wording the sparse index can match
    russian = looks_russian(search_query)
    targeted = bool(detect_article_no(search_query) or aliases.detect_documents(search_query))
    variants = (
        await expand_query(search_query, llm)
        if settings.enable_query_expansion and (russian or not targeted)
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
        raise HTTPException(
            status_code=400, detail={"error": "bad_attachment", "message": str(exc)}
        )

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
async def chat_agentic(
    request: Request,
    payload: ChatRequest,
    principal: Principal = Depends(auth.current_principal),
):
    """The model drives the search itself and may reach lex.uz when the base falls short.

    Tool calls interleave with generation, so there is nothing to stream until the model
    stops calling; this path always answers in one piece.
    """
    _authorise(payload, principal, agentic_mode=True)
    started = time.monotonic()
    llm = request.app.state.llm
    agent = agents_service.get_agent(payload.agent)
    session_id = sqlite.ensure_session(payload.session_id, principal.id, agent.key)
    meter = usage.new_meter(principal.id, "/api/chat/agentic", "agentic", session_id)
    label = await intent.classify(payload.question, llm, payload.attachment is not None)
    meter.kind = _kind(label, payload, True)
    _charge(principal, label)
    history = sqlite.get_history(session_id)
    sqlite.add_message(session_id, "user", _user_text(payload))

    try:
        # neither a greeting nor a question about one's own plan needs the tool loop
        if label == intent.ACCOUNT:
            answer = _account_reply(payload, principal)
            sqlite.add_message(session_id, "assistant", answer)
            return ChatResponse(
                answer=answer, sources=[], used_agent=agent.key, session_id=session_id
            )
        if label in (intent.CONVERSATION, intent.OFF_TOPIC):
            answer = await generate_service.conversational_answer(
                payload.question, llm, history, off_topic=label == intent.OFF_TOPIC
            )
            sqlite.add_message(session_id, "assistant", answer)
            return ChatResponse(
                answer=answer, sources=[], used_agent=agent.key, session_id=session_id
            )

        attachment_block = None
        extra_parts = None
        if payload.attachment:
            try:
                prepared = attachments_service.prepare(payload.attachment)
            except attachments_service.AttachmentError as exc:
                raise HTTPException(
                    status_code=400, detail={"error": "bad_attachment", "message": str(exc)}
                )
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
            "agentic answer",
            agent=agent.key,
            tools=[call["tool"] for call in calls],
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_usd=meter.cost_usd,
        )
        return ChatResponse(
            answer=answer, sources=sources, used_agent=agent.key, session_id=session_id
        )
    finally:
        usage.flush(meter, session_id)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    payload: ChatRequest,
    principal: Principal = Depends(auth.current_principal),
):
    _authorise(payload, principal, agentic_mode=False)
    started = time.monotonic()
    llm = request.app.state.llm
    agent = agents_service.get_agent(payload.agent)
    session_id = sqlite.ensure_session(payload.session_id, principal.id, agent.key)
    # the meter opens before the message is classified so the classifier's own tokens
    # land on this request rather than on nobody
    meter = usage.new_meter(principal.id, "/api/chat", "question", session_id)
    label = await intent.classify(payload.question, llm, payload.attachment is not None)
    meter.kind = _kind(label, payload, False)
    _charge(principal, label)
    history = sqlite.get_history(session_id)
    request_id = getattr(request.state, "request_id", None)

    # "mening tarifim" is a question about this account, not about the Labour Code's
    # article on wage tariffs. It is answered from what is already known, so it costs
    # neither a model call nor a question from the daily allowance.
    if label == intent.ACCOUNT:
        answer = _account_reply(payload, principal)
        sqlite.add_message(session_id, "user", _user_text(payload))
        sqlite.add_message(session_id, "assistant", answer)
        usage.flush(meter, session_id)
        if not payload.stream:
            return ChatResponse(
                answer=answer, sources=[], used_agent=agent.key, session_id=session_id
            )

        async def account_stream() -> AsyncIterator[str]:
            yield _sse("meta", {"session_id": session_id, "used_agent": agent.key})
            yield _sse("token", {"text": answer})
            yield _sse("sources", {"sources": []})
            yield _sse("done", {"quota": usage.snapshot(principal.id, principal.plan)})

        return StreamingResponse(
            account_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    conversational = label in (intent.CONVERSATION, intent.OFF_TOPIC)
    off_topic = label == intent.OFF_TOPIC
    drafting_mode = label == intent.DRAFT

    attachment_block = None
    extra_parts = None
    try:
        if conversational:
            hits = []
        elif payload.attachment:
            hits, attachment_block, extra_parts = await _prepare_attachment(
                request, payload, agent
            )
        else:
            hits = await _retrieve(request, payload, agent, history)
    except Exception:
        usage.flush(meter, session_id)
        raise

    sources = generate_service.build_sources(hits)
    sqlite.add_message(session_id, "user", _user_text(payload))
    document: dict | None = None

    if not payload.stream:
        try:
            if conversational:
                answer = await generate_service.conversational_answer(
                    payload.question, llm, history, off_topic=off_topic
                )
                sources = []
            elif drafting_mode and (document := await _draft(payload, hits, llm, history)):
                answer = drafting.summary_line(document)
                sources = sources[:DRAFT_SOURCES]
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
                "chat answer",
                agent=agent.key,
                hits=len(hits),
                latency_ms=int((time.monotonic() - started) * 1000),
                prompt_tokens=meter.prompt_tokens,
                output_tokens=meter.output_tokens,
                cost_usd=meter.cost_usd,
            )
            return ChatResponse(
                answer=answer,
                sources=sources,
                used_agent=agent.key,
                session_id=session_id,
                document=document,
            )
        finally:
            usage.flush(meter, session_id)

    async def event_stream() -> AsyncIterator[str]:
        # the body is iterated outside the handler's context, so the meter is rebound
        # here or the tokens spent while streaming are attributed to nobody
        usage.bind(meter)
        collected: list[str] = []
        final_sources: list[dict] = []
        yield _sse("meta", {"session_id": session_id, "used_agent": agent.key})
        drafted: dict | None = None
        try:
            if drafting_mode and (drafted := await _draft(payload, llm=llm, hits=hits, history=history)):
                # a document arrives as one JSON object, so there is nothing to stream:
                # the sentence goes out in one piece and the draft follows it
                text = drafting.summary_line(drafted)
                collected.append(text)
                yield _sse("token", {"text": text})
                yield _sse("document", {"document": drafted})
                pieces = _nothing()
            elif conversational:
                pieces = generate_service.stream_conversational(
                    payload.question, llm, history, off_topic=off_topic
                )
            else:
                pieces = generate_service.stream_answer(
                    payload.question, hits, llm, history, agent.prompt,
                    attachment_block, extra_parts,
                )
            async for piece in pieces:
                collected.append(piece)
                yield _sse("token", {"text": piece})
        except Exception as exc:
            # the provider's own text can carry fragments of the request, so what
            # reaches the client is a sentence chosen from the kind of failure, and
            # the detail stays in the log
            logger.exception("streaming failed")
            yield _sse("error", {"message": _failure_message(exc), "request_id": request_id})
        else:
            answer_text = "".join(collected)
            if drafted is not None:
                # the draft rests on the articles it was built from, not on words the
                # summary sentence happens to repeat
                final_sources = sources[:DRAFT_SOURCES]
            elif not conversational and generate_service.answer_is_grounded(answer_text):
                final_sources = generate_service.filter_cited_sources(answer_text, sources)
            yield _sse("sources", {"sources": final_sources})
        finally:
            answer = "".join(collected)
            if answer:
                sqlite.add_message(session_id, "assistant", answer, final_sources)
            usage.flush(meter, session_id)
            logger.info(
                "chat answer (stream)",
                agent=agent.key,
                hits=len(hits),
                latency_ms=int((time.monotonic() - started) * 1000),
                prompt_tokens=meter.prompt_tokens,
                output_tokens=meter.output_tokens,
                cost_usd=meter.cost_usd,
            )
            yield _sse("done", {"quota": usage.snapshot(principal.id, principal.plan)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
