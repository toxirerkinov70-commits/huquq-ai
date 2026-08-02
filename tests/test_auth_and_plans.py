"""Tokens, tariffs and the arithmetic a bill would rest on."""

from datetime import date, timedelta

import pytest

from backend.app.services import auth, plans, usage


def test_token_round_trip():
    token = auth.issue_token("user-1")
    assert auth.verify_token(token) == "user-1"


@pytest.mark.parametrize(
    "token",
    [
        "",
        "nonsense",
        "v1.user-1.123.deadbeef",
        "v2.user-1.123.deadbeef",
    ],
)
def test_forged_tokens_are_rejected(token):
    assert auth.verify_token(token) is None


def test_tampered_user_id_is_rejected():
    token = auth.issue_token("user-1")
    version, _, issued, signature = token.split(".")
    assert auth.verify_token(f"{version}.user-2.{issued}.{signature}") is None


def test_api_key_is_hashed_not_stored():
    raw, hashed, prefix = auth.new_api_key()
    assert raw.startswith(auth.API_KEY_PREFIX)
    assert hashed != raw
    assert auth.hash_api_key(raw) == hashed
    assert raw.startswith(prefix)


def test_expired_plan_falls_back_to_free():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    user = {"plan": "pro", "plan_expires_at": yesterday}
    assert plans.for_user(user).key == "free"


def test_live_plan_is_honoured():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    user = {"plan": "pro", "plan_expires_at": tomorrow}
    assert plans.for_user(user).key == "pro"


def test_unknown_plan_falls_back_to_free():
    assert plans.get("no-such-plan").key == "free"


def test_free_plan_withholds_the_paid_features():
    free = plans.get("free")
    assert free.allow_agentic is False
    assert free.allow_attachments is False
    assert free.allow_api_keys is False


def test_meter_costs_what_the_tokens_cost(monkeypatch):
    from backend.app.config import settings

    monkeypatch.setattr(settings, "price_input_per_mtok", 1.0)
    monkeypatch.setattr(settings, "price_output_per_mtok", 10.0)
    meter = usage.Meter(user_id="u", endpoint="/api/chat", kind="question")
    meter.add("gemini-2.5-flash", 1_000_000, 100_000)
    assert meter.cost_usd == pytest.approx(2.0)
    assert meter.llm_calls == 1


def test_bound_meter_collects_calls_from_anywhere():
    meter = usage.new_meter("u", "/api/chat", "question")
    usage.record("gemini-2.5-flash", 100, 20)
    usage.record("gemini-2.5-flash", 50, 10)
    assert meter.prompt_tokens == 150
    assert meter.output_tokens == 30
    assert meter.llm_calls == 2
    usage.bind(None)


def test_recording_without_a_meter_is_harmless():
    usage.bind(None)
    usage.record("gemini-2.5-flash", 100, 20)
