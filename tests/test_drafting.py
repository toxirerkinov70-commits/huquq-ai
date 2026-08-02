"""Drafting a document from the articles that were found.

The rule under test is the one that matters: a draft may leave a blank, but it may not
fill one in. Everything the person did not say has to come back as a bracketed gap and
be listed, because an invented name on a document addressed to a court is worse than an
obviously unfinished one.
"""

import json

import pytest

from backend.app.services import drafting


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.system = None

    async def generate(self, prompt, system=None, **kwargs):
        self.system = system
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


class FakeHit:
    def __init__(self, payload):
        self.payload = payload


HITS = [
    FakeHit(
        {
            "doc_title": "Mehnat kodeksi",
            "article_no": "174",
            "article_title": "Bekor qilish asoslari",
            "text": "Ish beruvchi mehnat shartnomasini faqat qonunda nazarda tutilgan...",
        }
    )
]

DOCUMENT = {
    "tur": "davo",
    "sarlavha": "Da'vo arizasi",
    "kimga": "Chilonzor tumanlararo sudi",
    "kimdan": "[F.I.Sh.]",
    "matn": ["Birinchi xatboshi.", "Ikkinchi xatboshi."],
    "talablar": ["Lavozimga tiklash"],
    "ilovalar": ["Shartnoma nusxasi"],
    "asos": ["Mehnat kodeksi 174-modda"],
    "toldirilishi_kerak": ["[F.I.Sh.] — to'liq ism"],
}

DECK = {
    "sarlavha": "Mehnat shartnomasi",
    "slaydlar": [
        {"sarlavha": "Birinchi", "punktlar": ["Bir", "Ikki"], "asos": "MK 174-modda"},
        {"sarlavha": "Bo'sh", "punktlar": []},
    ],
}


@pytest.mark.parametrize(
    "question, slides",
    [
        ("soliq bo'yicha prezentatsiya qilib ber", True),
        ("bu mavzuda slaydlar tayyorla", True),
        ("сделай презентацию по налогам", True),
        ("ishdan bo'shatish uchun ariza yozib ber", False),
        ("shikoyat tayyorla", False),
    ],
)
def test_slides_are_asked_for_by_name(question, slides):
    assert drafting.wants_slides(question) is slides


@pytest.mark.asyncio
async def test_a_document_keeps_every_part_the_model_returned():
    result = await drafting.draft("ariza yozib ber", HITS, FakeLLM(DOCUMENT))

    assert result["kind"] == drafting.DOCUMENT
    assert result["doc_type"] == "davo"
    assert result["title"] == "DA'VO ARIZASI"
    assert result["recipient"] == "Chilonzor tumanlararo sudi"
    assert result["body"] == ["Birinchi xatboshi.", "Ikkinchi xatboshi."]
    assert result["grounds"] == ["Mehnat kodeksi 174-modda"]
    assert result["todo"] == ["[F.I.Sh.] — to'liq ism"]
    assert result["disclaimer"]


@pytest.mark.asyncio
async def test_an_unknown_document_type_becomes_an_ariza():
    payload = dict(DOCUMENT, tur="qandaydir")
    result = await drafting.draft("yozib ber", HITS, FakeLLM(payload))
    assert result["doc_type"] == "ariza"


@pytest.mark.asyncio
async def test_an_empty_body_is_refused_rather_than_shown():
    payload = dict(DOCUMENT, matn=[])
    with pytest.raises(drafting.DraftingError):
        await drafting.draft("ariza yozib ber", HITS, FakeLLM(payload))


@pytest.mark.asyncio
async def test_slides_without_points_are_dropped():
    result = await drafting.draft("prezentatsiya qilib ber", HITS, FakeLLM(DECK))

    assert result["kind"] == drafting.SLIDES
    assert len(result["slides"]) == 1
    assert result["slides"][0]["bullets"] == ["Bir", "Ikki"]


@pytest.mark.asyncio
async def test_a_deck_with_nothing_in_it_is_refused():
    with pytest.raises(drafting.DraftingError):
        await drafting.draft("prezentatsiya", HITS, FakeLLM({"slaydlar": []}))


@pytest.mark.asyncio
async def test_the_request_picks_the_right_instructions():
    llm = FakeLLM(DECK)
    await drafting.draft("slayd qilib ber", HITS, llm)
    assert "taqdimot" in llm.system.lower()

    llm = FakeLLM(DOCUMENT)
    await drafting.draft("ariza yozib ber", HITS, llm)
    assert "rasmiy hujjat" in llm.system.lower()


def test_the_context_carries_the_article_the_draft_must_rest_on():
    context = drafting.build_context(HITS)
    assert "Mehnat kodeksi" in context
    assert "174-modda" in context


def test_the_chat_line_lists_what_is_left_to_fill_in():
    document = {
        "kind": drafting.DOCUMENT,
        "title": "ARIZA",
        "todo": ["[sana] — ariza sanasi"],
    }
    line = drafting.summary_line(document)
    assert "ARIZA" in line
    assert "[sana] — ariza sanasi" in line
