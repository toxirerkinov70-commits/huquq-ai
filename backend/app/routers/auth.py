"""Registration and sign-in.

Two doors, one account. A phone number is verified with a code; a Google account is
verified with the token Google issued for this application. Either way the same thing is
true at the end: there is a row in ``users`` the conversations will belong to.

Nobody gets through without accepting the offer. It is checked on the server rather than
trusted from the checkbox, because a checkbox is a claim the client makes about itself.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from ..config import settings
from ..db import sqlite
from ..models import (
    AuthConfig,
    AuthResponse,
    CompleteRegistrationRequest,
    GoogleAuthRequest,
    PhoneStartRequest,
    PhoneStartResponse,
    PhoneVerifyRequest,
    QuotaStatus,
)
from ..services import auth, google, otp, plans, usage
from ..services.auth import Principal

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _terms_accepted(user: dict) -> bool:
    """Acceptance is tied to the version that was accepted, not to a boolean.

    When the offer changes, everyone is asked again — otherwise the record says a user
    agreed to a document they never saw.
    """
    return bool(user.get("accepted_terms_at")) and user.get("terms_version") == settings.terms_version


def _session_for(user: dict) -> AuthResponse:
    plan = plans.for_user(user)
    return AuthResponse(
        token=auth.issue_token(user["id"]),
        user_id=user["id"],
        plan=plan.key,
        quota=QuotaStatus(**usage.snapshot(user["id"], plan)),
        name=user.get("name"),
        needs_profile=not (user.get("name") or "").strip(),
        needs_terms=not _terms_accepted(user),
    )


def _apply_owner(user: dict) -> dict:
    """The service's own account is recognised by its email, not granted by hand."""
    if plans.is_owner(user.get("email")) and user.get("plan") != "owner":
        logger.info("owner account recognised", user_id=user["id"], email=user.get("email"))
        return sqlite.set_plan(user["id"], "owner", None) or user
    return user


@router.get("/config", response_model=AuthConfig)
async def config():
    """What the sign-in screen should offer.

    A button that cannot work is worse than no button, so Google is hidden when it has
    no client id. Outside production the screen says why instead — otherwise the first
    reaction to a missing button is that something is broken.
    """
    development = settings.environment != "production"
    return AuthConfig(
        google_enabled=google.is_configured(),
        google_client_id=settings.google_client_id or None,
        google_hint=(
            "GOOGLE_CLIENT_ID sozlanmagan — Google Cloud Console'dan olib .env ga yozing"
            if development and not google.is_configured()
            else None
        ),
        allow_anonymous=settings.allow_anonymous_signup,
        terms_version=settings.terms_version,
        otp_length=settings.otp_length,
        sms_hint=(
            "Sinov rejimi: SMS yuborilmaydi, kod shu yerda ko'rsatiladi"
            if development and settings.sms_provider.lower() == "console"
            else None
        ),
    )


@router.post("/phone/start", response_model=PhoneStartResponse)
async def phone_start(payload: PhoneStartRequest):
    try:
        sent = await otp.send_code(payload.phone)
    except otp.OtpError as exc:
        raise HTTPException(
            status_code=429 if exc.code in ("too_soon", "daily_limit") else 400,
            detail=exc.as_detail(),
        )
    existing = sqlite.find_user_by("phone", sent.phone)
    logger.info(
        "otp sent", phone=otp.mask_phone(sent.phone), returning=existing is not None
    )
    return PhoneStartResponse(
        phone_masked=otp.mask_phone(sent.phone),
        expires_in=sent.expires_in,
        resend_in=sent.resend_in,
        registered=existing is not None,
        debug_code=sent.debug_code,
    )


@router.post("/phone/verify", response_model=AuthResponse)
async def phone_verify(payload: PhoneVerifyRequest):
    try:
        phone = otp.verify_code(payload.phone, payload.code)
    except otp.OtpError as exc:
        raise HTTPException(status_code=400, detail=exc.as_detail())

    user = sqlite.find_user_by("phone", phone)
    if user is None:
        user = sqlite.create_user(kind="phone", phone=phone)
        logger.info("account created by phone", user_id=user["id"])
    if user.get("status") != "active":
        raise HTTPException(
            status_code=403,
            detail={"error": "account_blocked", "message": "Hisob bloklangan."},
        )
    sqlite.touch_user(user["id"])
    return _session_for(_apply_owner(user))


@router.post("/google", response_model=AuthResponse)
async def google_sign_in(payload: GoogleAuthRequest):
    if not payload.credential and not payload.access_token:
        raise HTTPException(
            status_code=400,
            detail={"error": "google_auth_failed", "message": "Google tokeni yuborilmadi."},
        )
    try:
        if payload.credential:
            identity = await google.verify_id_token(payload.credential)
        else:
            identity = await google.verify_access_token(payload.access_token)
    except google.GoogleAuthError as exc:
        raise HTTPException(
            status_code=400, detail={"error": "google_auth_failed", "message": exc.message}
        )

    user = sqlite.find_user_by("google_sub", identity.sub)
    if user is None:
        # somebody who registered by phone and now signs in with Google keeps the one
        # account, as long as the email is the one already on file
        user = sqlite.find_user_by("email", identity.email)
        if user is not None:
            user = sqlite.update_user(
                user["id"], google_sub=identity.sub, picture=identity.picture
            )
        else:
            user = sqlite.create_user(
                kind="google",
                email=identity.email,
                google_sub=identity.sub,
                name=identity.name,
                picture=identity.picture,
            )
            logger.info("account created by google", user_id=user["id"])
    elif identity.name and not user.get("name"):
        user = sqlite.update_user(user["id"], name=identity.name, picture=identity.picture)

    if user.get("status") != "active":
        raise HTTPException(
            status_code=403,
            detail={"error": "account_blocked", "message": "Hisob bloklangan."},
        )
    sqlite.touch_user(user["id"])
    return _session_for(_apply_owner(user))


@router.post("/complete", response_model=AuthResponse)
async def complete_registration(
    payload: CompleteRegistrationRequest,
    principal: Principal = Depends(auth.current_principal),
):
    """The last step: the name to greet by, and acceptance of the offer."""
    if not payload.accept_terms and not _terms_accepted(principal.user):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "terms_required",
                "message": "Davom etish uchun ommaviy oferta shartlarini qabul qiling.",
            },
        )

    name = (payload.name or "").strip()
    if name:
        if len(name) < 2:
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_name", "message": "Ism kamida 2 ta harfdan iborat bo'lsin."},
            )
        sqlite.update_user(principal.id, name=name)

    if payload.accept_terms:
        sqlite.accept_terms(principal.id, settings.terms_version)

    user = sqlite.get_user(principal.id)
    logger.info("registration completed", user_id=principal.id, named=bool(name))
    return _session_for(user)


@router.post("/anon", response_model=AuthResponse)
async def anonymous_signup(request: Request):
    """Trying the service without registering.

    Kept because the first question should not need a phone number. Such an account
    still owns its own conversations, and still has to accept the offer before asking.
    """
    if not settings.allow_anonymous_signup:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "signup_disabled",
                "message": "Ro'yxatdan o'tmasdan foydalanish yopilgan.",
            },
        )
    user = sqlite.create_user(kind="anon", plan=settings.default_plan)
    logger.info("anonymous account created", user_id=user["id"])
    return _session_for(user)
