"""Tools the model may call while answering.

The internal search is the workhorse. The two lex.uz tools reach the live site and are
deliberately awkward to trigger: they are slow, they put load on a site whose robots.txt
asks for twenty seconds between requests, and the indexed corpus is the right answer
almost every time. They exist for the case the base genuinely cannot cover.
"""

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from ..config import settings
from .retrieval import SearchFilters

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
REGISTRY_PATH = DATA_DIR / "registry.jsonl"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"
MARKDOWN_DIR = DATA_DIR / "markdown"
QUEUE_PATH = DATA_DIR / "update_queue.jsonl"

MAX_TOOL_CALLS = 5
LIVE_RESULTS = 5
SNIPPET = 700

TOOL_DECLARATIONS = [
    {
        "name": "search_legal_base",
        "description": (
            "Ichki huquqiy bazadan qidiradi. Har qanday savol uchun birinchi navbatda "
            "shu vositani ishlating."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Qidiruv so'rovi"},
                "doc_type": {
                    "type": "string",
                    "description": "Ixtiyoriy: hujjat turi bo'yicha cheklash, masalan 'Kodeks'",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_article",
        "description": (
            "Bitta moddaning to'liq matnini qaytaradi. Qidiruv natijasi kesilgan bo'lsa "
            "yoki qo'shni moddalar kerak bo'lsa ishlating."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "article_no": {"type": "string", "description": "Masalan '125' yoki '289-1'"},
            },
            "required": ["doc_id", "article_no"],
        },
    },
    {
        "name": "get_document_structure",
        "description": (
            "Hujjatning mundarijasini qaytaradi. 'Bu kodeksda nima bor?' turidagi "
            "savollarda ishlating."
        ),
        "parameters": {
            "type": "object",
            "properties": {"doc_id": {"type": "string"}},
            "required": ["doc_id"],
        },
    },
    {
        "name": "check_lex_live",
        "description": (
            "lex.uz dan hujjatning joriy holatini real vaqtda tekshiradi. SEKIN. Faqat "
            "bazadagi ma'lumot eskirgan bo'lishi mumkin deb o'ylasangiz chaqiring."
        ),
        "parameters": {
            "type": "object",
            "properties": {"doc_id": {"type": "string"}},
            "required": ["doc_id"],
        },
    },
    {
        "name": "search_lex_live",
        "description": (
            "lex.uz qidiruvini real vaqtda ishlatadi. SEKIN. Faqat ichki bazada natija "
            "topilmagan bo'lsa chaqiring."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
]

LIVE_TOOLS = {"check_lex_live", "search_lex_live"}

_client_lock = threading.Lock()
_live_client = None


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict]:
    if not REGISTRY_PATH.exists():
        return {}
    with REGISTRY_PATH.open(encoding="utf-8") as handle:
        return {r["doc_id"]: r for r in (json.loads(l) for l in handle if l.strip())}


@lru_cache(maxsize=64)
def _document_chunks(doc_id: str) -> list[dict]:
    if not CHUNKS_PATH.exists():
        return []
    chunks = []
    with CHUNKS_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                chunk = json.loads(line)
                if chunk.get("doc_id") == doc_id:
                    chunks.append(chunk)
    return chunks


def _lex_client():
    """One shared client, so the crawl delay is honoured across concurrent questions."""
    global _live_client
    with _client_lock:
        if _live_client is None:
            from parser.lex.client import LexClient

            _live_client = LexClient(
                settings.lex_base_url, settings.lex_request_delay, DATA_DIR / "cache"
            )
        return _live_client


def _queue(doc_id: str, reason: str) -> None:
    """A question that finds stale data feeds the next refresh instead of being lost."""
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "doc_id": doc_id,
                    "reason": reason,
                    "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
            )
            + "\n"
        )


class ToolBox:
    """Executes the model's tool calls and keeps a log of what it asked for."""

    def __init__(self, retriever) -> None:
        self.retriever = retriever
        self.calls: list[dict] = []
        # what each call returned, so the answer can cite exactly what the model saw
        self.results: list[tuple[dict, dict]] = []
        self.live_sources: list[dict] = []

    async def run(self, name: str, args: dict) -> dict:
        call = {"tool": name, "args": args}
        self.calls.append(call)
        handler = getattr(self, f"_{name}", None)
        if handler is None:
            result: dict = {"error": f"noma'lum vosita: {name}"}
        else:
            try:
                result = await handler(**args)
            except TypeError as exc:
                result = {"error": f"noto'g'ri argumentlar: {exc}"}
            except Exception as exc:
                logger.exception("tool %s failed", name)
                result = {"error": str(exc)}
        self.results.append((call, result))
        return result

    async def _search_legal_base(self, query: str, doc_type: str | None = None) -> dict:
        filters = SearchFilters(doc_type=doc_type) if doc_type else SearchFilters()
        hits = await self.retriever.hybrid_search(query, k=6, filters=filters)
        return {
            "results": [
                {
                    "doc_id": hit.payload.get("doc_id"),
                    "doc_title": hit.payload.get("doc_title"),
                    "article_no": hit.payload.get("article_no_display")
                    or hit.payload.get("article_no"),
                    "article_title": hit.payload.get("article_title"),
                    "text": (hit.payload.get("text") or "")[:SNIPPET],
                    "source_url": hit.payload.get("source_url"),
                }
                for hit in hits
            ]
        }

    async def _get_article(self, doc_id: str, article_no: str) -> dict:
        parts = [
            chunk
            for chunk in _document_chunks(doc_id)
            if str(chunk.get("article_no")) == str(article_no)
        ]
        if not parts:
            return {"error": f"{doc_id} hujjatida {article_no}-modda topilmadi"}
        parts.sort(key=lambda c: c.get("part", 0))
        first = parts[0]
        return {
            "doc_id": doc_id,
            "doc_title": first.get("doc_title"),
            "article_no": first.get("article_no_display") or first.get("article_no"),
            "article_title": first.get("article_title"),
            "chapter": first.get("chapter"),
            "status": first.get("status"),
            "text": "\n\n".join(chunk.get("text", "") for chunk in parts),
            "source_url": first.get("source_url"),
        }

    async def _get_document_structure(self, doc_id: str) -> dict:
        record = _registry().get(doc_id)
        if record is None:
            return {"error": f"{doc_id} reyestrda yo'q"}
        seen: set[str] = set()
        articles = []
        for chunk in _document_chunks(doc_id):
            if chunk.get("part") != 0:
                continue
            key = str(chunk.get("article_no"))
            if key in seen:
                continue
            seen.add(key)
            articles.append(
                {
                    "article_no": chunk.get("article_no_display") or chunk.get("article_no"),
                    "article_title": chunk.get("article_title"),
                    "chapter": chunk.get("chapter"),
                }
            )
        return {
            "doc_id": doc_id,
            "title": record.get("title"),
            "status": record.get("status"),
            "articles_count": len(articles),
            "articles": articles[:200],
        }

    async def _check_lex_live(self, doc_id: str) -> dict:
        record = _registry().get(doc_id)
        result = await asyncio.to_thread(self._fetch_live_document, doc_id)
        if "error" in result:
            return result

        stored = MARKDOWN_DIR / f"{doc_id}.md"
        stale = None
        if stored.exists():
            from parser.lex.diff import frontmatter

            stored_hash = frontmatter(stored.read_text(encoding="utf-8")).get("content_hash")
            stale = stored_hash != result["content_hash"]
            if stale:
                _queue(doc_id, "check_lex_live: bazadagi versiya eskirgan")

        payload = {
            "doc_id": doc_id,
            "title": result["title"],
            "articles": result["articles"],
            "checked_live": True,
            "base_is_stale": stale,
            "source_url": f"{settings.lex_base_url}/uz/docs/{doc_id}",
        }
        if record is not None:
            payload["registry_status"] = record.get("status")
        self.live_sources.append(
            {"doc_title": result["title"], "source_url": payload["source_url"], "live": True}
        )
        return payload

    def _fetch_live_document(self, doc_id: str) -> dict:
        from parser.lex.extract import extract_document

        try:
            html = _lex_client().get(f"/uz/docs/{doc_id}", use_cache=False)
            document = extract_document(doc_id, html)
        except Exception as exc:
            return {"error": f"lex.uz javob bermadi: {exc}"}
        return {
            "title": document.title,
            "articles": len(document.articles),
            "content_hash": document.content_hash(),
        }

    async def _search_lex_live(self, query: str) -> dict:
        rows = await asyncio.to_thread(self._fetch_live_search, query)
        for row in rows:
            self.live_sources.append(
                {"doc_title": row["title"], "source_url": row["url"], "live": True}
            )
        return {"checked_live": True, "results": rows}

    def _fetch_live_search(self, query: str) -> list[dict]:
        params = {"lang": "4", "status": "Y", "minor": "N", "query": query}
        try:
            html = _lex_client().get(f"/uz/search/all?{urlencode(params)}", use_cache=False)
        except Exception as exc:
            logger.warning("live search failed: %s", exc)
            return []
        rows = []
        for row in HTMLParser(html).css("tr.dd-table__main-item")[:LIVE_RESULTS]:
            link = row.css_first("div.dd-table__main-left-desc a")
            if link is None:
                continue
            href = link.attributes.get("href") or ""
            rows.append(
                {
                    "doc_id": href.rsplit("/", 1)[-1],
                    "title": link.text(strip=True),
                    "url": f"{settings.lex_base_url}{href}",
                    "in_base": href.rsplit("/", 1)[-1] in _registry(),
                }
            )
        return rows
