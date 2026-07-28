"""Decide, in code, when the base has nothing on what was asked.

Retrieval always returns its best six chunks. When the corpus does not cover a concept
those six are a neighbouring concept that reads like an answer — a question about a bond
warehouse comes back with the customs warehouse article, which is a real norm, well
written, and not what was asked. Nothing in the text or the scores marks it as wrong, and
a prompt rule telling the model to notice did not change its behaviour.

The signal that does separate the two cases is vocabulary: a content word whose stem
appears in no chunk anywhere is proof the base cannot answer, regardless of how the
ranking looks. That verdict is attached to the tool result, where the model reads it
next to the data it applies to.

The check stands down when the question names an article number or a document, because
the exact-match detectors in retrieval have already pinned the target and their tokens
("fkning") are not corpus words.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

from . import aliases
from .retrieval import detect_article_no
from .sparse import tokenize

logger = logging.getLogger(__name__)

VOCAB_PATH = Path(__file__).resolve().parents[3] / "data" / "corpus_vocab.json"

# below four characters the token is an abbreviation or a fragment, not a concept
MIN_TERM_LENGTH = 4
# how much of a word has to match to count as the same stem
STEM_LENGTH = 5

ADVICE = (
    "Ichki bazada {terms} so'zi umuman uchramaydi, ya'ni natijalar savolda so'ralgan "
    "tushuncha haqida emas, unga yaqin boshqa tushuncha haqida. Bu natijalarni javob "
    "o'rniga qo'yish xato. `search_lex_live` ni shu atama bilan chaqir."
)


@lru_cache(maxsize=1)
def _vocab() -> dict[int, set[str]]:
    """Stems the corpus contains, keyed by stem length."""
    if not VOCAB_PATH.exists():
        logger.warning("%s not found, coverage check disabled", VOCAB_PATH.name)
        return {}
    try:
        raw = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("could not read corpus vocabulary: %s", exc)
        return {}
    return {int(length): set(stems) for length, stems in raw.items()}


def unknown_terms(query: str) -> list[str]:
    """Content words of the query whose stem occurs nowhere in the corpus."""
    vocab = _vocab()
    if not vocab:
        return []

    missing: list[str] = []
    for token in tokenize(query):
        # a token opening with a digit is a date or an article number, already handled
        if len(token) < MIN_TERM_LENGTH or not token[:1].isalpha():
            continue
        length = min(len(token), STEM_LENGTH)
        stems = vocab.get(length)
        if stems is None or token[:length] in stems:
            continue
        if token not in missing:
            missing.append(token)
    return missing


def assess(query: str) -> dict | None:
    """The verdict to attach to a search result, or None when the base looks able to answer."""
    if detect_article_no(query) or aliases.detect_documents(query):
        return None

    missing = unknown_terms(query)
    if not missing:
        return None

    logger.info("corpus has no stem for %s, steering to live search", missing)
    return {
        "coverage": "weak",
        "missing_terms": missing,
        "advice": ADVICE.format(terms=", ".join(f"'{term}'" for term in missing)),
    }
