"""Reading the question itself, before anything is searched.

Kept apart from retrieval so the coverage check can use it without the two modules
importing each other.
"""

import re

SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹"

# "125-modda", "125 moddasi", "FKning 125-moddasi", "173²-modda", "173-2-modda"
ARTICLE_RE = re.compile(
    rf"(\d+)(?:\s*[-–]\s*(\d)|([{SUPERSCRIPTS}]))?\s*[-–]?\s*modda", re.IGNORECASE
)


# Someone describing their own case writes in the first person and in the past:
# "men mikroqarz olganman", "menga jarima qo'yishdi", "ishdan bo'shatishdi". A question
# about what a norm says has neither, and it does not need the mitigation or limitation
# articles that a described situation does.
SITUATION_RE = re.compile(
    r"\b(men|mening|menga|meni|mendan|menda|manga|biz|bizni|bizga|bizning)\b"
    r"|\w+(dim|dik|ganman|ganmiz|yapman|moqchiman|ishdi|shdi)\b",
    re.IGNORECASE,
)


CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")


def is_situation(query: str) -> bool:
    """Whether the user is describing what happened to them rather than asking what a rule says."""
    return bool(SITUATION_RE.search(query))


def looks_russian(query: str) -> bool:
    """A Cyrillic question cannot reach a Latin-script corpus through the sparse side.

    The index holds the Uzbek Latin text of every act, so BM25 scores a Russian question
    at zero on every chunk and half the hybrid disappears. Detecting it lets the pipeline
    put an Uzbek rendering of the question next to the original before searching.
    """
    letters = [char for char in query if char.isalpha()]
    if not letters:
        return False
    cyrillic = sum(1 for char in letters if CYRILLIC_RE.match(char))
    return cyrillic / len(letters) > 0.3


def detect_article_no(query: str) -> str | None:
    match = ARTICLE_RE.search(query)
    if match is None:
        return None
    base, dashed, superscript = match.groups()
    if dashed:
        return f"{base}-{dashed}"
    if superscript:
        return f"{base}-{SUPERSCRIPTS.index(superscript)}"
    return base
