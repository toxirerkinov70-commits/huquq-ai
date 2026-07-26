import json
import logging
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import (
    ArticleSummary,
    DocumentDetail,
    DocumentSummary,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from ..services import agents as agents_service
from ..services import aliases
from ..services.rerank import rerank
from ..services.retrieval import detect_article_no, expand_query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["search"])

REGISTRY_PATH = Path(__file__).resolve().parents[3] / "data" / "registry.jsonl"
CHUNKS_PATH = Path(__file__).resolve().parents[3] / "data" / "chunks.jsonl"


@lru_cache(maxsize=1)
def _registry() -> list[dict]:
    if not REGISTRY_PATH.exists():
        return []
    with REGISTRY_PATH.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


@lru_cache(maxsize=32)
def _articles(doc_id: str) -> list[ArticleSummary]:
    if not CHUNKS_PATH.exists():
        return []
    seen: set[str] = set()
    articles: list[ArticleSummary] = []
    with CHUNKS_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            chunk = json.loads(line)
            if chunk.get("doc_id") != doc_id or chunk.get("part") != 0:
                continue
            key = str(chunk.get("article_no"))
            if key in seen:
                continue
            seen.add(key)
            articles.append(
                ArticleSummary(
                    article_no=chunk.get("article_no_display") or chunk.get("article_no"),
                    article_title=chunk.get("article_title"),
                    source_url=chunk.get("source_url"),
                    chapter=chunk.get("chapter"),
                )
            )
    return articles


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
async def search(request: Request, payload: SearchRequest):
    retriever = request.app.state.retriever
    agent = agents_service.get_agent(payload.agent)
    filters = agent.filters()

    if payload.mode == "dense":
        hits = await retriever.dense_search(payload.query, k=payload.k, filters=filters)
    elif payload.mode == "sparse":
        hits = await retriever.sparse_search(payload.query, k=payload.k, filters=filters)
    else:
        variants = (
            await expand_query(payload.query, request.app.state.llm) if payload.expand else None
        )
        hits = await retriever.hybrid_search(
            payload.query, k=payload.k, filters=filters, variants=variants
        )

    if payload.rerank and hits:
        hits = await rerank(payload.query, hits, request.app.state.llm, top_n=payload.k)

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


@router.get("/agents")
async def list_agents():
    return {"agents": agents_service.list_agents()}


@router.get("/documents", response_model=list[DocumentSummary])
async def documents(
    group: int | None = None,
    q: str | None = Query(default=None, description="title substring"),
):
    records = _registry()
    if group is not None:
        records = [record for record in records if record.get("group") == group]
    if q:
        needle = aliases.normalize(q)
        records = [
            record for record in records if needle in aliases.normalize(record.get("title", ""))
        ]
    return [_summary(record) for record in records]


@router.get("/document/{doc_id}", response_model=DocumentDetail)
async def document(doc_id: str):
    record = next((item for item in _registry() if item["doc_id"] == doc_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="document not found")
    detail = DocumentDetail(**_summary(record).model_dump())
    detail.okoz = record.get("okoz") or []
    detail.tsz = record.get("tsz") or []
    detail.articles_list = _articles(doc_id)
    return detail
