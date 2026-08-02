"""Understand what was asked before deciding how to answer it.

The assistant used to make this decision with a list of regular expressions. That works
for "salom" and fails for everything a person actually types: "sen nimaga qodirsan",
"menga qanday foyda berasan", "nima ish qilasan" all went to the corpus and came back
with articles of the Labour Code, which is a wrong answer delivered confidently.

So the question is classified first. Patterns still run — they are free and they settle
the obvious cases without a network call — and only what they cannot settle is put to
the model. A classification that fails for any reason falls through to a legal search,
because answering a legal question conversationally is a worse failure than the reverse.
"""

import logging
import re

from . import selfinfo
from .llm import LLMClient, parse_json

logger = logging.getLogger(__name__)

CONVERSATION = "suhbat"
LEGAL = "huquqiy"
ACCOUNT = "hisob"
DRAFT = "hujjat"
OFF_TOPIC = "tashqari"

KNOWN = {CONVERSATION, LEGAL, ACCOUNT, DRAFT, OFF_TOPIC}

MAX_CLASSIFIED_CHARS = 600

# greetings, thanks, and questions about the assistant itself
META_RE = re.compile(
    r"^\s*(salom|assalomu\s+alaykum|xayrli\s+(tong|kun|kech|oqshom)|hormang"
    r"|привет|здравствуй\w*|добрый\s+(день|вечер)|доброе\s+утро)[\s!.,?]*$"
    r"|^\s*(rahmat|katta\s+rahmat|tashakkur|спасибо|благодарю)[\s!.,?]*$"
    r"|^\s*(xayr|ko'?rishguncha|пока|до\s+свидания)[\s!.,?]*$",
    re.IGNORECASE,
)

# an explicit article number or code name is a legal question whatever else it contains
LEGAL_MARKER_RE = re.compile(
    r"\d+\s*[-‑]?\s*modda|\bmodda\b|\bkodeks|\bqonun\b|\bstat(ya|ʼya|'ya)\b|\bстат[ья]"
    r"|\bкодекс|\bзакон\b",
    re.IGNORECASE,
)

# someone asking for a document to be written, not for a norm to be explained
DRAFT_RE = re.compile(
    r"\bariza\b|\bshikoyat\b|\bda'?vo\s+arizasi\b|\btushuntirish\s+xati\b|\bbayonot\b"
    r"|\btalabnoma\b|\bxat\s+(yoz|tayyorla|tuz)|hujjat\s+(yoz|tayyorla|tuz)"
    r"|\bprezentatsiya\b|\bslayd\w*\b|\bпрезентац\w+|\bслайд\w*"
    r"|\bзаявлени[ея]\b|\bжалоб[ауы]\b|\bиск\w*\s+заявлени",
    re.IGNORECASE,
)

CLASSIFIER_SYSTEM = f"""Sen O'zbekiston qonunchiligi bo'yicha yordamchining yo'naltiruvchi qismisan.
Foydalanuvchi xabarini o'qib, uni bitta toifaga ajratasan. Javobga qonun matnini yozma,
faqat JSON qaytar.

Toifalar:
- "{LEGAL}" — huquq, qonun, majburiyat, jazo, huquqbuzarlik, shartnoma, sud, soliq,
  mehnat munosabatlari haqidagi savol. Foydalanuvchi o'z boshidan kechirgan vaziyatni
  bayon qilsa ham shu toifa.
- "{DRAFT}" — foydalanuvchi hujjat yozib berishni so'raydi: ariza, shikoyat, da'vo
  arizasi, tushuntirish xati yoki mavzu bo'yicha prezentatsiya/slayd.
- "{CONVERSATION}" — salomlashish, minnatdorchilik yoki yordamchining o'zi haqida
  savol: nima qila olasan, kimsan, qanday ishlaysan, qanday savol berish mumkin.
- "{ACCOUNT}" — foydalanuvchining o'z hisobi: tarifi, qolgan savollari, chegarasi.
- "{OFF_TOPIC}" — huquqqa umuman aloqasi yo'q: ob-havo, sport, retsept, dasturlash,
  shaxsiy suhbat.

Faqat shu shaklda javob ber:
{{"toifa": "...", "sabab": "3-5 so'z"}}"""


def _fast_path(question: str, has_attachment: bool) -> str | None:
    """What can be decided without asking anyone."""
    if has_attachment:
        return LEGAL
    text = question.strip()
    if not text:
        return CONVERSATION
    if selfinfo.is_account_question(text):
        return ACCOUNT
    if META_RE.search(text):
        return CONVERSATION
    if DRAFT_RE.search(text):
        return DRAFT
    if LEGAL_MARKER_RE.search(text):
        return LEGAL
    if len(text) > MAX_CLASSIFIED_CHARS:
        # a long message is somebody describing their situation, not small talk
        return LEGAL
    return None


async def classify(question: str, llm: LLMClient, has_attachment: bool = False) -> str:
    decided = _fast_path(question, has_attachment)
    if decided is not None:
        return decided

    try:
        raw = await llm.generate(
            f"Xabar: {question}",
            system=CLASSIFIER_SYSTEM,
            temperature=0,
            json_output=True,
        )
        parsed = parse_json(raw)
    except Exception as exc:  # a router that breaks must not take the answer with it
        logger.warning("intent classification failed, treating as legal: %s", exc)
        return LEGAL

    if not isinstance(parsed, dict):
        return LEGAL
    label = str(parsed.get("toifa") or "").strip().lower()
    if label not in KNOWN:
        logger.warning("classifier returned an unknown label: %r", label)
        return LEGAL
    logger.info("intent %s (%s)", label, parsed.get("sabab"))
    return label
