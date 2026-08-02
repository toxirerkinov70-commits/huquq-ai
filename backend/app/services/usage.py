"""Measuring what a request costs, and refusing the ones a plan does not cover.

Token counts used to be a pair of numbers on the shared LLM client, accumulated since
process start. That says what the whole service spent and nothing about who spent it,
which is enough to be surprised by a bill and not enough to charge for anything.

A meter is created per request and bound to the context, so every LLM call made while
serving that request adds to it wherever in the stack it happens. Streaming responses
bind the same meter again inside the generator, because the body is iterated in a
different context from the handler that built it.
"""

import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from ..config import settings
from ..db import sqlite
from .plans import Plan

logger = logging.getLogger(__name__)

_current: ContextVar["Meter | None"] = ContextVar("usage_meter", default=None)


@dataclass
class Meter:
    user_id: str
    endpoint: str
    kind: str
    session_id: str | None = None
    llm_calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    models: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    def add(self, model: str | None, prompt_tokens: int, output_tokens: int) -> None:
        self.llm_calls += 1
        self.prompt_tokens += prompt_tokens
        self.output_tokens += output_tokens
        if model and model not in self.models:
            self.models.append(model)

    @property
    def cost_usd(self) -> float:
        return round(
            self.prompt_tokens / 1_000_000 * settings.price_input_per_mtok
            + self.output_tokens / 1_000_000 * settings.price_output_per_mtok,
            6,
        )

    @property
    def cost_uzs(self) -> float:
        return round(self.cost_usd * settings.usd_to_uzs, 2)

    @property
    def latency_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)


def new_meter(user_id: str, endpoint: str, kind: str, session_id: str | None = None) -> Meter:
    meter = Meter(user_id=user_id, endpoint=endpoint, kind=kind, session_id=session_id)
    bind(meter)
    return meter


def bind(meter: Meter | None) -> None:
    _current.set(meter)


def current() -> Meter | None:
    return _current.get()


def record(model: str | None, prompt_tokens: int, output_tokens: int) -> None:
    """Called from the LLM client after every completed call."""
    meter = _current.get()
    if meter is not None:
        meter.add(model, prompt_tokens, output_tokens)


def flush(meter: Meter, session_id: str | None = None) -> None:
    """Persist one request's usage. Never raises: a bookkeeping failure must not
    turn an answer the user already received into an error."""
    try:
        sqlite.record_usage(
            user_id=meter.user_id,
            endpoint=meter.endpoint,
            kind=meter.kind,
            session_id=session_id or meter.session_id,
            model=meter.models[-1] if meter.models else None,
            llm_calls=meter.llm_calls,
            prompt_tokens=meter.prompt_tokens,
            output_tokens=meter.output_tokens,
            cost_usd=meter.cost_usd,
            latency_ms=meter.latency_ms,
        )
    except Exception:
        logger.exception("could not record usage for %s", meter.user_id)


# --- quotas ------------------------------------------------------------------


class QuotaExceeded(Exception):
    def __init__(self, plan: Plan, used: int, reset_seconds: int) -> None:
        self.plan = plan
        self.used = used
        self.limit = plan.daily_questions
        self.reset_seconds = reset_seconds
        super().__init__(f"{plan.key}: {used}/{plan.daily_questions}")

    def as_detail(self) -> dict:
        return {
            "error": "quota_exceeded",
            "message": (
                f"Kunlik chegara tugadi ({self.used}/{self.limit}). "
                "Ertaga yangilanadi yoki tarifni ko'taring."
            ),
            "plan": self.plan.key,
            "used": self.used,
            "limit": self.limit,
            "reset_seconds": self.reset_seconds,
        }


class FeatureNotInPlan(Exception):
    def __init__(self, plan: Plan, feature: str, message: str) -> None:
        self.plan = plan
        self.feature = feature
        self.message = message
        super().__init__(message)

    def as_detail(self) -> dict:
        return {
            "error": "feature_not_in_plan",
            "message": self.message,
            "plan": self.plan.key,
            "feature": self.feature,
        }


def snapshot(user_id: str, plan: Plan) -> dict:
    used = sqlite.count_today(user_id)
    remaining = -1 if plan.is_unlimited else max(plan.daily_questions - used, 0)
    return {
        "plan": plan.key,
        "plan_name": plan.name,
        "used_today": used,
        "daily_limit": plan.daily_questions,
        "remaining": remaining,
        "reset_seconds": sqlite.seconds_until_reset(),
    }


def check_quota(user_id: str, plan: Plan) -> dict:
    """Raise when the day's allowance is spent, otherwise return the current standing."""
    status = snapshot(user_id, plan)
    if not plan.is_unlimited and status["used_today"] >= plan.daily_questions:
        raise QuotaExceeded(plan, status["used_today"], status["reset_seconds"])
    return status


def check_conversational(user_id: str, plan: Plan) -> None:
    """Greetings do not spend a question, but they are not free to the service either.

    Charging one against the daily allowance would let "salom" eat a free user's five
    questions. Leaving them entirely uncounted would make the endpoint an unmetered way
    to spend model quota, so a much looser ceiling applies instead.
    """
    if plan.is_unlimited:
        return
    used = sqlite.count_today(user_id, kinds=("question", "agentic", "attachment", "conversational"))
    if used >= plan.daily_questions * 3:
        raise QuotaExceeded(plan, used, sqlite.seconds_until_reset())


def check_agentic(plan: Plan) -> None:
    if not plan.allow_agentic:
        raise FeatureNotInPlan(
            plan,
            "agentic",
            "Agentik rejim Pro va Biznes tariflarida mavjud.",
        )


def check_attachment(plan: Plan, size_bytes: int) -> None:
    if not plan.allow_attachments:
        raise FeatureNotInPlan(
            plan,
            "attachments",
            "Hujjat yuklash Standart tarifidan boshlab mavjud.",
        )
    limit = plan.attachment_mb * 1024 * 1024
    if limit and size_bytes > limit:
        raise FeatureNotInPlan(
            plan,
            "attachment_size",
            f"Fayl hajmi {plan.attachment_mb} MB dan oshmasligi kerak.",
        )
