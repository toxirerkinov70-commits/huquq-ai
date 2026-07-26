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
    "jk": "jinoyat kodeksi",
    "jinoyat kodeksi": "jinoyat kodeksi",
    "uk": "jinoyat kodeksi",
    "jpk": "jinoyat-protsessual",
    "jik": "jinoyat-ijroiya",
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
    "mjk": "ma'muriy javobgarlik",
    "maʼmuriy javobgarlik kodeksi": "ma'muriy javobgarlik",
    "shk": "shaharsozlik kodeksi",
    "suv kodeksi": "suv kodeksi",
    "havo kodeksi": "havo kodeksi",
    "saylov kodeksi": "saylov kodeksi",
    "konstitutsiya": "konstitutsiya",
}

# short aliases are ambiguous inside normal prose, so they must stand alone
SHORT_ALIAS_RE = {
    alias: re.compile(rf"(?<![\w'])({alias})(?:ning|da|dagi|ga|ni|si)?(?![\w'])", re.IGNORECASE)
    for alias in ALIASES
    if len(alias) <= 4
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
    return list(matched)
