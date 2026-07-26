import logging
from typing import AsyncIterator

from .llm import LLMClient
from .retrieval import Hit

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "Javoblar tavsiyaviy xarakterga ega, aniq huquqiy maslahat uchun yuristga murojaat qiling."
)
NOT_FOUND = "Bu savol bo'yicha bazada aniq norma topilmadi"
MAX_CONTEXT_CHARS = 2500
SNIPPET_CHARS = 300

SYSTEM_PROMPT = f"""Sen O'zbekiston Respublikasi qonunchiligi bo'yicha yordam beruvchi yordamchisan.

Qat'iy qoidalar:
1. Faqat quyida berilgan kontekstga tayan. Kontekstda yo'q narsani yozma.
2. Modda matnini o'zgartirma, qayta yozma va o'ylab topma. Raqamlarni, muddatlarni va
   summalarni aynan kontekstdagidek keltir.
3. Har bir da'vo yonida manbani ko'rsat: hujjat nomi va modda raqami.
   Masalan: (Fuqarolik kodeksi, 173-modda).
4. Agar kontekstda javob bo'lmasa, ochiq ayt: "{NOT_FOUND}". Taxmin qilma.
5. Foydalanuvchi qaysi tilda so'rasa, o'sha tilda javob ber (o'zbek yoki rus).
6. Javob aniq va qisqa bo'lsin, ortiqcha muqaddima yozma.
7. Javob oxirida alohida qatorda quyidagini yoz:
   {DISCLAIMER}"""

CONTEXT_TEMPLATE = """[{index}] {doc_title}, {article}-modda. {title}
{text}"""

USER_TEMPLATE = """Kontekst:
{context}

Savol: {question}"""


def build_context(hits: list[Hit]) -> str:
    blocks = []
    for index, hit in enumerate(hits, start=1):
        payload = hit.payload
        blocks.append(
            CONTEXT_TEMPLATE.format(
                index=index,
                doc_title=payload.get("doc_title", ""),
                article=payload.get("article_no_display") or payload.get("article_no") or "?",
                title=payload.get("article_title") or "",
                text=(payload.get("text") or "")[:MAX_CONTEXT_CHARS],
            )
        )
    return "\n\n".join(blocks)


def answer_is_grounded(answer: str) -> bool:
    """A 'not found' answer must not be presented with a list of sources."""
    return NOT_FOUND.lower() not in answer.lower()


def build_sources(hits: list[Hit]) -> list[dict]:
    sources = []
    seen: set[str] = set()
    for hit in hits:
        payload = hit.payload
        key = f"{payload.get('doc_id')}:{payload.get('article_no')}"
        if key in seen:
            continue
        seen.add(key)
        text = payload.get("text") or ""
        sources.append(
            {
                "doc_id": payload.get("doc_id"),
                "doc_title": payload.get("doc_title"),
                "article_no": payload.get("article_no_display") or payload.get("article_no"),
                "article_title": payload.get("article_title"),
                "source_url": payload.get("source_url"),
                "snippet": text[:SNIPPET_CHARS] + ("..." if len(text) > SNIPPET_CHARS else ""),
            }
        )
    return sources


def build_prompt(question: str, hits: list[Hit], history: list[dict] | None = None) -> str:
    prompt = USER_TEMPLATE.format(context=build_context(hits), question=question)
    if history:
        turns = "\n".join(f"{item['role']}: {item['content']}" for item in history[-6:])
        prompt = f"Suhbat tarixi:\n{turns}\n\n{prompt}"
    return prompt


def empty_answer() -> str:
    return f"{NOT_FOUND}.\n\n{DISCLAIMER}"


async def generate_answer(
    question: str,
    hits: list[Hit],
    llm: LLMClient,
    history: list[dict] | None = None,
    agent_prompt: str | None = None,
) -> str:
    if not hits:
        return empty_answer()
    system = SYSTEM_PROMPT + (f"\n\n{agent_prompt}" if agent_prompt else "")
    return await llm.generate(build_prompt(question, hits, history), system=system)


async def stream_answer(
    question: str,
    hits: list[Hit],
    llm: LLMClient,
    history: list[dict] | None = None,
    agent_prompt: str | None = None,
) -> AsyncIterator[str]:
    if not hits:
        yield empty_answer()
        return
    system = SYSTEM_PROMPT + (f"\n\n{agent_prompt}" if agent_prompt else "")
    async for piece in llm.stream(build_prompt(question, hits, history), system=system):
        yield piece
