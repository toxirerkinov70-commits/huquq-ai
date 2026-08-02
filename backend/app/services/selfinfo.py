"""Questions about the account itself, answered from the account itself.

"Mening tarifim haqida gapirib ber" used to be searched in the corpus, which found the
Labour Code's article on wage tariff grids and answered that. The article was cited
correctly; it simply was not the question. The word carries both meanings, and the
possessive is what separates them: *my* tariff is a subscription, *the* tariff system
is labour law.

Answered here rather than by the model: the figures are known exactly, so there is
nothing to infer, and a question about one's own account should not spend a question
from one's own allowance.
"""

import re

from .plans import Plan

# A first-person marker is required. Without one, "tarif tizimi nima?" is a question
# about the Labour Code and belongs in the corpus.
OWN_ACCOUNT_RE = re.compile(
    r"(mening|menda|mening\s+hisobim|hisobim|o'?z)\s*\w*\s*(tarif|obuna|hisob|chegara|limit)"
    r"|tarifim|obunam|hisobim|chegaram|limitim|akkauntim"
    r"|(qancha|necha|nechta)\s+savol"
    r"|savol\w*\s+(qoldi|qolgan)"
    r"|kunlik\s+cheklov"
    r"|(мо[йя]|моего|моей)\s+(тариф|подписк|аккаунт|лимит)"
    r"|тариф\s+мо[йя]"
    r"|сколько\s+(у\s+меня\s+)?(осталось\s+)?вопрос"
    r"|мой\s+лимит|моя\s+подписка|мой\s+аккаунт",
    re.IGNORECASE,
)

MAX_CHARS = 200


def is_account_question(text: str) -> bool:
    """Whether the person is asking about their own plan rather than about the law."""
    if len(text) > MAX_CHARS:
        return False
    return bool(OWN_ACCOUNT_RE.search(text))


def _russian(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    return sum(1 for char in letters if "а" <= char.lower() <= "я") / len(letters) > 0.3


def _history(days: int, lang: str) -> str:
    """A retention period a person can read. "36500 kun" is a number, not an answer."""
    if days >= 3650:
        return "cheksiz saqlanadi" if lang == "uz" else "хранится бессрочно"
    if days >= 365 and days % 365 == 0:
        years = days // 365
        return f"{years} yil saqlanadi" if lang == "uz" else f"хранится {years} г."
    if days >= 30 and days % 30 == 0:
        months = days // 30
        return f"{months} oy saqlanadi" if lang == "uz" else f"хранится {months} мес."
    return f"{days} kun saqlanadi" if lang == "uz" else f"хранится {days} дней"


def _uz(plan: Plan, quota: dict, user: dict) -> str:
    lines = [f"**Sizning tarifingiz — {plan.name}.** {plan.tagline}.", ""]

    if plan.is_unlimited:
        lines.append("**Kunlik chegara:** yo'q, cheksiz savol berishingiz mumkin.")
    else:
        lines.append(
            f"**Kunlik chegara:** {plan.daily_questions} ta savol. "
            f"Bugun {quota['used_today']} tasini ishlatdingiz, {quota['remaining']} tasi qoldi. "
            "Chegara har kuni yarim tunda yangilanadi."
        )

    lines.append("")
    lines.append("**Nimalar ochiq:**")
    yes, no = "mavjud", "bu tarifda yo'q"
    lines.append(f"- Hujjat yuklash: {yes if plan.allow_attachments else no}")
    lines.append(f"- Agent rejimi: {yes if plan.allow_agentic else no}")
    lines.append(f"- API kalitlari: {yes if plan.allow_api_keys else no}")
    lines.append(f"- Suhbat tarixi: {_history(plan.history_days, 'uz')}")

    if user.get("plan_expires_at"):
        lines.append("")
        lines.append(f"**Amal qilish muddati:** {user['plan_expires_at'][:10]}")

    lines.append("")
    if plan.is_purchasable or plan.price_uzs == 0:
        lines.append("Tarifni ko'rish yoki o'zgartirish uchun: **Sozlamalar → Tarif**.")
    return "\n".join(lines)


def _ru(plan: Plan, quota: dict, user: dict) -> str:
    lines = [f"**Ваш тариф — {plan.name}.** {plan.tagline}.", ""]

    if plan.is_unlimited:
        lines.append("**Дневной лимит:** нет, вопросов можно задавать сколько угодно.")
    else:
        lines.append(
            f"**Дневной лимит:** {plan.daily_questions} вопросов. "
            f"Сегодня использовано {quota['used_today']}, осталось {quota['remaining']}. "
            "Лимит обновляется каждый день в полночь."
        )

    lines.append("")
    lines.append("**Что доступно:**")
    lines.append(f"- Загрузка документов: {'да' if plan.allow_attachments else 'нет на этом тарифе'}")
    lines.append(f"- Режим агента: {'да' if plan.allow_agentic else 'нет на этом тарифе'}")
    lines.append(f"- API-ключи: {'да' if plan.allow_api_keys else 'нет на этом тарифе'}")
    lines.append(f"- История диалогов: {_history(plan.history_days, 'ru')}")

    if user.get("plan_expires_at"):
        lines.append("")
        lines.append(f"**Действует до:** {user['plan_expires_at'][:10]}")

    lines.append("")
    if plan.is_purchasable or plan.price_uzs == 0:
        lines.append("Посмотреть или сменить тариф: **Настройки → Тариф**.")
    return "\n".join(lines)


def account_answer(user: dict, plan: Plan, quota: dict, question: str) -> str:
    return (_ru if _russian(question) else _uz)(plan, quota, user)
