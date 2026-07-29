import hashlib
import re
from collections import Counter

# Qdrant applies the IDF part of BM25 itself when the sparse vector is declared with
# Modifier.IDF, so only the term-frequency part is computed here.
K1 = 1.2
B = 0.75
AVG_DOC_LEN = 180

# Uzbek is agglutinative: a query says "poytaxt" while the text says "poytaxti", so
# exact token matching alone finds nothing. Character n-grams bridge the suffixes.
NGRAM_SIZE = 4
NGRAM_WEIGHT = 0.35

# how many times a chunk's heading is repeated before its body when indexing
HEADING_REPEAT = 3
# a heading line longer than this is a sentence, not a title. Court rulings carry their
# whole thesis in the title field ("Bankning aybi bilan ... penya undiriladi"), so
# repeating it for weight hands them a keyword match on half the words of any question
# about payments. Such a line is indexed once.
MAX_REPEATED_HEADING = 160

TOKEN_RE = re.compile(r"[\w'ʻʼ‘’-]+", re.UNICODE)
# lex.uz mixes apostrophe glyphs, so oʻzbek and o'zbek must collapse to one token
APOSTROPHES = str.maketrans({"ʻ": "'", "ʼ": "'", "‘": "'", "’": "'", "`": "'"})

STOPWORDS = {
    "va", "bilan", "uchun", "ushbu", "bu", "shu", "yoki", "ham", "agar", "lekin",
    "hamda", "yoxud", "hisoblanadi", "boʻyicha", "bo'yicha", "kerak", "mumkin",
    "quyidagi", "quyidagilar", "hollarda", "tomonidan", "asosida", "doir",
    # question words carry no signal but match many articles
    "qaysi", "qanday", "qancha", "nima", "necha", "nechta", "kim", "qayerda",
    # someone describing their own case writes in the first person, which legislation
    # never does: these match nothing and, worse, look like words the corpus lacks
    "men", "mening", "menga", "meni", "mendan", "menda", "manga",
    "biz", "bizning", "bizga", "bizni", "bizdan", "bizda",
    "sen", "sening", "senga", "seni", "siz", "sizning", "sizga", "sizni",
    "uning", "unga", "uni", "undan", "unda", "ular", "ularning", "ularga",
}


def tokenize(text: str) -> list[str]:
    normalized = text.translate(APOSTROPHES).lower()
    return [
        token
        for token in TOKEN_RE.findall(normalized)
        if len(token) > 2 and token not in STOPWORDS
    ]


def token_id(token: str) -> int:
    """Stable 32-bit id so the same term maps to the same index across runs."""
    return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest(), "big")


def expand(tokens: list[str]) -> Counter:
    """Whole words carry full weight; their n-grams carry a fraction of it."""
    weighted: Counter = Counter()
    for token in tokens:
        weighted[token_id(token)] += 1.0
        if len(token) > NGRAM_SIZE:
            for start in range(len(token) - NGRAM_SIZE + 1):
                gram = token[start : start + NGRAM_SIZE]
                weighted[token_id("#" + gram)] += NGRAM_WEIGHT
    return weighted


def document_text(heading: str, body: str) -> str:
    """What keyword search indexes for a chunk.

    Several tax-code articles are titled exactly "Soliq stavkalari" and only the section
    above them says which tax it is. That line appears once while the rate table under it
    runs to hundreds of tokens, so BM25 length normalisation buries the one phrase that
    identifies the article. Repeating the heading restores its weight.

    The body is the full text, not the shortened form the dense vector gets: a table
    drags an averaged vector around, but it costs keyword matching nothing.

    Only short lines are repeated, and a line is never counted twice: court rulings
    have no article title of their own, so the extractor fills it with the document
    title and the same sentence arrives here twice before repetition even begins.
    """
    if not heading:
        return body
    lines: list[str] = []
    for line in heading.splitlines():
        line = line.strip()
        if line and line not in lines:
            lines.append(line)

    weighted: list[str] = []
    for line in lines:
        repeat = HEADING_REPEAT if len(line) <= MAX_REPEATED_HEADING else 1
        weighted.extend([line] * repeat)
    return "\n".join(weighted + [body])


def encode_document(text: str) -> tuple[list[int], list[float]]:
    tokens = tokenize(text)
    if not tokens:
        return [], []
    weighted = expand(tokens)
    length_norm = K1 * (1 - B + B * len(tokens) / AVG_DOC_LEN)
    indices, values = [], []
    for index, weight in weighted.items():
        indices.append(index)
        values.append(weight * (K1 + 1) / (weight + length_norm))
    return indices, values


def encode_query(text: str) -> tuple[list[int], list[float]]:
    tokens = tokenize(text)
    if not tokens:
        return [], []
    weighted = expand(tokens)
    return list(weighted), list(weighted.values())
