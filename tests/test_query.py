"""The question-reading helpers: they decide which search path a question takes."""

import pytest

from backend.app.services.query import detect_article_no, is_situation, looks_russian


@pytest.mark.parametrize(
    "question,expected",
    [
        ("125-modda nima haqida?", "125"),
        ("FKning 125 moddasi", "125"),
        ("173²-modda", "173-2"),
        ("173-2-modda farqi", "173-2"),
        ("289¹-modda", "289-1"),
        ("Meros haqida nima deyilgan?", None),
        ("2024-yilda nima o'zgardi?", None),
    ],
)
def test_detect_article_no(question, expected):
    assert detect_article_no(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "Meni ishdan haydashdi, nima qilishim kerak?",
        "men mikroqarz olganman",
        "bizga jarima qo'yishdi",
    ],
)
def test_situations_are_detected(question):
    assert is_situation(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "Mehnat shartnomasi qanday bekor qilinadi?",
        "Fuqarolik kodeksining 173-moddasi",
    ],
)
def test_plain_questions_are_not_situations(question):
    assert is_situation(question) is False


@pytest.mark.parametrize(
    "question,russian",
    [
        ("Как расторгнуть трудовой договор?", True),
        ("Что говорит статья 173?", True),
        ("Mehnat shartnomasi qanday bekor qilinadi?", False),
        ("173-modda", False),
        ("", False),
    ],
)
def test_looks_russian(question, russian):
    assert looks_russian(question) is russian
