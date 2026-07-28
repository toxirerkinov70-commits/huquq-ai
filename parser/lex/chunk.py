import logging
import re

from .extract import Article, Document

logger = logging.getLogger(__name__)

MAX_TOKENS = 1200
# a paragraph with no sentence breaks is kept whole up to this ceiling rather than
# cut mid-sentence; beyond it readability loses to the embedding input limit
HARD_MAX_TOKENS = 2000
SHORT_ARTICLE_CHARS = 100
# Uzbek Latin text runs at roughly 3.5 characters per token for Gemini's tokenizer
CHARS_PER_TOKEN = 3.5

SENTENCE_BOUNDARY = re.compile(r"(?<=[.;:])\s+")
CLAUSE_BOUNDARY = re.compile(r"(?<=,)\s+")

PREAMBLE_KEY = "preamble"

# a block with this many cell separators is a table rather than prose
TABLE_PIPES = 8
EMBED_BODY_CHARS = 600


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def _group_pieces(pieces: list[str], max_tokens: int) -> list[str]:
    grouped: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for piece in pieces:
        tokens = estimate_tokens(piece)
        if current and current_tokens + tokens > max_tokens:
            grouped.append(" ".join(current))
            current, current_tokens = [], 0
        current.append(piece)
        current_tokens += tokens
    if current:
        grouped.append(" ".join(current))
    return grouped


def _split_long_block(block: str, max_tokens: int) -> list[str]:
    """Break a single oversized paragraph on sentence boundaries; tables stay whole."""
    if estimate_tokens(block) <= max_tokens or block.lstrip().startswith("|"):
        return [block]

    pieces = _group_pieces(SENTENCE_BOUNDARY.split(block), max_tokens)
    if all(estimate_tokens(piece) <= HARD_MAX_TOKENS for piece in pieces):
        return pieces

    logger.debug("no sentence boundary in %s-token block, falling back to clause split",
                 estimate_tokens(block))
    return [
        part
        for piece in pieces
        for part in (
            _group_pieces(CLAUSE_BOUNDARY.split(piece), max_tokens)
            if estimate_tokens(piece) > HARD_MAX_TOKENS
            else [piece]
        )
    ]


def _split_blocks(blocks: list[str], max_tokens: int = MAX_TOKENS) -> list[list[str]]:
    """Group an article's paragraphs into parts that each stay under the token budget."""
    parts: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    expanded = [piece for block in blocks for piece in _split_long_block(block, max_tokens)]
    for block in expanded:
        tokens = estimate_tokens(block)
        if current and current_tokens + tokens > max_tokens:
            parts.append(current)
            current, current_tokens = [], 0
        current.append(block)
        current_tokens += tokens
    if current:
        parts.append(current)
    return parts or [[]]


def _embedding_body(text: str) -> str:
    """Tables are mostly digits and drown the heading they belong to.

    Several articles in the tax code are titled just "Soliq stavkalari"; what tells them
    apart is the chapter above them. With the whole rate table averaged into the vector
    that signal is lost, so only the opening of a table is embedded. The stored text is
    untouched — the answer still quotes the full table.
    """
    if text.count("|") < TABLE_PIPES:
        return text
    return text[:EMBED_BODY_CHARS]


def _build_heading(
    doc_title: str, article: Article, text: str, previous: Article | None
) -> str:
    """Document, section, chapter and article title — what says which article this is."""
    header = [doc_title]
    for level in (article.section, article.chapter):
        if level:
            header.append(level)
    header.append(article.heading)
    # a very short article carries little signal on its own, so the neighbouring
    # article's heading is added as context without touching the stored text
    if previous is not None and len(text) < SHORT_ARTICLE_CHARS and previous.heading:
        header.append(f"Oldingi modda: {previous.heading}")
    return "\n".join(header)


def _build_embedding_text(
    doc_title: str, article: Article, text: str, previous: Article | None
) -> str:
    return _build_heading(doc_title, article, text, previous) + "\n" + _embedding_body(text)


def _preamble_article(document: Document) -> Article:
    """Ratification and other short laws keep their whole normative text before the first
    article heading, so chunking articles alone drops the document from the index."""
    return Article(
        article_no=None,
        article_no_display=None,
        title=document.title,
        element_id=None,
        part=None,
        section=None,
        chapter=None,
        paragraph=None,
        blocks=list(document.preamble),
    )


def chunk_document(document: Document, meta: dict) -> list[dict]:
    doc_title = document.title or meta.get("title", "")
    base_url = meta.get("url") or f"https://lex.uz/uz/docs/{document.doc_id}"
    doc_okoz = document.okoz
    doc_tsz = document.tsz
    adopted_date = meta.get("adopted_date") or document.adopted_date

    articles = document.articles
    fallback_key: str | None = None
    if not any(article.text.strip() for article in articles) and document.preamble:
        articles = [_preamble_article(document)]
        fallback_key = PREAMBLE_KEY
        logger.info("%s: no articles, chunking the preamble instead", document.doc_id)

    chunks: list[dict] = []
    previous: Article | None = None
    for article in articles:
        if not article.text.strip():
            previous = article
            continue

        parts = _split_blocks(article.blocks)
        for index, blocks in enumerate(parts):
            text = "\n\n".join(block for block in blocks if block.strip())
            if not text.strip():
                continue
            article_key = article.article_no or fallback_key or f"x{len(chunks)}"
            source_url = f"{base_url}#{article.element_id}" if article.element_id else base_url
            chunks.append(
                {
                    "chunk_id": f"{document.doc_id}:{article_key}:{index}",
                    "doc_id": document.doc_id,
                    "doc_title": doc_title,
                    "doc_type": meta.get("form") or "",
                    "act_type": meta.get("act_type"),
                    "doc_number": meta.get("doc_number"),
                    "group": meta.get("group"),
                    "article_no": article.article_no,
                    "article_no_display": article.article_no_display,
                    "article_title": article.title,
                    "part": index,
                    "part_of": len(parts),
                    "section": article.section,
                    "chapter": article.chapter,
                    "paragraph": article.paragraph,
                    # articles without their own classifier inherit the document's
                    "okoz": article.okoz or doc_okoz,
                    "tsz": article.tsz or doc_tsz,
                    "adopted_date": adopted_date,
                    "effective_date": meta.get("effective_date") or document.effective_date,
                    "status": meta.get("status") or "Y",
                    # a repealed article is marked, never deleted, so "what did this say
                    # before?" stays answerable; retrieval filters on status by default
                    "version": meta.get("version", 1),
                    "valid_from": meta.get("effective_date") or adopted_date,
                    "valid_to": meta.get("valid_to"),
                    "superseded_by": None,
                    "source_url": source_url,
                    "script": document.script,
                    "text": text,
                    "text_for_embedding": _build_embedding_text(
                        doc_title, article, text, previous
                    ),
                    # keyword search weights the heading separately, so it is stored
                    # rather than reconstructed by pulling the embedding text apart
                    "heading": _build_heading(doc_title, article, text, previous),
                }
            )
        previous = article

    return chunks
