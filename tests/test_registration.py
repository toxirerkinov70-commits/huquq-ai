"""Registration: which numbers are accepted, how codes behave, and who gets in."""

import pytest

from backend.app.config import settings
from backend.app.services import otp, plans


@pytest.mark.parametrize(
    "written,expected",
    [
        ("+998 90 123 45 67", "+998901234567"),
        ("998901234567", "+998901234567"),
        ("901234567", "+998901234567"),
        ("90 123-45-67", "+998901234567"),
        ("00998901234567", "+998901234567"),
    ],
)
def test_every_way_of_writing_one_number_lands_on_the_same_account(written, expected):
    assert otp.normalize_phone(written) == expected


@pytest.mark.parametrize(
    "written",
    [
        "+7 900 123 45 67",   # russian number
        "+998 12 345 67 89",  # not an operator code
        "12345",
        "",
        "abc",
    ],
)
def test_foreign_and_malformed_numbers_are_refused(written):
    with pytest.raises(otp.OtpError):
        otp.normalize_phone(written)


def test_the_masked_number_shows_enough_to_recognise_and_no_more():
    masked = otp.mask_phone("+998901234567")
    assert masked.startswith("+998 90")
    assert masked.endswith("67")
    assert "1234" not in masked


def test_display_format_is_readable():
    assert otp.display_phone("+998901234567") == "+998 90 123 45 67"


@pytest.mark.asyncio
async def test_code_round_trip(db, monkeypatch):
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "sms_provider", "console")

    sent = await otp.send_code("901234567")
    assert sent.phone == "+998901234567"
    assert sent.debug_code and len(sent.debug_code) == settings.otp_length
    assert otp.verify_code("901234567", sent.debug_code) == "+998901234567"


@pytest.mark.asyncio
async def test_a_used_code_cannot_be_used_twice(db, monkeypatch):
    monkeypatch.setattr(settings, "environment", "test")
    sent = await otp.send_code("901234567")
    otp.verify_code("901234567", sent.debug_code)
    with pytest.raises(otp.OtpError) as exc:
        otp.verify_code("901234567", sent.debug_code)
    assert exc.value.code == "no_code"


@pytest.mark.asyncio
async def test_wrong_codes_run_out_of_attempts(db, monkeypatch):
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "otp_max_attempts", 3)
    await otp.send_code("901234567")

    for _ in range(3):
        with pytest.raises(otp.OtpError) as exc:
            otp.verify_code("901234567", "000000")
        assert exc.value.code in ("wrong_code", "too_many_attempts")

    with pytest.raises(otp.OtpError) as exc:
        otp.verify_code("901234567", "000000")
    assert exc.value.code in ("too_many_attempts", "no_code")


@pytest.mark.asyncio
async def test_a_second_code_cannot_be_requested_immediately(db, monkeypatch):
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "otp_resend_seconds", 60)
    await otp.send_code("901234567")
    with pytest.raises(otp.OtpError) as exc:
        await otp.send_code("901234567")
    assert exc.value.code == "too_soon"
    assert exc.value.retry_after > 0


@pytest.mark.asyncio
async def test_codes_are_never_logged_in_production(db, monkeypatch):
    """A production deployment with no SMS provider must fail, not print the code."""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "sms_provider", "console")
    with pytest.raises(otp.OtpError) as exc:
        await otp.send_code("901234567")
    assert exc.value.code == "sms_not_configured"


def test_the_code_is_not_stored_in_the_clear(db, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "environment", "test")
    sent = asyncio.run(otp.send_code("901234567"))
    record = db.latest_otp("+998901234567")
    assert record["code_hash"] != sent.debug_code
    assert sent.debug_code not in record["code_hash"]


# --- owner ------------------------------------------------------------------


def test_the_owner_email_gets_the_owner_plan(monkeypatch):
    monkeypatch.setattr(settings, "owner_emails", "toxirerkinov70@gmail.com")
    assert plans.is_owner("toxirerkinov70@gmail.com") is True
    assert plans.is_owner("TOXIRERKINOV70@GMAIL.COM") is True
    assert plans.is_owner("someone@else.com") is False
    assert plans.is_owner(None) is False


def test_the_owner_plan_has_no_ceiling():
    owner = plans.get("owner")
    assert owner.is_unlimited is True
    assert owner.allow_agentic and owner.allow_attachments and owner.allow_api_keys
    # and it is not something a customer can buy
    assert owner.listed is False
    assert owner.is_purchasable is False


def test_an_expired_subscription_never_demotes_the_owner(monkeypatch):
    monkeypatch.setattr(settings, "owner_emails", "toxirerkinov70@gmail.com")
    user = {
        "plan": "owner",
        "email": "toxirerkinov70@gmail.com",
        "plan_expires_at": "2020-01-01",
    }
    assert plans.for_user(user).key == "owner"


def test_the_pricing_page_hides_the_owner_plan():
    assert all(item["key"] != "owner" for item in plans.catalogue())
    assert any(item["key"] == "owner" for item in plans.catalogue(include_hidden=True))
