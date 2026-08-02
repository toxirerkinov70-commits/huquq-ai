"""The guards that stop an ungrounded answer from being dressed up with sources."""

from backend.app.services.generate import (
    NOT_FOUND,
    answer_is_grounded,
    filter_cited_sources,
    is_conversational,
)


def test_not_found_answer_is_not_grounded():
    assert answer_is_grounded(f"{NOT_FOUND}.") is False


def test_cited_article_keeps_the_answer_grounded():
    answer = f"{NOT_FOUND} bo'yicha to'liq ma'lumot yo'q, lekin 173-modda buni qamrab oladi."
    assert answer_is_grounded(answer) is True


def test_plain_answer_is_grounded():
    assert answer_is_grounded("Fuqarolik kodeksi, 173-modda bo'yicha ...") is True


def test_only_cited_sources_survive():
    sources = [
        {"doc_title": "Fuqarolik kodeksi", "article_no": "173"},
        {"doc_title": "Fuqarolik kodeksi", "article_no": "999"},
    ]
    kept = filter_cited_sources("Javob: 173-modda bo'yicha ...", sources)
    assert [item["article_no"] for item in kept] == ["173"]


def test_superscript_citation_matches_its_source():
    sources = [{"doc_title": "Jinoyat kodeksi", "article_no": "173-2"}]
    assert filter_cited_sources("173²-modda bo'yicha ...", sources) == sources


def test_uncited_answer_keeps_every_source():
    sources = [{"doc_title": "Mehnat kodeksi", "article_no": "174"}]
    assert filter_cited_sources("Umumiy tushuntirish, modda raqamisiz.", sources) == sources


def test_greetings_skip_retrieval():
    assert is_conversational("Salom") is True
    assert is_conversational("Nima qila olasan?") is True


def test_legal_questions_are_not_conversational():
    assert is_conversational("Mehnat shartnomasi qanday bekor qilinadi?") is False
