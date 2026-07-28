import json
import re
from functools import lru_cache
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[3] / "data" / "registry.jsonl"

APOSTROPHES = str.maketrans({"ʻ": "'", "ʼ": "'", "‘": "'", "’": "'", "`": "'"})

# alias -> substring that identifies the document by title
ALIASES: dict[str, str] = {
    "fk": "fuqarolik kodeksi",
    "fuqarolik kodeksi": "fuqarolik kodeksi",
    "gk": "fuqarolik kodeksi",
    "fpk": "fuqarolik protsessual",
    # the procedural codes are named in full far more often than by abbreviation
    "fuqarolik protsessual": "fuqarolik protsessual",
    "jk": "jinoyat kodeksi",
    "jinoyat kodeksi": "jinoyat kodeksi",
    "uk": "jinoyat kodeksi",
    "jpk": "jinoyat-protsessual",
    "jinoyat-protsessual": "jinoyat-protsessual",
    "jik": "jinoyat-ijroiya",
    "jinoyat-ijroiya": "jinoyat-ijroiya",
    "sk": "soliq kodeksi",
    "soliq kodeksi": "soliq kodeksi",
    "nk": "soliq kodeksi",
    "mk": "mehnat kodeksi",
    "mehnat kodeksi": "mehnat kodeksi",
    "tk": "mehnat kodeksi",
    "ok": "oila kodeksi",
    "oila kodeksi": "oila kodeksi",
    "yk": "yer kodeksi",
    "yer kodeksi": "yer kodeksi",
    "ujk": "uy-joy kodeksi",
    "uy-joy kodeksi": "uy-joy kodeksi",
    "bk": "bojxona kodeksi",
    "bojxona kodeksi": "bojxona kodeksi",
    "buk": "budjet kodeksi",
    "budjet kodeksi": "budjet kodeksi",
    "ipk": "iqtisodiy protsessual",
    "iqtisodiy protsessual": "iqtisodiy protsessual",
    "mjk": "ma'muriy javobgarlik",
    # keys are looked up through normalize(), so they must use the plain apostrophe
    "ma'muriy javobgarlik kodeksi": "ma'muriy javobgarlik",
    "msiyk": "ma'muriy sud ishlarini yuritish",
    "ma'muriy sud ishlarini yuritish": "ma'muriy sud ishlarini yuritish",
    "shk": "shaharsozlik kodeksi",
    "suv kodeksi": "suv kodeksi",
    "havo kodeksi": "havo kodeksi",
    "saylov kodeksi": "saylov kodeksi",
    "konstitutsiya": "konstitutsiya",
}

_MARKER = "to'g'risida"
# "Notariat toʻgʻrisida" -> "notariat". Shorter cores are too common to filter on, and a
# prefix past 80 characters is never something a person types out.
CORE_RE = re.compile(rf"^([^“”\"]{{6,80}}?)\s+{re.escape(_MARKER)}")
BOILERPLATE_RE = re.compile(r"^o'zbekiston respublikasi(ning|da)?\s+")

# short aliases are ambiguous inside normal prose, so they must stand alone; the longer
# entries are distinctive phrases and are matched as plain substrings instead
SHORT_ALIAS_RE = {
    alias: re.compile(rf"(?<![\w'])({alias})(?:ning|da|dagi|ga|ni|si)?(?![\w'])", re.IGNORECASE)
    for alias in ALIASES
    if len(alias) <= 5
}


def normalize(text: str) -> str:
    return text.translate(APOSTROPHES).lower()


@lru_cache(maxsize=1)
def _registry() -> list[dict]:
    if not REGISTRY_PATH.exists():
        return []
    with REGISTRY_PATH.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def documents_for_alias(alias: str) -> list[str]:
    """Map an alias to the doc_ids whose title contains its canonical phrase."""
    needle = ALIASES.get(normalize(alias))
    if needle is None:
        return []
    return [
        record["doc_id"]
        for record in _registry()
        if needle in normalize(record.get("title", ""))
    ]


@lru_cache(maxsize=1)
def _title_cores() -> list[tuple[str, list[str]]]:
    """The naming part of every law title, paired with the documents that carry it.

    The alias table is written by hand and only ever covered the codes. With several
    hundred laws indexed, an article number alone is ambiguous — article 17 exists in
    dozens of them — so the document a question names has to come from the registry.

    A core maps to every document whose title contains it, not just the law it was cut
    from: a plenum ruling on a law names that law in its own title, and a question about
    how the courts apply a law must be able to reach both.
    """
    titles = [(normalize(record.get("title", "")), record["doc_id"]) for record in _registry()]
    cores: dict[str, None] = {}
    for title, _ in titles:
        match = CORE_RE.search(title)
        if match is None:
            continue
        core = BOILERPLATE_RE.sub("", match.group(1).strip(" ,.«»\"'"))
        if len(core) >= 6:
            cores.setdefault(core, None)
    return [
        (core, [doc_id for title, doc_id in titles if core in title]) for core in cores
    ]


def detect_documents(query: str) -> list[str]:
    """Return doc_ids the query names, either in full or by abbreviation."""
    text = normalize(query)
    matched: dict[str, None] = {}
    for alias, needle in ALIASES.items():
        pattern = SHORT_ALIAS_RE.get(alias)
        found = pattern.search(text) if pattern is not None else needle in text
        if found:
            for doc_id in documents_for_alias(alias):
                matched.setdefault(doc_id, None)
    # the marker has to be in the query too, otherwise a core like "sudlar" would fire
    # on any sentence that happens to mention courts
    if _MARKER in text:
        for core, doc_ids in _title_cores():
            if core in text:
                for doc_id in doc_ids:
                    matched.setdefault(doc_id, None)
    return list(matched)
