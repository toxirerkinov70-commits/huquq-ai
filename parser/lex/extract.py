import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from selectolax.parser import HTMLParser, Node

logger = logging.getLogger(__name__)

SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
SUP_TO_DIGIT = {char: str(index) for index, char in enumerate(SUPERSCRIPT_DIGITS)}
SUP_RE = re.compile(r"<sup>\s*(\d+)\s*</sup>", re.IGNORECASE)

# lex.uz uses several apostrophe glyphs interchangeably in oʻ/gʻ
APOS = r"['ʻʼ‘’`]"

# some headings render as "24⁵-modda", others as "24 ⁵ -modda", so spacing is optional
ARTICLE_RE = re.compile(
    rf"^(\d+)\s*([{SUPERSCRIPT_DIGITS}]*)\s*-?\s*modda\.?\s*(.*)$", re.IGNORECASE | re.DOTALL
)
SECTION_RE = re.compile(rf"BO{APOS}?LIM", re.IGNORECASE)
PART_RE = re.compile(r"\bQISM\b", re.IGNORECASE)
CHAPTER_RE = re.compile(rf"(\d+[{SUPERSCRIPT_DIGITS}]*\s*-\s*bob|^[IVXLC]+\s*-?\s*bob)", re.IGNORECASE)

# toolbar labels injected next to every element by the lex.uz reader UI
TOOLBAR_LABELS = (
    "Hujjatga taklif yuborish",
    "Audioni tinglash",
    "Hujjat elementidan havola olish",
)

BODY_SELECTOR = "#divCont"
SKIP_CLASSES = {"COMMENT", "COMMENTLEXUZ", "INDEXES_ON_REF"}

CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
LATIN_RE = re.compile(r"[A-Za-z]")

# the page title starts with the adoption date, the header carries the effective date
TITLE_DATE_RE = re.compile(r"^\s*(\d{2})\.(\d{2})\.(\d{4})\s*\.")
DATE_ONLY_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
EFFECTIVE_LABEL = "Kuchga kirish sanasi"

CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "ʼ", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "oʻ", "қ": "q", "ғ": "gʻ", "ҳ": "h",
}


@dataclass
class Article:
    article_no: str | None
    article_no_display: str | None
    title: str
    element_id: str | None
    part: str | None
    section: str | None
    chapter: str | None
    paragraph: str | None
    okoz: list[str] = field(default_factory=list)
    tsz: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(block for block in self.blocks if block.strip())

    @property
    def heading(self) -> str:
        if self.article_no_display is None:
            return self.title
        return f"{self.article_no_display}-modda." + (f" {self.title}" if self.title else "")


@dataclass
class Document:
    doc_id: str
    title: str
    publication: str | None
    script: str
    preamble: list[str]
    articles: list[Article]
    adopted_date: str | None = None
    effective_date: str | None = None

    def _union(self, attribute: str) -> list[str]:
        seen: dict[str, None] = {}
        for article in self.articles:
            for value in getattr(article, attribute):
                seen.setdefault(value, None)
        return list(seen)

    @property
    def okoz(self) -> list[str]:
        return self._union("okoz")

    @property
    def tsz(self) -> list[str]:
        return self._union("tsz")

    @property
    def okoz_categories(self) -> list[str]:
        """Top level of each OKOZ path, which is what agent-mode filtering needs."""
        seen: dict[str, None] = {}
        for value in self.okoz:
            seen.setdefault(value.split(" / ")[0].strip(), None)
        return list(seen)

    def content_hash(self) -> str:
        payload = "\n".join(article.heading + "\n" + article.text for article in self.articles)
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def preprocess(html: str) -> str:
    """Turn <sup>2</sup> into ² so article numbering survives plain-text extraction."""
    return SUP_RE.sub(lambda m: "".join(SUPERSCRIPT_DIGITS[int(d)] for d in m.group(1)), html)


def detect_script(text: str) -> str:
    cyrillic = len(CYRILLIC_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    return "cyrillic" if cyrillic > latin else "latin"


def transliterate(text: str) -> str:
    out = []
    for char in text:
        lower = char.lower()
        mapped = CYRILLIC_TO_LATIN.get(lower)
        if mapped is None:
            out.append(char)
        elif char.isupper():
            out.append(mapped.capitalize() if len(mapped) > 1 else mapped.upper())
        else:
            out.append(mapped)
    return "".join(out)


def _clean_text(node: Node) -> str:
    text = node.text(separator=" ", strip=True)
    for label in TOOLBAR_LABELS:
        text = text.replace(label, " ")
    text = unicodedata.normalize("NFC", text)
    return " ".join(text.split())


def _node_classes(node: Node) -> set[str]:
    return set((node.attributes.get("class") or "").split())


def _table_to_markdown(table: Node) -> str:
    rows: list[list[str]] = []
    for tr in table.css("tr"):
        cells = [_clean_text(cell).replace("|", "\\|") for cell in tr.css("td,th")]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header, *body = rows
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)


def _has_table_ancestor(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.tag == "table":
            return True
        parent = parent.parent
    return False


def _classifier_values(node: Node) -> tuple[str, list[str]]:
    """lex.uz emits two taxonomies in the same block shape, labelled OKOZ or TSZ."""
    label_node = node.css_first("b")
    label = _clean_text(label_node).rstrip(":").upper() if label_node is not None else "OKOZ"
    values = []
    for span in node.css("span.iorVal"):
        value = _clean_text(span).rstrip("]").strip()
        if value:
            values.append(value)
    return label, values


def _parse_article_heading(text: str) -> tuple[str, str, str] | None:
    match = ARTICLE_RE.match(text)
    if match is None:
        return None
    base, sup, title = match.groups()
    suffix = "".join(SUP_TO_DIGIT[char] for char in sup)
    article_no = f"{base}-{suffix}" if suffix else base
    display = f"{base}{sup}" if sup else base
    return article_no, display, title.strip()


def extract_document(doc_id: str, html: str) -> Document:
    tree = HTMLParser(preprocess(html))
    body = tree.css_first(BODY_SELECTOR)
    if body is None:
        raise ValueError(f"{doc_id}: no {BODY_SELECTOR} container in page")

    # the reader toolbar sits in a wrapper next to every element's text
    for wrapper in body.css("div.lx_elem2"):
        wrapper.decompose()

    title = ""
    publication = None
    preamble: list[str] = []
    articles: list[Article] = []
    current: Article | None = None
    state = {"part": None, "section": None, "chapter": None, "paragraph": None}
    pending: dict[str, list[str]] = {"OKOZ": [], "TSZ": []}

    for node in body.iter(include_text=False):
        classes = _node_classes(node)

        if classes & SKIP_CLASSES:
            if "INDEXES_ON_REF" in classes:
                label, values = _classifier_values(node)
                pending.setdefault(label, []).extend(values)
            continue

        text = _clean_text(node)

        if "ACT_TITLE" in classes:
            title = text
            continue
        if "NEW_EDITION" in classes:
            title = f"{title} {text}".strip()
            continue
        if "PUBLICATION_ORIGIN" in classes:
            publication = text
            continue

        if "TEXT_HEADER_DEFAULT" in classes:
            if not text:
                continue
            if "§" in text:
                state["paragraph"] = text
            elif CHAPTER_RE.search(text):
                state["chapter"] = text
                state["paragraph"] = None
            elif SECTION_RE.search(text):
                state["section"] = text
                state["chapter"] = state["paragraph"] = None
            elif PART_RE.search(text):
                state["part"] = text
                state["section"] = state["chapter"] = state["paragraph"] = None
            else:
                state["section"] = text
                state["chapter"] = state["paragraph"] = None
            continue

        if "CLAUSE_DEFAULT" in classes:
            # amended documents leave behind empty heading elements; starting a new
            # article there would produce a chunk with no article number
            if not text:
                continue
            if current is not None:
                articles.append(current)
            parsed = _parse_article_heading(text)
            inner = node.css_first("div[name]")
            element_id = inner.attributes.get("name") if inner is not None else None
            if parsed is None:
                logger.debug("%s: unparsed clause heading %r", doc_id, text[:80])
                article_no = display = None
                heading_title = text
            else:
                article_no, display, heading_title = parsed
            current = Article(
                article_no=article_no,
                article_no_display=display,
                title=heading_title,
                element_id=element_id,
                part=state["part"],
                section=state["section"],
                chapter=state["chapter"],
                paragraph=state["paragraph"],
                okoz=list(dict.fromkeys(pending["OKOZ"])),
                tsz=list(dict.fromkeys(pending["TSZ"])),
            )
            pending = {"OKOZ": [], "TSZ": []}
            continue

        if "CHANGES_ORIGINS" in classes:
            if text and current is not None:
                current.changes.append(text)
            continue

        target = current.blocks if current is not None else preamble
        tables = [t for t in node.css("table") if not _has_table_ancestor(t)]
        if tables:
            for table in tables:
                markdown = _table_to_markdown(table)
                if markdown:
                    target.append(markdown)
            continue

        if text:
            target.append(text)
            if current is not None and (pending["OKOZ"] or pending["TSZ"]):
                current.okoz = list(dict.fromkeys(current.okoz + pending["OKOZ"]))
                current.tsz = list(dict.fromkeys(current.tsz + pending["TSZ"]))
                pending = {"OKOZ": [], "TSZ": []}

    if current is not None:
        articles.append(current)

    full_text = "\n".join(article.text for article in articles[:20])
    return Document(
        doc_id=doc_id,
        title=title,
        publication=publication,
        script=detect_script(full_text or title),
        preamble=preamble,
        articles=articles,
        adopted_date=_parse_title_date(tree),
        effective_date=_parse_effective_date(tree),
    )


def _iso_date(day: str, month: str, year: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def _parse_title_date(tree: HTMLParser) -> str | None:
    node = tree.css_first("title")
    if node is None:
        return None
    match = TITLE_DATE_RE.match(node.text(strip=True))
    return _iso_date(*match.groups()) if match is not None else None


def _parse_effective_date(tree: HTMLParser) -> str | None:
    """The header renders the label and its value in sibling divs."""
    for label in tree.css("div.docHeader__item-label"):
        if EFFECTIVE_LABEL not in label.text(strip=True):
            continue
        parent = label.parent
        if parent is None:
            continue
        match = DATE_ONLY_RE.search(parent.text(separator=" ", strip=True))
        if match is not None:
            return _iso_date(*match.groups())
    return None


def to_markdown(document: Document, meta: dict) -> str:
    front = {
        "doc_id": document.doc_id,
        "doc_title": document.title or meta.get("title", ""),
        "doc_type": meta.get("form") or "",
        "act_type": meta.get("act_type"),
        "doc_number": meta.get("doc_number") or "",
        "adopted_date": meta.get("adopted_date") or document.adopted_date or "",
        "effective_date": meta.get("effective_date") or document.effective_date or "",
        "status": meta.get("status") or "",
        # full OKOZ paths live on each chunk; the frontmatter keeps the readable roots
        "okoz": document.okoz_categories,
        "tsz": document.tsz,
        "source_url": meta.get("url", f"https://lex.uz/uz/docs/{document.doc_id}"),
        "script": document.script,
        "articles": len(document.articles),
        "content_hash": document.content_hash(),
        "fetched_at": meta.get("fetched_at", ""),
    }

    lines = ["---"]
    for key, value in front.items():
        if isinstance(value, list):
            rendered = "[" + ", ".join(f'"{item}"' for item in value) + "]"
        elif isinstance(value, int) or value is None:
            rendered = str(value)
        else:
            rendered = '"' + str(value).replace('"', "'") + '"'
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    lines.append("")

    if document.preamble:
        lines.extend(["\n\n".join(document.preamble), ""])

    seen = {"part": None, "section": None, "chapter": None, "paragraph": None}
    for article in document.articles:
        for level, marker in (("part", "#"), ("section", "#"), ("chapter", "##"), ("paragraph", "##")):
            value = getattr(article, level)
            if value and value != seen[level]:
                lines.extend([f"{marker} {value}", ""])
                seen[level] = value
        lines.extend([f"### {article.heading}", ""])
        if article.text:
            lines.extend([article.text, ""])
        for change in article.changes:
            lines.extend([f"*{change}*", ""])

    return "\n".join(lines).rstrip() + "\n"
