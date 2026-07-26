from dataclasses import dataclass, field

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
        prompt="Jinoyat huquqi sohasiga e'tibor qarat. Jazo turlari va muddatlarini aniq keltir.",
    ),
    "fuqarolik": Agent(
        key="fuqarolik",
        name="Fuqarolik huquqi",
        description="Fuqarolik kodeksi va fuqarolik protsessual kodeksi",
        doc_aliases=("fk", "fpk"),
        prompt="Fuqarolik huquqi sohasiga e'tibor qarat.",
    ),
    "soliq": Agent(
        key="soliq",
        name="Soliq",
        description="Soliq kodeksi va soliqqa oid hujjatlar",
        doc_aliases=("sk",),
        prompt="Soliq huquqi sohasiga e'tibor qarat. Stavkalar va muddatlarni aniq keltir.",
    ),
    "mehnat": Agent(
        key="mehnat",
        name="Mehnat",
        description="Mehnat kodeksi va mehnatga oid qonunlar",
        doc_aliases=("mk",),
        prompt="Mehnat huquqi sohasiga e'tibor qarat.",
    ),
    "shartnoma": Agent(
        key="shartnoma",
        name="Shartnoma",
        description="Fuqarolik kodeksining shartnoma bo'limlari",
        doc_aliases=("fk",),
        prompt=(
            "Shartnoma huquqiga e'tibor qarat: tuzish, o'zgartirish, bekor qilish "
            "va javobgarlik masalalari."
        ),
    ),
    "sud": Agent(
        key="sud",
        name="Sud amaliyoti",
        description="Protsessual kodekslar va sud amaliyoti",
        doc_aliases=("fpk", "jpk", "ipk"),
        prompt="Protsessual normalar va sud amaliyotiga e'tibor qarat.",
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
