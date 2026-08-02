import asyncio
import logging
from dataclasses import dataclass, field, replace

from qdrant_client import AsyncQdrantClient, models

from ..config import settings
from . import aliases, coverage
from .embedding import get_embedding_client
from .query import (  # noqa: F401  (re-exported)
    ARTICLE_RE,
    SUPERSCRIPTS,
    detect_article_no,
    looks_russian,
)
from .sparse import encode_query

logger = logging.getLogger(__name__)

DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"
RRF_K = 60

# how far down the results the distinctive terms of the question are looked for, and
# what share of them has to be absent before the search is judged to have drifted.
# Below three quarters the pass fires on questions that were already answered and
# costs precision; measured on eval/questions.jsonl.
SALVAGE_CHECK_TOP = 3
SALVAGE_MISSING_SHARE = 0.75


@dataclass
class SearchFilters:
    doc_ids: list[str] = field(default_factory=list)
    act_types: list[int] = field(default_factory=list)
    okoz: list[str] = field(default_factory=list)
    status: str | None = "Y"

    def to_qdrant(self) -> models.Filter | None:
        must: list[models.Condition] = []
        if self.doc_ids:
            must.append(
                models.FieldCondition(key="doc_id", match=models.MatchAny(any=self.doc_ids))
            )
        if self.act_types:
            must.append(
                models.FieldCondition(key="act_type", match=models.MatchAny(any=self.act_types))
            )
        if self.okoz:
            must.append(models.FieldCondition(key="okoz", match=models.MatchAny(any=self.okoz)))
        if self.status:
            must.append(
                models.FieldCondition(key="status", match=models.MatchValue(value=self.status))
            )
        return models.Filter(must=must) if must else None


@dataclass
class Hit:
    chunk_id: str
    score: float
    payload: dict
    source: str = "hybrid"


EXPAND_SYSTEM = """Sen O'zbekiston qonunchiligi bo'yicha qidiruv so'rovlarini kengaytirasan.
Berilgan savolni huquqiy atamalar bilan 2 ta muqobil shaklda qayta yoz.
Savol mazmunini o'zgartirma, faqat boshqacha ifodala.

Agar savol foydalanuvchi boshidan kechirgan vaziyat bayoni bo'lsa (kimdir bir ish
qilgan yoki unga nisbatan qilingan), so'rovlarni shunday tuz:
- birinchisi — qilmishning rasmiy huquqiy nomi (masalan "mikroqarzni o'z vaqtida
  to'lamaganlik uchun neustoyka");
- ikkinchisi — shu qilmishning oqibati: javobgarlik, jazo yoki undiruv normasi.
Kundalik so'zlarni qonun matnidagi atamalarga almashtir.

Faqat JSON qaytar: {"queries": ["...", "..."]}"""

REWRITE_SYSTEM = """Sen suhbat tarixiga qarab foydalanuvchining oxirgi savolini
mustaqil, o'zi tushunarli savolga aylantirasan. Olmoshlarni ("u", "bu", "unga")
aniq atamalar bilan almashtir. Yangi ma'lumot qo'shma.
Faqat qayta yozilgan savolni qaytar, boshqa hech narsa yozma."""

# The corpus is Uzbek Latin only, so a Russian question scores zero on the sparse side
# and the hybrid falls back to dense alone. Translating the question into the terms the
# statute itself uses restores the other half of the search.
EXPAND_SYSTEM_RU = """Ты переводишь юридические вопросы с русского на узбекский язык
(латиница) для поиска по законодательству Узбекистана.

Верни 2 варианта поискового запроса на узбекском языке, используя официальные
юридические термины из узбекских кодексов (например: "mehnat shartnomasini bekor
qilish", "jinoiy javobgarlik", "da'vo muddati"). Смысл не меняй.

Верни только JSON: {"queries": ["...", "..."]}"""


async def expand_query(query: str, llm) -> list[str]:
    """Alternative phrasings, so one unlucky wording does not sink the search."""
    system = EXPAND_SYSTEM_RU if looks_russian(query) else EXPAND_SYSTEM
    try:
        data = await llm.generate_json(f"Savol: {query}", system=system)
    except Exception as exc:
        logger.warning("query expansion failed: %s", exc)
        return []
    queries = data.get("queries") if isinstance(data, dict) else data
    return [str(item) for item in (queries or []) if isinstance(item, (str, int))][:3]


async def rewrite_followup(question: str, history: list[dict], llm) -> str:
    """Turn a follow-up into a standalone question before searching."""
    if not history:
        return question
    turns = "\n".join(f"{item['role']}: {item['content']}" for item in history[-6:])
    try:
        rewritten = await llm.generate(
            f"Suhbat:\n{turns}\n\nOxirgi savol: {question}", system=REWRITE_SYSTEM
        )
    except Exception as exc:
        logger.warning("query rewrite failed: %s", exc)
        return question
    rewritten = rewritten.strip()
    return rewritten or question


def _to_hits(points, source: str) -> list[Hit]:
    return [
        Hit(
            chunk_id=point.payload["chunk_id"],
            score=point.score,
            payload=point.payload,
            source=source,
        )
        for point in points
    ]


def reciprocal_rank_fusion(rankings: list[list[Hit]], k: int | None = None) -> list[Hit]:
    k = RRF_K if k is None else k
    scores: dict[str, float] = {}
    best: dict[str, Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1 / (k + rank)
            best.setdefault(hit.chunk_id, hit)
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [
        Hit(chunk_id=chunk_id, score=score, payload=best[chunk_id].payload, source="hybrid")
        for chunk_id, score in ordered
    ]


class Retriever:
    def __init__(
        self,
        qdrant: AsyncQdrantClient | None = None,
        embedder=None,
        collection: str | None = None,
    ) -> None:
        self.qdrant = qdrant or AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=60,
        )
        self.embedder = embedder or get_embedding_client()
        self.collection = collection or settings.qdrant_collection

    async def close(self) -> None:
        await self.qdrant.close()
        await self.embedder.close()

    async def dense_search(
        self, query: str, k: int = 20, filters: SearchFilters | None = None
    ) -> list[Hit]:
        vector = await self.embedder.embed_query(query)
        result = await self.qdrant.query_points(
            self.collection,
            query=vector,
            using=DENSE_VECTOR,
            limit=k,
            query_filter=(filters or SearchFilters()).to_qdrant(),
            with_payload=True,
        )
        return _to_hits(result.points, "dense")

    async def sparse_search(
        self, query: str, k: int = 20, filters: SearchFilters | None = None
    ) -> list[Hit]:
        indices, values = encode_query(query)
        if not indices:
            return []
        result = await self.qdrant.query_points(
            self.collection,
            query=models.SparseVector(indices=indices, values=values),
            using=SPARSE_VECTOR,
            limit=k,
            query_filter=(filters or SearchFilters()).to_qdrant(),
            with_payload=True,
        )
        return _to_hits(result.points, "sparse")

    async def article_lookup(
        self, article_no: str, filters: SearchFilters | None = None, k: int = 6
    ) -> list[Hit]:
        """Exact article-number match, which pure vector search regularly gets wrong."""
        base = (filters or SearchFilters()).to_qdrant()
        conditions = list(base.must) if base is not None and base.must else []
        conditions.append(
            models.FieldCondition(key="article_no", match=models.MatchValue(value=article_no))
        )
        points, _ = await self.qdrant.scroll(
            self.collection,
            scroll_filter=models.Filter(must=conditions),
            limit=k,
            with_payload=True,
        )
        return [
            Hit(
                chunk_id=point.payload["chunk_id"],
                score=1.0,
                payload=point.payload,
                source="article",
            )
            for point in points
        ]

    async def _salvage(
        self, query: str, fused: list[Hit], filters: SearchFilters, k: int
    ) -> list[Hit]:
        """Search the question's distinctive words on their own when the results miss them.

        A sentence-long question is mostly words every article uses. They match anything
        that mentions a payment or a deadline, and the one term that names the subject is
        a single token among dozens, so the ranking can fill up with documents that never
        contain it. Dropping the generic words removes that dilution: the same corpus that
        answered a question about a microloan with tax-penalty case law returns the
        microfinance law itself once only "mikroqarz" is asked for.
        """
        terms = coverage.rare_terms(query)
        if not terms:
            return fused
        top = [hit.payload for hit in fused[:SALVAGE_CHECK_TOP]]
        missing = coverage.terms_missing_from(terms, top) if top else terms
        # one distinctive word absent is normal — a question rarely uses every word its
        # answer does. Nearly all of them absent is the results being about something else.
        if len(missing) < len(terms) * SALVAGE_MISSING_SHARE:
            return fused

        logger.info("top results miss %s, searching those terms alone", missing)
        extra = await self.sparse_search(" ".join(terms), k=max(k, 20), filters=filters)
        if not extra:
            return fused
        return reciprocal_rank_fusion([fused, extra])

    async def hybrid_search(
        self,
        query: str,
        k: int = 10,
        filters: SearchFilters | None = None,
        variants: list[str] | None = None,
    ) -> list[Hit]:
        filters = filters or SearchFilters()
        if not filters.doc_ids:
            detected = aliases.detect_documents(query)
            if detected:
                logger.info("query names %s document(s)", len(detected))
                filters = replace(filters, doc_ids=detected)

        queries = [query] + [v for v in (variants or []) if v and v != query]
        searches = []
        for text in queries:
            searches.append(self.dense_search(text, k=max(k, 20), filters=filters))
            searches.append(self.sparse_search(text, k=max(k, 20), filters=filters))
        rankings = await asyncio.gather(*searches)

        fused = reciprocal_rank_fusion([ranking for ranking in rankings if ranking])
        fused = await self._salvage(query, fused, filters, k)

        article_no = detect_article_no(query)
        if article_no:
            exact = await self.article_lookup(article_no, filters)
            if exact:
                logger.info("article %s matched %s chunk(s) directly", article_no, len(exact))
                seen = {hit.chunk_id for hit in exact}
                fused = exact + [hit for hit in fused if hit.chunk_id not in seen]
        return fused[:k]
