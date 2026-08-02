import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..models import (
    ArticleSummary,
    DocumentDetail,
    DocumentSummary,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from ..services import agents as agents_service
from ..services import aliases, auth, corpus, usage
from ..services.auth import Principal
from ..services.rerank import rerank
from ..services.retrieval import detect_article_no, expand_query

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["search"])


def _articles(doc_id: str) -> list[ArticleSummary]:
    return [
        ArticleSummary(
            article_no=chunk.get("article_no_display") or chunk.get("article_no"),
            article_title=chunk.get("article_title"),
            source_url=chunk.get("source_url"),
            chapter=chunk.get("chapter"),
        )
        for chunk in corpus.document_articles(doc_id)
    ]


def _summary(record: dict) -> DocumentSummary:
    return DocumentSummary(
        doc_id=record["doc_id"],
        title=record.get("title", ""),
        doc_type=record.get("form"),
        act_type=record.get("act_type"),
        adopted_date=record.get("adopted_date"),
        effective_date=record.get("effective_date"),
        status=record.get("status"),
        articles=record.get("articles"),
        url=record.get("url"),
    )


@router.post("/search", response_model=SearchResponse)
async def search(
    request: Request,
    payload: SearchRequest,
    principal: Principal = Depends(auth.current_principal),
):
    """Retrieval only, with no answer generated.

    It still costs an embedding and, when expansion or reranking is asked for, model
    calls — so it is metered and capped like anything else.
    """
    usage.check_quota(principal.id, principal.plan)
    meter = usage.new_meter(principal.id, "/api/search", "search")
    retriever = request.app.state.retriever
    agent = agents_service.get_agent(payload.agent)
    filters = agent.filters()
    k = min(payload.k, principal.plan.max_search_k)

    try:
        if payload.mode == "dense":
            hits = await retriever.dense_search(payload.query, k=k, filters=filters)
        elif payload.mode == "sparse":
            hits = await retriever.sparse_search(payload.query, k=k, filters=filters)
        else:
            variants = (
                await expand_query(payload.query, request.app.state.llm)
                if payload.expand
                else None
            )
            hits = await retriever.hybrid_search(
                payload.query, k=k, filters=filters, variants=variants
            )

        if payload.rerank and hits:
            hits = await rerank(payload.query, hits, request.app.state.llm, top_n=k)

        return SearchResponse(
            query=payload.query,
            detected_article_no=detect_article_no(payload.query),
            detected_doc_ids=aliases.detect_documents(payload.query),
            hits=[
                SearchHit(
                    chunk_id=hit.chunk_id,
                    score=hit.score,
                    source=hit.source,
                    doc_id=hit.payload.get("doc_id"),
                    doc_title=hit.payload.get("doc_title"),
                    article_no=hit.payload.get("article_no_display")
                    or hit.payload.get("article_no"),
                    article_title=hit.payload.get("article_title"),
                    source_url=hit.payload.get("source_url"),
                    text=hit.payload.get("text"),
                )
                for hit in hits
            ],
        )
    finally:
        usage.flush(meter)


@router.get("/agents")
async def list_agents():
    return {"agents": agents_service.list_agents()}


@router.get("/documents", response_model=list[DocumentSummary])
async def documents(
    group: int | None = None,
    q: str | None = Query(default=None, description="title substring"),
    limit: int = Query(default=500, ge=1, le=2000),
    _: Principal = Depends(auth.current_principal),
):
    records = corpus.registry.all()
    if group is not None:
        records = [record for record in records if record.get("group") == group]
    if q:
        needle = aliases.normalize(q)
        records = [
            record for record in records if needle in aliases.normalize(record.get("title", ""))
        ]
    return [_summary(record) for record in records[:limit]]


@router.get("/document/{doc_id}", response_model=DocumentDetail)
async def document(doc_id: str, _: Principal = Depends(auth.current_principal)):
    record = corpus.registry.get(doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    detail = DocumentDetail(**_summary(record).model_dump())
    detail.okoz = record.get("okoz") or []
    detail.tsz = record.get("tsz") or []
    detail.articles_list = _articles(doc_id)
    return detail
