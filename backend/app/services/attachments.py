"""Uploaded files: validation, text extraction, and the analysis step.

PDF and images go to Gemini as inline media; docx and plain text are reduced to
text here, because the API does not accept office formats inline.
"""

import base64
import binascii
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field

from ..models import Attachment
from .llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

MAX_BYTES = 10 * 1024 * 1024
INLINE_MIMES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_MIMES = {"text/plain", "text/markdown"}
MAX_TEXT_CHARS = 40_000

DOCX_TAG_RE = re.compile(r"<[^>]+>")


class AttachmentError(ValueError):
    pass


@dataclass
class PreparedAttachment:
    name: str
    mime: str
    # inline media for gemini; empty when the document became plain text
    parts: list[dict] = field(default_factory=list)
    text: str = ""


def prepare(attachment: Attachment) -> PreparedAttachment:
    try:
        raw = base64.b64decode(attachment.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttachmentError("Fayl ma'lumotlari o'qib bo'lmadi.") from exc
    if len(raw) > MAX_BYTES:
        raise AttachmentError("Fayl hajmi 10 MB dan oshmasligi kerak.")
    if not raw:
        raise AttachmentError("Fayl bo'sh.")

    mime = attachment.mime.lower().split(";")[0].strip()
    if mime in INLINE_MIMES:
        part = {"inlineData": {"mimeType": mime, "data": attachment.data}}
        return PreparedAttachment(name=attachment.name, mime=mime, parts=[part])
    if mime == DOCX_MIME or attachment.name.lower().endswith(".docx"):
        return PreparedAttachment(
            name=attachment.name, mime=DOCX_MIME, text=_docx_text(raw)
        )
    if mime in TEXT_MIMES or attachment.name.lower().endswith((".txt", ".md")):
        return PreparedAttachment(
            name=attachment.name, mime="text/plain", text=_plain_text(raw)
        )
    raise AttachmentError(
        "Bu turdagi fayl qo'llab-quvvatlanmaydi. PDF, rasm (JPG/PNG/WEBP), DOCX yoki TXT yuklang."
    )


def _plain_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        raise AttachmentError("Fayldan matn topilmadi.")
    return text[:MAX_TEXT_CHARS]


def _docx_text(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise AttachmentError("DOCX faylni ochib bo'lmadi.") from exc
    # paragraph closes become line breaks before the tags are stripped
    xml = xml.replace("</w:p>", "\n")
    text = DOCX_TAG_RE.sub("", xml).strip()
    if not text:
        raise AttachmentError("Hujjatdan matn topilmadi.")
    return text[:MAX_TEXT_CHARS]


def prompt_block(prepared: PreparedAttachment, analysis: dict) -> str:
    """The document's place inside the generation prompt."""
    lines = [f"Foydalanuvchi hujjat yukladi: {prepared.name}"]
    if analysis.get("doc_kind"):
        lines.append(f"Hujjat turi: {analysis['doc_kind']}")
    if analysis.get("summary"):
        lines.append(f"Hujjat haqida qisqacha: {analysis['summary']}")
    if prepared.text:
        lines.append(f"Hujjat matni:\n{prepared.text}")
    else:
        lines.append("Hujjatning o'zi so'rovga ilova qilingan.")
    lines.append(
        "Yuklangan hujjat ham kontekst hisoblanadi: savol shu hujjatga tegishli bo'lsa, "
        "avval uning mazmuni va maqsadini qisqacha tushuntir, so'ng kontekstdagi "
        "normalarga solishtirib tahlil qil."
    )
    return "\n".join(lines)


ANALYZE_PROMPT = """Quyida foydalanuvchi yuklagan hujjat va uning savoli berilgan.

Hujjatni o'qib, JSON qaytar:
{{"summary": "hujjat nima haqida — 3-5 jumla, o'zbek tilida, asosiy faktlar bilan",
  "doc_kind": "hujjat turi (sud qarori, shartnoma, ariza, dalolatnoma ...)",
  "queries": ["hujjat va savolga mos qonunchilik bazasidan qidirish uchun 1-3 ta qisqa so'rov"]}}

Faqat hujjatda bor ma'lumotni yoz, taxmin qilma.

Savol: {question}{doc_block}"""


async def analyze(
    prepared: PreparedAttachment, question: str, llm: LLMClient
) -> dict:
    """One LLM pass over the document: summary plus search queries for the corpus."""
    doc_block = f"\n\nHujjat matni:\n{prepared.text}" if prepared.text else ""
    prompt = ANALYZE_PROMPT.format(question=question, doc_block=doc_block)
    try:
        data = await llm.generate_json(prompt, extra_parts=prepared.parts or None)
    except LLMError as exc:
        logger.warning("attachment analysis failed: %s", exc)
        return {"summary": "", "doc_kind": "", "queries": []}
    if not isinstance(data, dict):
        return {"summary": "", "doc_kind": "", "queries": []}
    queries = [q for q in data.get("queries") or [] if isinstance(q, str) and q.strip()]
    return {
        "summary": str(data.get("summary") or ""),
        "doc_kind": str(data.get("doc_kind") or ""),
        "queries": queries[:3],
    }
