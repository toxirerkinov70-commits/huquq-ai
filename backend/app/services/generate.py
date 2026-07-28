import logging
import re
from typing import AsyncIterator

from .llm import LLMClient
from .retrieval import Hit

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "Javoblar tavsiyaviy xarakterga ega, aniq huquqiy maslahat uchun yuristga murojaat qiling."
)
NOT_FOUND = "Bu savol bo'yicha bazada aniq norma topilmadi"
PARTIAL = "Savolning quyidagi qismi bazada topilmadi"
MAX_CONTEXT_CHARS = 2500
SNIPPET_CHARS = 300

# "173-modda", "289¹-modda", "15 modda" — a cited article means the answer rests on
# the context rather than on nothing
CITATION_RE = re.compile(r"\d[\d¹²³⁰-⁹\s-]*modda", re.IGNORECASE)

CAPABILITIES = """Sening imkoniyatlaring:
- Bazada O'zbekiston Respublikasining amaldagi qonunchiligi bor: Konstitutsiya,
  barcha kodekslar, qonunlar hamda Oliy sud Plenumi qarorlari va sud amaliyoti.
- Savolga mos qonun moddasini topib, uni sodda tilda tushuntirasan va har doim
  manba (hujjat nomi, modda raqami, lex.uz havolasi) ko'rsatasan.
- Foydalanuvchi vaziyatini, shartnomasini yoki sud qarorini normalarga tayangan
  holda tahlil qilib, amaliy tavsiya berasan.
- Yuklangan hujjatni (PDF, rasm, matn) o'qib, mazmunini tushuntirasan va
  qonunchilikka mosligini tekshirasan.
- Soha bo'yicha rejimlar bor: jinoyat, fuqarolik, soliq, mehnat, shartnoma, sud."""

SYSTEM_PROMPT = f"""Sen Huquq AI — O'zbekiston Respublikasi qonunchiligi bo'yicha yordam beruvchi yordamchisan.

{CAPABILITIES}

Qat'iy qoidalar:
1. Faqat quyida berilgan kontekstga tayan. Kontekstda yo'q narsani yozma.
2. Modda matnini o'zgartirma, qayta yozma va o'ylab topma. Raqamlarni, muddatlarni va
   summalarni aynan kontekstdagidek keltir. Kontekstda summa, miqdor yoki muddat
   ko'rsatilmagan bo'lsa, uni o'zingdan yozma — ko'rsatilmaganini ayt.
3. Har bir da'vo yonida manbani ko'rsat: hujjat nomi va modda raqami.
   Masalan: (Fuqarolik kodeksi, 173-modda).
4. Agar kontekstda javob bo'lmasa, ochiq ayt: "{NOT_FOUND}". Taxmin qilma.
5. Kontekstdagi modda boshqa tartib-taomil yoki boshqa holat haqida bo'lsa, uni
   so'ralgan savolning javobi sifatida ko'rsatma. Yaqin mavzudagi norma javobning
   o'rnini bosmaydi.
6. Savol bir necha qismdan iborat bo'lsa, kontekst javob beradigan qismini yoz,
   so'ng qolganini alohida qatorda ko'rsat:
   "{PARTIAL}: ..." — va nima topilmaganini aniq sanab o't.
7. Foydalanuvchi qaysi tilda so'rasa, o'sha tilda javob ber (o'zbek yoki rus).
8. Javob aniq va qisqa bo'lsin, ortiqcha muqaddima yozma.
9. "Javoblar tavsiyaviy xarakterga ega" degan ogohlantirishni yozma — uni interfeys
   har javob ostida o'zi ko'rsatadi.

Istisno holatlar:
- Savol qonunchilik haqida emas, balki salomlashish, minnatdorchilik yoki sening
  imkoniyatlaring haqida bo'lsa — kontekst talab qilinmaydi: qisqa, samimiy va aniq
  javob ber, "{NOT_FOUND}" dema va manba ko'rsatma.
- Foydalanuvchi o'z vaziyati, hujjati yoki sud qarori bo'yicha maslahat yoki tahlil
  so'rasa, kontekstdagi normalarni uning faktlariga tatbiq et va javobni shunday tuz:
  **Xulosa** — bir-ikki jumlada asosiy javob;
  **Huquqiy asos** — tayanilgan normalar, har biri manbasi bilan;
  **Tavsiya** — amaliy keyingi qadamlar.
  O'z bahoingni norma matni sifatida emas, tahlil sifatida taqdim et. Faktlar
  yetarli bo'lmasa, qaysi ma'lumot yetishmayotganini so'ra."""

# a message that greets, thanks, or asks about the assistant itself needs a
# conversational reply, not a corpus search; kept tight so real legal questions
# never match
META_PATTERNS = [
    r"^\s*(salom|assalomu\s+alaykum|xayrli\s+(tong|kun|kech|oqshom)|привет|здравствуй\w*|добрый\s+(день|вечер)|доброе\s+утро)[\s!.,?]*$",
    r"^\s*(rahmat|katta\s+rahmat|спасибо|благодарю)[\s!.,?]*$",
    r"(qanday|qanaqa|qay\s+tarzda)\s+yordam\s+ber",
    r"yordam\s+ber(a\s+olasan|asan)",
    r"nima(lar)?(ni)?\s+qil(a\s+olasan|asan)",
    r"\bkimsan\b|\b(sen|siz)\s+kim(san|siz)?\b",
    r"o'?zing\s+haqi?\w*\s+(gapir|aytib|so'zlab)",
    r"qanday\s+ishlaysan",
    r"qanday\s+savol(lar)?\s+(ber|so'?ra)",
    r"nima(lar)?(ni)?\s+so'?ra(shim|sam|sh)\s+mumkin",
    r"imkoniyat(lar)?ing",
    r"что\s+ты\s+умеешь|чем\s+(ты\s+)?можешь\s+помочь|кто\s+ты|как\s+(ты\s+)?работаешь|какие\s+вопросы",
]
META_RE = re.compile("|".join(META_PATTERNS), re.IGNORECASE)
META_MAX_CHARS = 200

CONVERSATIONAL_PROMPT = f"""Sen Huquq AI — O'zbekiston Respublikasi qonunchiligi bo'yicha yordamchisan.

{CAPABILITIES}

Foydalanuvchi hozir huquqiy savol emas, oddiy suhbat yozdi (salomlashish, minnatdorchilik
yoki sening imkoniyatlaring haqida savol). Qisqa va lo'nda javob ber:
- Salomlashsa — salomlash va nima qila olishingni bir-ikki jumlada ayt.
- Imkoniyatlaring haqida so'rasa — yuqoridagi ro'yxatga tayanib sodda tilda tushuntir
  va bitta-ikkita savol namunasini taklif qil.
- Minnatdorchilik bildirsa — qisqa javob qaytar.
Manba ko'rsatma, huquqiy norma keltirma, o'zingdan qonun o'ylab topma.
Foydalanuvchi tilida javob ber (o'zbek yoki rus)."""

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
    """A 'not found' answer must not be presented with a list of sources.

    A partial answer says a piece is missing while the rest still rests on real
    articles, so the phrase alone cannot decide: an answer that cites an article
    keeps its sources.
    """
    if CITATION_RE.search(answer):
        return True
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


def build_prompt(
    question: str,
    hits: list[Hit],
    history: list[dict] | None = None,
    attachment_block: str | None = None,
) -> str:
    prompt = USER_TEMPLATE.format(context=build_context(hits) or "(bo'sh)", question=question)
    if attachment_block:
        prompt = f"{attachment_block}\n\n{prompt}"
    if history:
        turns = "\n".join(f"{item['role']}: {item['content']}" for item in history[-6:])
        prompt = f"Suhbat tarixi:\n{turns}\n\n{prompt}"
    return prompt


def empty_answer() -> str:
    return f"{NOT_FOUND}."


SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
CITED_NO_RE = re.compile(r"(\d+[¹²³⁴⁵⁶⁷⁸⁹⁰]*)(?:\s*-\s*|\s+)modda", re.IGNORECASE)


def _normalize_no(value: object) -> str:
    return re.sub(r"[^0-9]", "", str(value).translate(SUPERSCRIPTS))


def filter_cited_sources(answer: str, sources: list[dict]) -> list[dict]:
    """Keep only the sources the answer actually cites.

    The reranker picks candidates before the answer exists, so a passage that lost
    the argument still sat in the list and was shown as a source. An article number
    in the answer is the reliable signal; article-less documents (Plenum rulings)
    are matched by their title words instead.
    """
    cited = {_normalize_no(match) for match in CITED_NO_RE.findall(answer)}
    if not cited:
        return sources
    answer_lower = answer.lower()
    kept = []
    for source in sources:
        article_no = source.get("article_no")
        if article_no:
            if _normalize_no(article_no) in cited:
                kept.append(source)
            continue
        title_words = set(re.findall(r"\w{6,}", (source.get("doc_title") or "").lower()))
        if sum(1 for word in title_words if word in answer_lower) >= 2:
            kept.append(source)
    return kept or sources


def is_conversational(question: str) -> bool:
    """Greetings and 'what can you do' questions skip retrieval entirely."""
    if len(question) > META_MAX_CHARS:
        return False
    return bool(META_RE.search(question))


def _conversational_prompt(question: str, history: list[dict] | None) -> str:
    if history:
        turns = "\n".join(f"{item['role']}: {item['content']}" for item in history[-6:])
        return f"Suhbat tarixi:\n{turns}\n\nXabar: {question}"
    return f"Xabar: {question}"


async def conversational_answer(
    question: str, llm: LLMClient, history: list[dict] | None = None
) -> str:
    return await llm.generate(
        _conversational_prompt(question, history), system=CONVERSATIONAL_PROMPT, temperature=0.6
    )


async def stream_conversational(
    question: str, llm: LLMClient, history: list[dict] | None = None
) -> AsyncIterator[str]:
    async for piece in llm.stream(
        _conversational_prompt(question, history), system=CONVERSATIONAL_PROMPT, temperature=0.6
    ):
        yield piece


async def generate_answer(
    question: str,
    hits: list[Hit],
    llm: LLMClient,
    history: list[dict] | None = None,
    agent_prompt: str | None = None,
    attachment_block: str | None = None,
    extra_parts: list[dict] | None = None,
) -> str:
    # an uploaded document is itself context, so an empty corpus result is not final
    if not hits and not attachment_block:
        return empty_answer()
    system = SYSTEM_PROMPT + (f"\n\n{agent_prompt}" if agent_prompt else "")
    return await llm.generate(
        build_prompt(question, hits, history, attachment_block),
        system=system,
        extra_parts=extra_parts,
    )


async def stream_answer(
    question: str,
    hits: list[Hit],
    llm: LLMClient,
    history: list[dict] | None = None,
    agent_prompt: str | None = None,
    attachment_block: str | None = None,
    extra_parts: list[dict] | None = None,
) -> AsyncIterator[str]:
    if not hits and not attachment_block:
        yield empty_answer()
        return
    system = SYSTEM_PROMPT + (f"\n\n{agent_prompt}" if agent_prompt else "")
    async for piece in llm.stream(
        build_prompt(question, hits, history, attachment_block),
        system=system,
        extra_parts=extra_parts,
    ):
        yield piece
