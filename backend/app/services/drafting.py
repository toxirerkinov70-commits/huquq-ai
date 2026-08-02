"""Turning an answer into a document the person can actually hand in.

Knowing which article applies is half of what somebody needs. The other half is a sheet
of paper addressed to the right office, and that is what this produces: a formal letter
in the shape Uzbek offices expect, or a short set of slides when the request is to
explain a topic rather than to claim something.

Two rules carry over from the answers. Nothing is invented: the legal grounds come from
the retrieved articles and nowhere else. And nothing is quietly filled in — a name or a
date the user never gave stays a bracketed blank and is listed back to them, because a
plausible invented address is worse than an obvious gap.
"""

import logging

from .llm import LLMClient, parse_json
from .retrieval import Hit

logger = logging.getLogger(__name__)

DOCUMENT = "hujjat"
SLIDES = "slayd"

DOC_TYPES = {
    "ariza": "Ariza",
    "shikoyat": "Shikoyat",
    "davo": "Da'vo arizasi",
    "tushuntirish": "Tushuntirish xati",
    "bayonot": "Bayonot",
}

MAX_CONTEXT_CHARS = 1800
MAX_CONTEXT_ARTICLES = 6

DISCLAIMER = (
    "Ushbu loyiha namuna sifatida tayyorlandi va yuridik kuchga ega emas. "
    "Topshirishdan oldin yurist bilan tekshiring."
)

_SHARED_RULES = """Qoidalar:
- Faqat berilgan kontekstdagi normalarga tayan. Kontekstda yo'q moddani keltirma.
- Foydalanuvchi aytmagan ma'lumotni o'ylab topma. Ism, sana, manzil, summa noma'lum
  bo'lsa, o'rniga kvadrat qavsda joy qoldir: [F.I.Sh.], [sana], [manzil].
- Qoldirilgan joylarning hammasini "toldirilishi_kerak" ro'yxatiga yoz.
- Rasmiy, quruq ish uslubi. Bo'rttirma, his-tuyg'u qo'shma.
- Foydalanuvchi tilida yoz (o'zbek yoki rus).
Javobni faqat JSON qaytar, boshqa hech narsa yozma."""

DOCUMENT_SYSTEM = f"""Sen O'zbekiston Respublikasi qonunchiligi bo'yicha rasmiy hujjat tuzuvchi yordamchisan.
Foydalanuvchining vaziyati va tegishli qonun moddalari asosida rasmiy hujjat loyihasini
tayyorlaysan.

{_SHARED_RULES}

JSON tuzilishi:
{{
  "tur": "ariza | shikoyat | davo | tushuntirish | bayonot",
  "sarlavha": "hujjat sarlavhasi, masalan ARIZA",
  "kimga": "hujjat yuboriladigan organ yoki mansabdor shaxs",
  "kimdan": "ariza beruvchi: F.I.Sh., manzil, telefon",
  "matn": ["xatboshi", "xatboshi", "..."],
  "talablar": ["so'ralayotgan birinchi narsa", "ikkinchi", "..."],
  "ilovalar": ["ilova qilinadigan hujjat nomi", "..."],
  "asos": ["Mehnat kodeksi 174-modda", "..."],
  "toldirilishi_kerak": ["[F.I.Sh.] — ariza beruvchining to'liq ismi", "..."]
}}"""

SLIDES_SYSTEM = f"""Sen O'zbekiston Respublikasi qonunchiligini tushuntiruvchi yordamchisan.
Foydalanuvchi so'ragan mavzu bo'yicha qisqa taqdimot tayyorlaysan.

{_SHARED_RULES}
- 4 tadan 6 tagacha slayd. Har slaydda 2-4 ta punkt, har punkt bitta qisqa jumla.
- Birinchi slayd — mavzu va u nima haqidaligi. Oxirgi slayd — amaliy xulosa.

JSON tuzilishi:
{{
  "sarlavha": "taqdimot nomi",
  "slaydlar": [
    {{"sarlavha": "slayd nomi", "punktlar": ["...", "..."], "asos": "Mehnat kodeksi 174-modda"}}
  ]
}}"""


def wants_slides(question: str) -> bool:
    lowered = question.lower()
    return any(
        word in lowered
        for word in ("prezentatsiya", "prezentacia", "slayd", "slide", "презентац", "слайд")
    )


def build_context(hits: list[Hit]) -> str:
    blocks = []
    for hit in hits[:MAX_CONTEXT_ARTICLES]:
        payload = hit.payload
        article = payload.get("article_no_display") or payload.get("article_no") or "?"
        blocks.append(
            f"{payload.get('doc_title', '')}, {article}-modda. "
            f"{payload.get('article_title') or ''}\n"
            f"{(payload.get('text') or '')[:MAX_CONTEXT_CHARS]}"
        )
    return "\n\n".join(blocks)


def _prompt(question: str, hits: list[Hit], history: list[dict] | None) -> str:
    parts = []
    if history:
        turns = "\n".join(f"{item['role']}: {item['content']}" for item in history[-4:])
        parts.append(f"Suhbat tarixi:\n{turns}")
    parts.append(f"Tegishli normalar:\n{build_context(hits)}")
    parts.append(f"Foydalanuvchi so'rovi: {question}")
    return "\n\n".join(parts)


def _clean_list(value: object, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [str(item).strip() for item in value if str(item).strip()]
    return items[:limit]


def _normalise_document(data: dict) -> dict:
    doc_type = str(data.get("tur") or "ariza").strip().lower()
    if doc_type not in DOC_TYPES:
        doc_type = "ariza"
    title = str(data.get("sarlavha") or DOC_TYPES[doc_type]).strip()
    return {
        "kind": DOCUMENT,
        "doc_type": doc_type,
        "title": title.upper(),
        "recipient": str(data.get("kimga") or "").strip(),
        "sender": str(data.get("kimdan") or "").strip(),
        "body": _clean_list(data.get("matn")),
        "requests": _clean_list(data.get("talablar")),
        "attachments": _clean_list(data.get("ilovalar"), limit=10),
        "grounds": _clean_list(data.get("asos"), limit=10),
        "todo": _clean_list(data.get("toldirilishi_kerak"), limit=15),
        "disclaimer": DISCLAIMER,
    }


def _normalise_slides(data: dict) -> dict:
    slides = []
    raw = data.get("slaydlar")
    if isinstance(raw, list):
        for item in raw[:8]:
            if not isinstance(item, dict):
                continue
            bullets = _clean_list(item.get("punktlar"), limit=5)
            if not bullets:
                continue
            slides.append(
                {
                    "title": str(item.get("sarlavha") or "").strip(),
                    "bullets": bullets,
                    "grounds": str(item.get("asos") or "").strip(),
                }
            )
    return {
        "kind": SLIDES,
        "title": str(data.get("sarlavha") or "").strip(),
        "slides": slides,
        "disclaimer": DISCLAIMER,
    }


class DraftingError(RuntimeError):
    pass


async def draft(
    question: str,
    hits: list[Hit],
    llm: LLMClient,
    history: list[dict] | None = None,
) -> dict:
    """Produce either a formal document or a set of slides, whichever was asked for."""
    slides = wants_slides(question)
    raw = await llm.generate(
        _prompt(question, hits, history),
        system=SLIDES_SYSTEM if slides else DOCUMENT_SYSTEM,
        temperature=0.3,
        json_output=True,
    )
    parsed = parse_json(raw)
    if not isinstance(parsed, dict):
        raise DraftingError("model did not return a document object")

    result = _normalise_slides(parsed) if slides else _normalise_document(parsed)
    if slides and not result["slides"]:
        raise DraftingError("model returned no slides")
    if not slides and not result["body"]:
        raise DraftingError("model returned an empty document body")
    logger.info("drafted %s", result["kind"])
    return result


def summary_line(document: dict) -> str:
    """What the assistant says in the chat alongside the attached draft."""
    if document["kind"] == SLIDES:
        count = len(document["slides"])
        return (
            f"**{document['title']}** mavzusida {count} ta slayd tayyorladim. "
            "Quyidan ko'rishingiz, PDF yoki rasm sifatida yuklab olishingiz mumkin."
        )
    lines = [
        f"**{document['title']}** loyihasini tayyorladim — quyidan ko'ring, "
        "PDF yoki rasm sifatida yuklab oling."
    ]
    if document["todo"]:
        lines.append("")
        lines.append("To'ldirishingiz kerak bo'lgan joylar:")
        lines.extend(f"- {item}" for item in document["todo"])
    return "\n".join(lines)
