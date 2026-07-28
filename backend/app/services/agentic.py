"""Answer by letting the model drive the search itself.

The scheduled refresh keeps the corpus current between runs; this path covers the gap
inside a single question — the model can look at lex.uz when the base cannot answer, and
what it finds there feeds the next refresh.
"""

import logging

from .generate import DISCLAIMER, SYSTEM_PROMPT, build_sources
from .llm import LLMClient
from .tools import MAX_TOOL_CALLS, TOOL_DECLARATIONS, ToolBox

logger = logging.getLogger(__name__)

TOOL_RULES = f"""Vositalardan foydalanish qoidalari:
- Har doim `search_legal_base` dan boshla.
- `get_article` ni matn kesilgan yoki qo'shni modda kerak bo'lgandagina chaqir.
- `search_legal_base` javobida `coverage: "weak"` bo'lsa, bu bazada shunday tushuncha
  yo'qligini bildiradi: `missing_terms` dagi so'zlar korpusda umuman uchramaydi.
  Natijalar qanchalik ishonchli ko'rinmasin, ular boshqa tushuncha haqida — javob
  o'rniga qo'yma. Bunday holatda `search_lex_live` ni chaqirish **majburiy**.
- `check_lex_live` va `search_lex_live` sekin va lex.uz ga yuk beradi. Ularni yuqoridagi
  holatdan tashqari faqat ma'lumot eskirgan bo'lishi mumkin bo'lganda chaqir.
- Jami {MAX_TOOL_CALLS} tadan ortiq vosita chaqirmang.
- lex.uz dan real vaqtda olingan ma'lumotni javobda "real vaqtda tekshirildi" deb belgila.
- lex.uz da topilgan hujjat bazada bo'lmasa, uning matnini o'ylab topma: nomi va havolasini
  ko'rsatib, tafsilotlar bazada yo'qligini ayt."""


async def answer_with_tools(
    question: str,
    retriever,
    llm: LLMClient,
    history: list[dict] | None = None,
    agent_prompt: str | None = None,
    attachment_block: str | None = None,
    extra_parts: list[dict] | None = None,
) -> tuple[str, list[dict], list[dict]]:
    """Returns the answer, its sources, and the log of what the model called."""
    toolbox = ToolBox(retriever)
    system = "\n\n".join(part for part in (SYSTEM_PROMPT, TOOL_RULES, agent_prompt) if part)

    prompt = f"Savol: {question}"
    if attachment_block:
        prompt = f"{attachment_block}\n\n{prompt}"
    if history:
        turns = "\n".join(f"{item['role']}: {item['content']}" for item in history[-6:])
        prompt = f"Suhbat tarixi:\n{turns}\n\n{prompt}"

    answer = await llm.generate_with_tools(
        prompt,
        TOOL_DECLARATIONS,
        toolbox.run,
        system=system,
        max_calls=MAX_TOOL_CALLS,
        extra_parts=extra_parts,
    )
    if not answer.strip():
        answer = f"Bu savol bo'yicha bazada aniq norma topilmadi.\n\n{DISCLAIMER}"

    for call in toolbox.calls:
        logger.info("tool call %s %s", call["tool"], call["args"])

    return answer, _sources(toolbox), toolbox.calls


def _sources(toolbox: ToolBox) -> list[dict]:
    """Whatever the model actually looked at, with live lookups marked as such."""
    sources: list[dict] = []
    seen: set[str] = set()

    for call, result in toolbox.results:
        for item in _cited(call, result):
            key = f"{item.get('doc_id')}:{item.get('article_no')}:{item.get('source_url')}"
            if key in seen:
                continue
            seen.add(key)
            sources.append(item)

    for live in toolbox.live_sources:
        key = live["source_url"]
        if key not in seen:
            seen.add(key)
            sources.append(live)
    return sources


def _cited(call: dict, result: dict) -> list[dict]:
    if call["tool"] == "search_legal_base":
        # the model was told not to answer from these, so listing them under the answer
        # would present the neighbouring concept as the source after all
        if result.get("coverage") == "weak":
            return []
        return [
            {
                "doc_id": row.get("doc_id"),
                "doc_title": row.get("doc_title"),
                "article_no": row.get("article_no"),
                "article_title": row.get("article_title"),
                "source_url": row.get("source_url"),
                "snippet": (row.get("text") or "")[:300],
            }
            for row in result.get("results", [])
        ]
    if call["tool"] == "get_article" and "error" not in result:
        return [
            {
                "doc_id": result.get("doc_id"),
                "doc_title": result.get("doc_title"),
                "article_no": result.get("article_no"),
                "article_title": result.get("article_title"),
                "source_url": result.get("source_url"),
                "snippet": (result.get("text") or "")[:300],
            }
        ]
    return []


__all__ = ["answer_with_tools", "build_sources"]
