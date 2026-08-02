"""What each tariff allows.

The limits live here rather than in the handlers so that adding a plan is a data change,
and so the same numbers drive the quota check, the pricing page and the tests. Prices are
in so'm because that is what a customer pays; the cost side is tracked in USD because that
is what the model provider bills.
"""

from dataclasses import dataclass, field
from datetime import date

from ..config import settings


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    price_uzs: int
    # what the plan is for, in one line, shown on the pricing page
    tagline: str
    daily_questions: int
    allow_agentic: bool = False
    allow_attachments: bool = False
    attachment_mb: int = 0
    allow_api_keys: bool = False
    api_keys_max: int = 0
    # how long conversations are kept for this plan, in days
    history_days: int = 30
    max_search_k: int = 10
    # whether the plan appears on the pricing page and can be ordered
    listed: bool = True
    features: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_unlimited(self) -> bool:
        return self.daily_questions <= 0

    @property
    def is_purchasable(self) -> bool:
        return self.listed and self.price_uzs > 0

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "price_uzs": self.price_uzs,
            "tagline": self.tagline,
            "daily_questions": self.daily_questions,
            "allow_agentic": self.allow_agentic,
            "allow_attachments": self.allow_attachments,
            "attachment_mb": self.attachment_mb,
            "allow_api_keys": self.allow_api_keys,
            "api_keys_max": self.api_keys_max,
            "history_days": self.history_days,
            "listed": self.listed,
            "purchasable": self.is_purchasable,
            "features": list(self.features),
        }


PLANS: dict[str, Plan] = {
    "free": Plan(
        key="free",
        name="Bepul",
        price_uzs=0,
        tagline="Tizim bilan tanishish uchun",
        daily_questions=5,
        history_days=14,
        max_search_k=10,
        features=(
            "Kuniga 5 ta savol",
            "Barcha agent rejimlari",
            "Har javob ostida manba havolalari",
        ),
    ),
    "standart": Plan(
        key="standart",
        name="Standart",
        price_uzs=39_000,
        tagline="Muntazam foydalanadigan fuqarolar uchun",
        daily_questions=50,
        allow_attachments=True,
        attachment_mb=10,
        history_days=180,
        max_search_k=20,
        features=(
            "Kuniga 50 ta savol",
            "Hujjat yuklab tahlil qildirish (PDF, DOCX, rasm)",
            "Suhbat tarixi 6 oy saqlanadi",
        ),
    ),
    "pro": Plan(
        key="pro",
        name="Pro",
        price_uzs=99_000,
        tagline="Yuristlar va faol foydalanuvchilar uchun",
        daily_questions=300,
        allow_agentic=True,
        allow_attachments=True,
        attachment_mb=10,
        history_days=365,
        max_search_k=30,
        features=(
            "Kuniga 300 ta savol",
            "Agentik rejim — lex.uz dan real vaqtda tekshirish",
            "Hujjat yuklash va tahlil",
            "Suhbat tarixi 1 yil saqlanadi",
        ),
    ),
    # not sold and not listed on the pricing page: this is the account the service is
    # operated from, and it has to be able to exercise every capability the product has
    "owner": Plan(
        key="owner",
        name="Egasi",
        price_uzs=0,
        tagline="Tizim yaratuvchisi uchun — cheksiz",
        daily_questions=0,
        allow_agentic=True,
        allow_attachments=True,
        attachment_mb=25,
        allow_api_keys=True,
        api_keys_max=50,
        history_days=36500,
        max_search_k=100,
        listed=False,
        features=(
            "Cheksiz savol",
            "Barcha rejimlar va vositalar",
            "API kalitlari",
            "Suhbat tarixi cheksiz saqlanadi",
        ),
    ),
    "biznes": Plan(
        key="biznes",
        name="Biznes",
        price_uzs=890_000,
        tagline="Korxona yuristlari va yuridik firmalar uchun",
        daily_questions=2000,
        allow_agentic=True,
        allow_attachments=True,
        attachment_mb=10,
        allow_api_keys=True,
        api_keys_max=10,
        history_days=1095,
        max_search_k=50,
        features=(
            "Kuniga 2000 ta savol",
            "API kalitlari — o'z tizimingizga ulash",
            "Agentik rejim va hujjat tahlili",
            "Suhbat tarixi 3 yil saqlanadi",
            "Ustuvor qo'llab-quvvatlash",
        ),
    ),
}

DEFAULT_PLAN = "free"


def get(key: str | None) -> Plan:
    return PLANS.get((key or DEFAULT_PLAN).lower(), PLANS[DEFAULT_PLAN])


def is_owner(email: str | None) -> bool:
    if not email:
        return False
    owners = {
        item.strip().lower() for item in settings.owner_emails.split(",") if item.strip()
    }
    return email.strip().lower() in owners


def for_user(user: dict) -> Plan:
    """The plan actually in force, which is not the stored one once it has lapsed."""
    # the owner account is not something a lapsed subscription can demote
    if user.get("plan") == "owner" or is_owner(user.get("email")):
        return PLANS["owner"]
    expires = user.get("plan_expires_at")
    if expires:
        try:
            if date.fromisoformat(expires[:10]) < date.today():
                return PLANS[DEFAULT_PLAN]
        except ValueError:
            return PLANS[DEFAULT_PLAN]
    return get(user.get("plan"))


def catalogue(include_hidden: bool = False) -> list[dict]:
    return [
        plan.as_dict() for plan in PLANS.values() if include_hidden or plan.listed
    ]


def price_usd(plan: Plan) -> float:
    return round(plan.price_uzs / settings.usd_to_uzs, 2) if settings.usd_to_uzs else 0.0
