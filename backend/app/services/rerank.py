import logging

from .llm import LLMClient, LLMError
from .retrieval import Hit

logger = logging.getLogger(__name__)

TOP_N = 6
MAX_SNIPPET = 900

SYSTEM = """Sen huquqiy qidiruv natijalarini baholaydigan yordamchisan.
Har bir parcha berilgan savolga qanchalik javob berishini 0 dan 10 gacha baholaysan.
10 — parcha savolga to'g'ridan-to'g'ri javob beradi.
5 — mavzuga aloqador, lekin to'g'ridan-to'g'ri javob bermaydi.
0 — aloqasi yo'q.
Faqat JSON qaytar, boshqa hech narsa yozma."""

PROMPT = """Savol: {question}

Parchalar:
{passages}

Har bir parcha uchun quyidagi shaklda JSON qaytar:
{{"scores": [{{"id": 1, "score": 8}}, {{"id": 2, "score": 3}}]}}"""


def _format(hits: list[Hit]) -> str:
    blocks = []
    for index, hit in enumerate(hits, start=1):
        payload = hit.payload
        title = payload.get("article_title") or ""
        blocks.append(
            f"[{index}] {payload.get('doc_title', '')} "
            f"{payload.get('article_no_display') or payload.get('article_no')}-modda. {title}\n"
            f"{(payload.get('text') or '')[:MAX_SNIPPET]}"
        )
    return "\n\n".join(blocks)


async def rerank(
    question: str, hits: list[Hit], llm: LLMClient, top_n: int = TOP_N
) -> list[Hit]:
    """Score every candidate in a single call and keep the best ones."""
    if len(hits) <= top_n:
        return hits

    try:
        data = await llm.generate_json(
            PROMPT.format(question=question, passages=_format(hits)), system=SYSTEM
        )
    except LLMError as exc:
        # ranking is an improvement, not a requirement: fall back to fusion order
        logger.warning("rerank failed, keeping retrieval order: %s", exc)
        return hits[:top_n]

    scores: dict[int, float] = {}
    entries = data.get("scores") if isinstance(data, dict) else data
    for entry in entries or []:
        try:
            scores[int(entry["id"])] = float(entry["score"])
        except (KeyError, TypeError, ValueError):
            continue

    if not scores:
        logger.warning("rerank returned no usable scores")
        return hits[:top_n]

    ordered = sorted(
        enumerate(hits, start=1), key=lambda pair: scores.get(pair[0], 0.0), reverse=True
    )
    reranked = []
    for index, hit in ordered[:top_n]:
        score = scores.get(index, 0.0)
        if score <= 0:
            continue
        reranked.append(Hit(hit.chunk_id, score, hit.payload, source="rerank"))
    return reranked or hits[:top_n]
