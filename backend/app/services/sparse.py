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

TOKEN_RE = re.compile(r"[\w'ʻʼ‘’-]+", re.UNICODE)
# lex.uz mixes apostrophe glyphs, so oʻzbek and o'zbek must collapse to one token
APOSTROPHES = str.maketrans({"ʻ": "'", "ʼ": "'", "‘": "'", "’": "'", "`": "'"})

STOPWORDS = {
    "va", "bilan", "uchun", "ushbu", "bu", "shu", "yoki", "ham", "agar", "lekin",
    "hamda", "yoxud", "hisoblanadi", "boʻyicha", "bo'yicha", "kerak", "mumkin",
    "quyidagi", "quyidagilar", "hollarda", "tomonidan", "asosida", "doir",
    # question words carry no signal but match many articles
    "qaysi", "qanday", "qancha", "nima", "necha", "nechta", "kim", "qayerda",
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
