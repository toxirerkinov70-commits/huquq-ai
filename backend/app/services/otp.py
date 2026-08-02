"""Phone registration: number validation, one-time codes, and sending them.

Only Uzbek numbers are accepted, and only real operator codes within them — a nine digit
string starting +998 is not by itself a number anyone can be reached on.

The code is stored hashed. A one-time code is a short-lived password; keeping it in clear
text means a database copy hands over every account that is mid-registration.
"""

import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from ..config import settings
from ..db import sqlite

logger = logging.getLogger(__name__)

COUNTRY_CODE = "998"
# mobile and CDMA codes actually issued in Uzbekistan
OPERATOR_CODES = {
    "20", "33", "50", "55", "77", "88", "90", "91", "93", "94", "95", "97", "98", "99",
}
DIGITS_RE = re.compile(r"\D+")


class OtpError(Exception):
    """Something the user can fix, phrased for them rather than for the log."""

    def __init__(self, code: str, message: str, retry_after: int | None = None) -> None:
        self.code = code
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)

    def as_detail(self) -> dict:
        detail = {"error": self.code, "message": self.message}
        if self.retry_after is not None:
            detail["retry_after"] = self.retry_after
        return detail


def normalize_phone(raw: str) -> str:
    """Any way a person writes their number, reduced to +998XXXXXXXXX.

    People type +998 90 123 45 67, 90 123-45-67 and 998901234567 for the same number,
    and all three have to reach the same account.
    """
    digits = DIGITS_RE.sub("", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 9:
        digits = COUNTRY_CODE + digits
    if not digits.startswith(COUNTRY_CODE) or len(digits) != 12:
        raise OtpError(
            "bad_phone",
            "Faqat O'zbekiston raqamlari qabul qilinadi: +998 XX XXX XX XX",
        )
    operator = digits[3:5]
    if operator not in OPERATOR_CODES:
        raise OtpError(
            "bad_operator",
            f"'{operator}' operator kodi mavjud emas. Raqamni tekshiring.",
        )
    return "+" + digits


def display_phone(phone: str) -> str:
    """+998901234567 -> +998 90 123 45 67"""
    digits = DIGITS_RE.sub("", phone)
    if len(digits) != 12:
        return phone
    return f"+{digits[:3]} {digits[3:5]} {digits[5:8]} {digits[8:10]} {digits[10:]}"


def mask_phone(phone: str) -> str:
    """What the code-entry screen shows: enough to recognise, not enough to leak."""
    digits = DIGITS_RE.sub("", phone)
    if len(digits) != 12:
        return phone
    return f"+{digits[:3]} {digits[3:5]} *** ** {digits[10:]}"


def _hash(code: str, phone: str) -> str:
    # salted with the number so the same code for two people hashes differently
    return hashlib.sha256(f"{phone}:{code}:{settings.auth_secret}".encode()).hexdigest()


def _generate() -> str:
    upper = 10**settings.otp_length
    return str(secrets.randbelow(upper)).zfill(settings.otp_length)


@dataclass
class SentCode:
    phone: str
    expires_in: int
    resend_in: int
    # only ever filled on the console sender, so a developer can finish the flow
    debug_code: str | None = None


async def send_code(raw_phone: str, purpose: str = "register") -> SentCode:
    phone = normalize_phone(raw_phone)

    previous = sqlite.active_otp(phone)
    if previous is not None:
        sent_at = datetime.fromisoformat(previous["sent_at"])
        waited = (datetime.now(timezone.utc) - sent_at).total_seconds()
        if waited < settings.otp_resend_seconds:
            raise OtpError(
                "too_soon",
                "Yangi kod so'rashdan oldin biroz kuting.",
                retry_after=int(settings.otp_resend_seconds - waited),
            )

    if sqlite.otp_sent_today(phone) >= settings.otp_daily_limit:
        raise OtpError(
            "daily_limit",
            "Bu raqamga bugun juda ko'p kod yuborildi. Ertaga urinib ko'ring.",
        )

    code = _generate()
    sqlite.save_otp(phone, _hash(code, phone), purpose, settings.otp_ttl_seconds)
    debug_code = await _deliver(phone, code)
    return SentCode(
        phone=phone,
        expires_in=settings.otp_ttl_seconds,
        resend_in=settings.otp_resend_seconds,
        debug_code=debug_code,
    )


def verify_code(raw_phone: str, code: str) -> str:
    """Returns the normalised number once the code checks out."""
    phone = normalize_phone(raw_phone)
    record = sqlite.active_otp(phone)
    if record is None:
        raise OtpError("no_code", "Bu raqam uchun faol kod yo'q. Qaytadan so'rang.")

    if datetime.fromisoformat(record["expires_at"]) < datetime.now(timezone.utc):
        sqlite.consume_otp(record["id"])
        raise OtpError("expired", "Kod muddati tugadi. Yangi kod so'rang.")

    if record["attempts"] >= settings.otp_max_attempts:
        sqlite.consume_otp(record["id"])
        raise OtpError("too_many_attempts", "Juda ko'p urinish. Yangi kod so'rang.")

    if not hmac.compare_digest(record["code_hash"], _hash(code.strip(), phone)):
        left = settings.otp_max_attempts - sqlite.bump_otp_attempts(record["id"])
        if left <= 0:
            sqlite.consume_otp(record["id"])
            raise OtpError("too_many_attempts", "Juda ko'p urinish. Yangi kod so'rang.")
        raise OtpError("wrong_code", f"Kod noto'g'ri. Yana {left} ta urinish qoldi.")

    sqlite.consume_otp(record["id"])
    return phone


MESSAGE = "Huquq AI. Tasdiqlash kodi: {code}. Uni hech kimga aytmang."


async def _deliver(phone: str, code: str) -> str | None:
    provider = settings.sms_provider.lower()
    if provider == "eskiz":
        await _send_eskiz(phone, code)
        return None
    if settings.environment == "production":
        # refusing here is deliberate: a production deployment that silently logs codes
        # instead of sending them lets anyone with log access take over any account
        raise OtpError(
            "sms_not_configured",
            "SMS xizmati sozlanmagan. Administrator bilan bog'laning.",
        )
    logger.warning("SMS provider is 'console' — code for %s is %s", mask_phone(phone), code)
    return code


async def _send_eskiz(phone: str, code: str) -> None:
    if not settings.eskiz_email or not settings.eskiz_password:
        raise OtpError("sms_not_configured", "SMS xizmati sozlanmagan.")
    async with httpx.AsyncClient(base_url="https://notify.eskiz.uz/api", timeout=30) as client:
        auth = await client.post(
            "/auth/login",
            data={"email": settings.eskiz_email, "password": settings.eskiz_password},
        )
        if auth.status_code != 200:
            logger.error("eskiz auth failed: %s", auth.text[:200])
            raise OtpError("sms_failed", "SMS yuborib bo'lmadi. Keyinroq urinib ko'ring.")
        token = auth.json()["data"]["token"]

        response = await client.post(
            "/message/sms/send",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "mobile_phone": phone.lstrip("+"),
                "message": MESSAGE.format(code=code),
                "from": settings.eskiz_from,
            },
        )
    if response.status_code not in (200, 201):
        logger.error("eskiz send failed: %s", response.text[:200])
        raise OtpError("sms_failed", "SMS yuborib bo'lmadi. Keyinroq urinib ko'ring.")
