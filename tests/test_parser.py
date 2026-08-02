"""Sparse tokenisation and the diff that decides what gets re-embedded."""

from backend.app.services.sparse import tokenize
from parser.lex.diff import article_key, compare, frontmatter, split_articles

OLD = """---
doc_id: "111181"
content_hash: "sha256:aaa"
---

### 1-modda. Birinchi

Birinchi moddaning matni.

### 2-modda. Ikkinchi

Ikkinchi moddaning matni.
"""

NEW = """---
doc_id: "111181"
content_hash: "sha256:bbb"
---

### 1-modda. Birinchi

Birinchi moddaning matni.

### 2-modda. Ikkinchi

Ikkinchi moddaning YANGI matni.

### 3-modda. Uchinchi

Uchinchi moddaning matni.
"""


def test_frontmatter_is_read():
    assert frontmatter(OLD)["content_hash"] == "sha256:aaa"
    assert frontmatter("matn, frontmatter yo'q") == {}


def test_article_key_normalises_superscripts():
    assert article_key("125-modda. Nomi") == "125"
    assert article_key("24⁵-modda. Nomi") == "24-5"


def test_split_articles_keeps_every_heading():
    assert set(split_articles(NEW)) == {"1", "2", "3"}


def test_compare_touches_only_what_changed():
    changes = compare(OLD, NEW)
    assert changes.added == ["3"]
    assert changes.modified == ["2"]
    assert changes.removed == []
    # article 1 is untouched, so it must not be re-embedded
    assert changes.touched == ["2", "3"]
    assert changes.empty is False


def test_identical_documents_produce_no_work():
    assert compare(OLD, OLD).empty is True


def test_a_collapsed_document_is_flagged_rather_than_applied():
    truncated = OLD[: len(OLD) // 4]
    changes = compare(OLD, truncated)
    assert changes.suspicious is True


def test_tokenizer_drops_stopwords_and_first_person():
    tokens = tokenize("Men bu shartnoma bo'yicha savol bermoqchiman")
    assert "men" not in tokens
    assert "bu" not in tokens
    assert "shartnoma" in tokens


def test_tokenizer_folds_apostrophe_variants():
    assert tokenize("oʻzbek") == tokenize("o'zbek")
