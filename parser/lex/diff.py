"""Compare two Markdown versions of a document and report which articles moved.

Re-embedding a whole code because one article was amended is the expensive mistake this
avoids: only the articles whose text actually changed need new vectors.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

ARTICLE_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
SUP_TO_DIGIT = {char: str(index) for index, char in enumerate(SUPERSCRIPT_DIGITS)}
ARTICLE_NO_RE = re.compile(rf"^(\d+)\s*([{SUPERSCRIPT_DIGITS}]*)\s*-\s*modda", re.IGNORECASE)

# a document that loses more than this share of its text is a parser failure far more
# often than a real repeal, so the pipeline stops instead of overwriting good data
MAX_SHRINK = 0.5


@dataclass
class ChangeSet:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    old_chars: int = 0
    new_chars: int = 0

    @property
    def touched(self) -> list[str]:
        """Articles that need new vectors: everything added or rewritten."""
        return sorted(set(self.added) | set(self.modified))

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.modified)

    @property
    def shrink(self) -> float:
        if not self.old_chars:
            return 0.0
        return max(0.0, (self.old_chars - self.new_chars) / self.old_chars)

    @property
    def suspicious(self) -> bool:
        return self.shrink > MAX_SHRINK


def frontmatter(markdown: str) -> dict[str, str]:
    match = FRONTMATTER_RE.search(markdown)
    if match is None:
        return {}
    values = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            values[key.strip()] = value.strip().strip('"')
    return values


def article_key(heading: str) -> str:
    """"125-modda. Nomi" -> "125", "24⁵-modda" -> "24-5", matching how chunk ids spell it."""
    match = ARTICLE_NO_RE.match(heading)
    if match is None:
        return heading.strip()
    base, sup = match.group(1), match.group(2)
    suffix = "".join(SUP_TO_DIGIT[char] for char in sup)
    return f"{base}-{suffix}" if suffix else base


def split_articles(markdown: str) -> dict[str, str]:
    """Map every article to its body, keyed the way chunk ids are."""
    sections: dict[str, str] = {}
    matches = list(ARTICLE_HEADING_RE.finditer(markdown))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        key = article_key(match.group(1))
        body = markdown[match.end() : end].strip()
        # a repeated key means extraction split one article in two; keeping the longer
        # body stays closer to the source than letting the second overwrite the first
        if key in sections and len(sections[key]) >= len(body):
            continue
        sections[key] = body
    return sections


def compare(old_markdown: str, new_markdown: str) -> ChangeSet:
    old = split_articles(old_markdown)
    new = split_articles(new_markdown)

    changes = ChangeSet(old_chars=len(old_markdown), new_chars=len(new_markdown))
    changes.added = sorted(set(new) - set(old))
    changes.removed = sorted(set(old) - set(new))
    changes.modified = sorted(key for key in set(old) & set(new) if old[key] != new[key])

    if changes.suspicious:
        logger.warning(
            "document shrank by %.0f%% (%s -> %s chars), extraction is suspect",
            changes.shrink * 100,
            changes.old_chars,
            changes.new_chars,
        )
    return changes
