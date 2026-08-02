"""Who is calling, and what they are allowed to spend.

Two ways in. A browser gets a signed bearer token from ``/api/auth/anon`` — no
registration, but from then on a conversation belongs to an account and nobody else can
read it. A machine uses an API key, which is what a Biznes customer integrates with.

The token is signed rather than stored: verifying it costs a hash instead of a query,
and revocation still works because the account behind it is checked on every request.
"""

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, HTTPException, Request, status

from ..config import settings
from ..db import sqlite
from . import plans
from .plans import Plan

logger = logging.getLogger(__name__)

TOKEN_VERSION = "v1"
API_KEY_PREFIX = "hq_live_"
SECRET_FILE = Path("./data/.auth_secret")

_secret_cache: str | None = None


def secret() -> str:
    """The signing key: configured, or generated once and kept beside the database.

    Generating it keeps a fresh checkout working without setup. It is written to disk
    rather than held in memory because a restart would otherwise sign out every user.
    """
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache
    if settings.auth_secret:
        _secret_cache = settings.auth_secret
        return _secret_cache
    if SECRET_FILE.exists():
        _secret_cache = SECRET_FILE.read_text(encoding="utf-8").strip()
        return _secret_cache
    generated = sqlite.new_token_secret()
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRET_FILE.write_text(generated, encoding="utf-8")
    try:
        SECRET_FILE.chmod(0o600)
    except OSError:
        # windows filesystems reject the mode; the file still sits inside data/
        pass
    logger.warning(
        "AUTH_SECRET not set, generated one at %s — set it explicitly in production",
        SECRET_FILE,
    )
    _secret_cache = generated
    return _secret_cache


def _sign(payload: str) -> str:
    return hmac.new(secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def issue_token(user_id: str) -> str:
    issued = str(int(time.time()))
    payload = f"{user_id}.{issued}"
    return f"{TOKEN_VERSION}.{payload}.{_sign(payload)}"


def verify_token(token: str) -> str | None:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != TOKEN_VERSION:
        return None
    _, user_id, issued, signature = parts
    if not hmac.compare_digest(_sign(f"{user_id}.{issued}"), signature):
        return None
    return user_id


def new_api_key() -> tuple[str, str, str]:
    """Returns the key shown once, its stored hash, and the displayable prefix."""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_api_key(raw), raw[: len(API_KEY_PREFIX) + 6]


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class Principal:
    user: dict
    plan: Plan
    method: str

    @property
    def id(self) -> str:
        return self.user["id"]

    @property
    def is_admin(self) -> bool:
        return self.user.get("kind") == "admin"


def _unauthorised(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "unauthorized", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _resolve(request: Request) -> Principal:
    api_key = request.headers.get("x-api-key")
    if api_key:
        record = sqlite.find_api_key(hash_api_key(api_key))
        if record is None:
            raise _unauthorised("API kalit yaroqsiz yoki bekor qilingan.")
        user = sqlite.get_user(record["user_id"])
        if user is None:
            raise _unauthorised("API kalitga bog'langan hisob topilmadi.")
        method = "api_key"
    else:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise _unauthorised("Avtorizatsiya talab qilinadi. /api/auth/anon dan token oling.")
        user_id = verify_token(header[7:].strip())
        if user_id is None:
            raise _unauthorised("Token yaroqsiz. Yangi token oling.")
        user = sqlite.get_user(user_id)
        if user is None:
            raise _unauthorised("Hisob topilmadi. Yangi token oling.")
        method = "bearer"

    if user.get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "account_blocked", "message": "Hisob bloklangan."},
        )
    return Principal(user=user, plan=plans.for_user(user), method=method)


async def current_principal(request: Request) -> Principal:
    principal = _resolve(request)
    request.state.user_id = principal.id
    return principal


async def optional_principal(request: Request) -> Principal | None:
    """For endpoints that read public reference data but still log who asked."""
    try:
        return await current_principal(request)
    except HTTPException:
        return None


async def require_admin(request: Request) -> Principal:
    """Admin endpoints are off unless ADMIN_API_KEY is configured."""
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    supplied = request.headers.get("x-admin-key", "")
    if not supplied or not hmac.compare_digest(supplied, settings.admin_api_key):
        raise _unauthorised("Admin kaliti noto'g'ri.")
    return Principal(
        user={"id": "admin", "kind": "admin", "plan": "biznes", "status": "active"},
        plan=plans.get("biznes"),
        method="admin_key",
    )


CurrentUser = Depends(current_principal)
AdminUser = Depends(require_admin)
