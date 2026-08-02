"""Routing a message to the right kind of answer.

The failure this guards against is the one that was reported: "menga qanday yordam bera
olasan" answered with articles of the Labour Code. The patterns below settle the obvious
cases for free; everything else goes to the model, and a model that fails is treated as
a legal question, because answering a real legal question with small talk is worse.
"""

import pytest

from backend.app.services import intent


class FakeLLM:
    """Records what it was asked and returns whatever the test wants."""

    def __init__(self, reply: str | Exception = '{"toifa": "huquqiy", "sabab": "test"}'):
        self.reply = reply
        self.calls = 0

    async def generate(self, prompt, **kwargs):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.mark.parametrize(
    "message, expected",
    [
        ("salom", intent.CONVERSATION),
        ("Assalomu alaykum!", intent.CONVERSATION),
        ("rahmat", intent.CONVERSATION),
        ("mening tarifim qanday", intent.ACCOUNT),
        ("nechta savol qoldi", intent.ACCOUNT),
        ("FK 125-modda nima deydi", intent.LEGAL),
        ("mehnat kodeksi bo'yicha savolim bor", intent.LEGAL),
        ("ishdan bo'shatilganim uchun ariza yozib ber", intent.DRAFT),
        ("shikoyat tayyorlab ber", intent.DRAFT),
        ("soliq bo'yicha prezentatsiya qilib ber", intent.DRAFT),
    ],
)
def test_the_free_path_settles_the_obvious_cases(message, expected):
    assert intent._fast_path(message, has_attachment=False) == expected


@pytest.mark.parametrize(
    "message",
    [
        "sen nimaga qodirsan",
        "menga qanday foyda berasan",
        "nima ish qilasan",
        "bugun ob-havo qanday",
    ],
)
def test_what_the_patterns_cannot_settle_goes_to_the_model(message):
    """These are exactly the phrasings the old regex-only router got wrong."""
    assert intent._fast_path(message, has_attachment=False) is None


def test_an_upload_is_always_legal_work():
    assert intent._fast_path("bu nima?", has_attachment=True) == intent.LEGAL


def test_a_long_message_is_somebody_describing_their_situation():
    story = "Meni ishdan bo'shatishdi. " * 40
    assert len(story) > intent.MAX_CLASSIFIED_CHARS
    assert intent._fast_path(story, has_attachment=False) == intent.LEGAL


@pytest.mark.asyncio
async def test_the_obvious_cases_never_reach_the_model():
    llm = FakeLLM()
    assert await intent.classify("salom", llm) == intent.CONVERSATION
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_the_model_decides_what_the_patterns_could_not():
    llm = FakeLLM('{"toifa": "suhbat", "sabab": "imkoniyatlar haqida"}')
    assert await intent.classify("sen nimaga qodirsan", llm) == intent.CONVERSATION
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_an_unrelated_question_is_recognised_as_such():
    llm = FakeLLM('{"toifa": "tashqari", "sabab": "ob-havo"}')
    assert await intent.classify("bugun ob-havo qanday", llm) == intent.OFF_TOPIC


@pytest.mark.asyncio
async def test_an_unknown_label_falls_back_to_a_legal_answer():
    llm = FakeLLM('{"toifa": "nimadir", "sabab": "?"}')
    assert await intent.classify("sen nimaga qodirsan", llm) == intent.LEGAL


@pytest.mark.asyncio
async def test_broken_json_falls_back_to_a_legal_answer():
    llm = FakeLLM("bu json emas")
    assert await intent.classify("sen nimaga qodirsan", llm) == intent.LEGAL


@pytest.mark.asyncio
async def test_a_model_failure_never_blocks_the_answer():
    llm = FakeLLM(RuntimeError("provider down"))
    assert await intent.classify("sen nimaga qodirsan", llm) == intent.LEGAL
