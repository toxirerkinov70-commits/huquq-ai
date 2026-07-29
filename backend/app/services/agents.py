"""The domain modes, and what each of them goes looking for.

A mode is more than a filter. Someone who describes what happened to them needs the
article that names the act, but also the ones that decide how heavily it lands:
mitigation, aggravation, the grounds for release from liability, the deadline that may
have already passed. Those articles do not share the words of the question — nobody
writing "men odam o'ldirib qo'ydim" says "yengillashtiruvchi holatlar" — so retrieval
driven by the question alone never reaches them.

Each mode therefore carries a short list of companion searches. They run beside the
question's own search and their results are appended to the context, which is what lets
the answer set out the whole picture instead of one article.

How an answer to a described situation is laid out is common to every mode and lives in
the system prompt; what a mode adds here is the part specific to its field.
"""

from dataclasses import dataclass

from . import aliases
from .retrieval import SearchFilters


@dataclass(frozen=True)
class Agent:
    key: str
    name: str
    description: str
    doc_aliases: tuple[str, ...] = ()
    okoz_prefixes: tuple[str, ...] = ()
    act_types: tuple[int, ...] = ()
    prompt: str = ""
    # searches run beside the question's own, to bring in the norms that decide the
    # weight of the outcome rather than name the act
    facets: tuple[str, ...] = ()

    def filters(self) -> SearchFilters:
        doc_ids: dict[str, None] = {}
        for alias in self.doc_aliases:
            for doc_id in aliases.documents_for_alias(alias):
                doc_ids.setdefault(doc_id, None)
        return SearchFilters(doc_ids=list(doc_ids), act_types=list(self.act_types))


AGENTS: dict[str, Agent] = {
    "umumiy": Agent(
        key="umumiy",
        name="Umumiy",
        description="Barcha hujjatlar bo'yicha qidiradi",
    ),
    "jinoyat": Agent(
        key="jinoyat",
        name="Jinoyat huquqi",
        description="Jinoyat kodeksi, JPK, jinoyat-ijroiya kodeksi",
        doc_aliases=("jk", "jpk", "jik"),
        facets=(
            "jazoni yengillashtiruvchi holatlar",
            "jazoni og'irlashtiruvchi holatlar",
            "jinoiy javobgarlikdan ozod qilish asoslari",
        ),
        prompt="""Jinoyat huquqi sohasiga e'tibor qarat.
- Jazo turi va muddatini modda sanksiyasida yozilganidek keltir, o'rtacha yoki taxminiy
  muddat aytma.
- Qilmish qasddanmi, ehtiyotsizlikdanmi, zarur mudofaa yoki kuchli ruhiy hayajon
  holatidami — bu kvalifikatsiyani butunlay o'zgartiradi. Faktlardan buni aniq bilib
  bo'lmasa, har bir variantni tegishli moddasi bilan alohida ko'rsat.
- Kontekstda yengillashtiruvchi, og'irlashtiruvchi yoki javobgarlikdan ozod qiluvchi
  holatlar moddalari bo'lsa, ularni tushirib qoldirma.
- Keyingi qadamlarda himoyachi yordamidan foydalanish huquqini eslat.""",
    ),
    "fuqarolik": Agent(
        key="fuqarolik",
        name="Fuqarolik huquqi",
        description="Fuqarolik kodeksi va fuqarolik protsessual kodeksi",
        doc_aliases=("fk", "fpk"),
        facets=(
            "da'vo muddati",
            "yetkazilgan zararni qoplash majburiyati",
        ),
        prompt="""Fuqarolik huquqi sohasiga e'tibor qarat.
Kontekstda da'vo muddati haqidagi norma bo'lsa, uni albatta eslat — muddat o'tib
ketgan bo'lsa qolgan huquqlar amalda ishlamaydi.""",
    ),
    "soliq": Agent(
        key="soliq",
        name="Soliq",
        description="Soliq kodeksi va soliqqa oid hujjatlar",
        doc_aliases=("sk",),
        facets=(
            "soliq huquqbuzarligi uchun javobgarlik",
            "penya hisoblash tartibi",
        ),
        prompt="""Soliq huquqi sohasiga e'tibor qarat.
Stavkalar, muddatlar va hisoblash tartibini aynan modda matnidagidek keltir.""",
    ),
    "mehnat": Agent(
        key="mehnat",
        name="Mehnat",
        description="Mehnat kodeksi va mehnatga oid qonunlar",
        doc_aliases=("mk",),
        facets=(
            "mehnat shartnomasini bekor qilish asoslari",
            "mehnat nizolarini ko'rish tartibi va muddatlari",
        ),
        prompt="""Mehnat huquqi sohasiga e'tibor qarat.
Xodimning huquqi buzilgan bo'lsa, nizoni ko'rish tartibi va unga murojaat muddatini
kontekstdan topib ko'rsat.""",
    ),
    "shartnoma": Agent(
        key="shartnoma",
        name="Shartnoma",
        description="Fuqarolik kodeksining shartnoma bo'limlari",
        doc_aliases=("fk",),
        facets=(
            "shartnoma majburiyatini buzganlik uchun javobgarlik",
            "neustoyka jarima va penya undirish",
        ),
        prompt="""Shartnoma huquqiga e'tibor qarat: tuzish, o'zgartirish, bekor qilish
va javobgarlik masalalari.
Shartnoma sharti qonunga zid bo'lishi mumkin bo'lsa, buni alohida ayt: imzolangan
shart har doim ham majburiy emas.""",
    ),
    "sud": Agent(
        key="sud",
        name="Sud amaliyoti",
        description="Protsessual kodekslar va sud amaliyoti",
        doc_aliases=("fpk", "jpk", "ipk"),
        facets=(
            "shikoyat berish muddati va tartibi",
            "da'vo arizasiga qo'yiladigan talablar",
        ),
        prompt="""Protsessual normalar va sud amaliyotiga e'tibor qarat.
Muddatlarni (shikoyat, e'tiroz, ariza berish) aniq ko'rsat — ular o'tib ketsa
huquqni amalga oshirib bo'lmaydi.""",
    ),
}

DEFAULT_AGENT = "umumiy"


def get_agent(key: str | None) -> Agent:
    return AGENTS.get((key or DEFAULT_AGENT).lower(), AGENTS[DEFAULT_AGENT])


def list_agents() -> list[dict]:
    return [
        {"key": agent.key, "name": agent.name, "description": agent.description}
        for agent in AGENTS.values()
    ]
