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
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from ..config import settings
from . import corpus, coverage
from .corpus import DATA_DIR
from .retrieval import SearchFilters

logger = logging.getLogger(__name__)

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
                "act_type": {
                    "type": "integer",
                    "description": (
                        "Ixtiyoriy: hujjat turi bo'yicha cheklash. "
                        "1 — Konstitutsiya, 21 — kodekslar, 22 — qonunlar, "
                        "3 — prezident hujjatlari, 4 — hukumat qarorlari"
                    ),
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


def _registry() -> dict[str, dict]:
    return corpus.registry.as_map()


def _document_chunks(doc_id: str) -> list[dict]:
    return corpus.chunks.chunks(doc_id)


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


def _doc_id_from_href(href: str) -> str:
    """The search page links carry the query and an anchor: /uz/docs/-8336553?query=bond#sr-1."""
    path = href.split("?", 1)[0].split("#", 1)[0]
    return path.rstrip("/").rsplit("/", 1)[-1]


def _queue(doc_id: str, reason: str, title: str | None = None) -> None:
    """A question that finds stale or missing data feeds the next refresh instead of being lost."""
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if any(entry.get("doc_id") == doc_id for entry in _queued()):
        return
    with QUEUE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "reason": reason,
                    "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def _queued() -> list[dict]:
    """A popular question must not write the same document into the queue on every ask."""
    if not QUEUE_PATH.exists():
        return []
    with QUEUE_PATH.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class ToolBox:
    """Executes the model's tool calls and keeps a log of what it asked for."""

    def __init__(self, retriever, agent=None) -> None:
        self.retriever = retriever
        self.agent = agent
        self.calls: list[dict] = []
        # what each call returned, so the answer can cite exactly what the model saw
        self.results: list[tuple[dict, dict]] = []
        self.live_sources: list[dict] = []
        # set when a search found the corpus has no word for what was asked
        self.weak_coverage = False

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

    async def _search_legal_base(self, query: str, act_type: int | None = None) -> dict:
        # the mode the user picked narrows the corpus here exactly as it does on the
        # streaming path, so the same question does not reach two different bases
        filters = self.agent.filters() if self.agent is not None else SearchFilters()
        if act_type is not None and not filters.act_types:
            filters = replace(filters, act_types=[int(act_type)])
        hits = await self.retriever.hybrid_search(query, k=6, filters=filters)
        payloads = [hit.payload for hit in hits]
        result = {
            "results": [
                {
                    "doc_id": payload.get("doc_id"),
                    "doc_title": payload.get("doc_title"),
                    "article_no": payload.get("article_no_display") or payload.get("article_no"),
                    "article_title": payload.get("article_title"),
                    "text": (payload.get("text") or "")[:SNIPPET],
                    "source_url": payload.get("source_url"),
                }
                for payload in payloads
            ]
        }
        # ranking cannot say whether these are the right articles or merely the closest
        # ones; the vocabulary check can, and the model reads it here beside the results
        verdict = coverage.assess(query, payloads)
        if verdict is not None:
            self.weak_coverage = verdict["coverage"] == "weak"
            result.update(verdict)
        else:
            result["coverage"] = "good"
        return result

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
            # the question just proved the corpus is missing this document; queueing it
            # here is how user traffic feeds the refresh instead of the gap persisting
            if not row["in_base"] and row["doc_id"]:
                _queue(row["doc_id"], f"search_lex_live: bazada yo'q ({query})", row["title"])
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
            doc_id = _doc_id_from_href(href)
            rows.append(
                {
                    "doc_id": doc_id,
                    "title": link.text(strip=True),
                    "url": f"{settings.lex_base_url}{href}",
                    "in_base": doc_id in _registry(),
                }
            )
        return rows
