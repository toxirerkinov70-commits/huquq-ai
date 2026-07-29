"""Decide, in code, when the results are not about what was asked.

Retrieval always returns its best six chunks. When the corpus does not cover a concept
those six are a neighbouring concept that reads like an answer — a question about a bond
warehouse comes back with the customs warehouse article, which is a real norm, well
written, and not what was asked. Nothing in the text or the scores marks it as wrong, and
a prompt rule telling the model to notice did not change its behaviour.

The signal that does separate the two cases is vocabulary, in two forms:

A word whose stem appears in no chunk anywhere is proof the base cannot answer,
regardless of how the ranking looks.

A word the corpus does have but uses rarely is what the question is about. "Mikroqarz"
occurs in 273 chunks out of 22513; "hisob", "majbur" and "miqdor" occur in thousands
and match every article that mentions money. A long question carries a handful of the
first kind and dozens of the second, so results can rank well on the generic words
while containing none of the distinctive ones — which means the search drifted onto a
different subject. That is worth reporting even though every word exists somewhere.

Both verdicts are attached to the tool result, where the model reads them next to the
data they apply to.

The check stands down when the question names an article number or a document, because
the exact-match detectors in retrieval have already pinned the target and their tokens
("fkning") are not corpus words.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

from . import aliases
from .query import detect_article_no
from .sparse import tokenize

logger = logging.getLogger(__name__)

VOCAB_PATH = Path(__file__).resolve().parents[3] / "data" / "corpus_vocab.json"

# below four characters the token is an abbreviation or a fragment, not a concept
MIN_TERM_LENGTH = 4
# how much of a word has to match to count as the same stem
STEM_LENGTH = 5
# A five-character stem is short enough that an ordinary word can miss it and still be
# a word the corpus knows: "qo'yyabdi" is how people say "qo'yayapti", and no article
# is written that way, while "qo'y-" runs through the whole of legislation in 4933
# chunks. So a missing stem is confirmed at four characters, where a word the corpus
# genuinely does not have stays near zero — "mars" reaches 5 chunks and only through
# "marshrut", "bond" reaches none.
CONFIRM_LENGTH = 4
CONFIRM_DF_RATIO = 0.001
# a stem in more than this share of the corpus is a word the language needs, not a
# word the question is about
RARE_DF_RATIO = 0.02
# more than this and the "distinctive" terms are just a long sentence
MAX_RARE_TERMS = 4

MISSING_ADVICE = (
    "Ichki bazada {terms} so'zi umuman uchramaydi, ya'ni natijalar savolda so'ralgan "
    "tushuncha haqida emas, unga yaqin boshqa tushuncha haqida. Bu natijalarni javob "
    "o'rniga qo'yish xato. `search_lex_live` ni shu atama bilan chaqir."
)
OFF_TOPIC_ADVICE = (
    "Yuqoridagi natijalarning hech birida savolning asosiy atamasi ({terms}) uchramaydi. "
    "Baza bu atamani biladi, lekin qidiruv boshqa mavzuga og'ib ketgan. Avval "
    "`search_legal_base` ni faqat shu atama bilan qayta chaqir; u ham natija bermasa, "
    "javobni shu natijalar asosida yozma."
)


@lru_cache(maxsize=1)
def _vocab() -> dict:
    """How many chunks each stem occurs in, by prefix length, and the size of the corpus."""
    if not VOCAB_PATH.exists():
        logger.warning("%s not found, coverage check disabled", VOCAB_PATH.name)
        return {}
    try:
        raw = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("could not read corpus vocabulary: %s", exc)
        return {}

    frequencies = raw.get("df")
    if not isinstance(frequencies, dict) or str(STEM_LENGTH) not in frequencies:
        logger.warning("%s is in an older format, rerun build_vocab.py", VOCAB_PATH.name)
        return {}

    return {
        "df": {int(length): counts for length, counts in frequencies.items()},
        "chunks": int(raw.get("chunks") or 0),
    }


def _content_tokens(query: str) -> list[str]:
    # a token opening with a digit is a date or an article number, already handled
    return [
        token
        for token in tokenize(query)
        if len(token) >= MIN_TERM_LENGTH and token[:1].isalpha()
    ]


def _frequency(token: str, length: int) -> int:
    counts = _vocab().get("df", {}).get(length) or {}
    return counts.get(token[:length], 0)


def unknown_terms(query: str) -> list[str]:
    """Content words of the query the corpus does not have, confirmed at both prefixes."""
    vocab = _vocab()
    if not vocab:
        return []
    floor = vocab["chunks"] * CONFIRM_DF_RATIO

    missing: list[str] = []
    for token in _content_tokens(query):
        if token in missing:
            continue
        if _frequency(token, STEM_LENGTH) == 0 and _frequency(token, CONFIRM_LENGTH) <= floor:
            missing.append(token)
    return missing


def rare_terms(query: str) -> list[str]:
    """The query's distinctive words: present in the corpus, but not everywhere in it.

    Rarest first, so a caller that searches them alone leads with the term that
    identifies the subject.
    """
    vocab = _vocab()
    if not vocab or not vocab["chunks"]:
        return []

    cap = vocab["chunks"] * RARE_DF_RATIO
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for token in _content_tokens(query):
        stem = token[:STEM_LENGTH]
        if stem in seen:
            continue
        seen.add(stem)
        frequency = _frequency(token, STEM_LENGTH)
        if 0 < frequency <= cap:
            scored.append((frequency, token))
    scored.sort()
    return [token for _, token in scored[:MAX_RARE_TERMS]]


def terms_missing_from(terms: list[str], payloads: list[dict]) -> list[str]:
    """Which of these terms no result contains, matched by stem so suffixes do not count."""
    if not terms or not payloads:
        return list(terms)
    found: set[str] = set()
    for payload in payloads:
        for field in ("text", "article_title", "doc_title"):
            value = payload.get(field)
            if value:
                found.update(token[:STEM_LENGTH] for token in tokenize(value))
    return [term for term in terms if term[:STEM_LENGTH] not in found]


def assess(query: str, payloads: list[dict] | None = None) -> dict | None:
    """The verdict to attach to a search result, or None when the results look usable.

    Pass the payloads that were returned to get the second check as well; without them
    only the absent-word check runs.
    """
    if detect_article_no(query) or aliases.detect_documents(query):
        return None

    missing = unknown_terms(query)
    if missing:
        logger.info("corpus has no stem for %s, steering to live search", missing)
        return {
            "coverage": "weak",
            "missing_terms": missing,
            "advice": MISSING_ADVICE.format(terms=", ".join(f"'{term}'" for term in missing)),
        }

    if payloads is None:
        return None

    distinctive = rare_terms(query)
    absent = terms_missing_from(distinctive, payloads)
    if distinctive and len(absent) == len(distinctive):
        logger.info("results contain none of %s, flagging as off-topic", distinctive)
        return {
            "coverage": "off_topic",
            "missing_terms": distinctive,
            "advice": OFF_TOPIC_ADVICE.format(terms=", ".join(f"'{term}'" for term in distinctive)),
        }
    return None
