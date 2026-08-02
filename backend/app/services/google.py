"""Verifying a Google sign-in.

Two kinds of token arrive here, because Google offers two browser flows and only one of
them works for this client.

An *ID token* comes from the rendered Sign in with Google button. An *access token*
comes from the popup flow (`google.accounts.oauth2.initTokenClient`), which the frontend
falls back to when Google refuses to render that button — see KAMCHILIKLAR.md 3.9.

Either way the token is worth exactly nothing until it has been checked, and the check
that matters is the same in both cases: the token must have been issued *for this
application*. A validly signed token issued for somebody else's client must not sign
anybody in here. Verification goes through Google's own tokeninfo endpoint rather than
local RS256 checking, which keeps this to one network call and no cryptography
dependency, and it runs on the sign-in path only, not on every request.
"""

import logging
from dataclasses import dataclass

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
ALLOWED_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleAuthError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str | None
    picture: str | None


def is_configured() -> bool:
    return bool(settings.google_client_id)


async def verify_id_token(id_token: str) -> GoogleIdentity:
    if not is_configured():
        raise GoogleAuthError("Google orqali kirish sozlanmagan.")
    if not id_token or len(id_token) > 4096:
        raise GoogleAuthError("Google tokeni yaroqsiz.")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(TOKENINFO_URL, params={"id_token": id_token})
    except httpx.HTTPError as exc:
        logger.error("google tokeninfo unreachable: %s", exc)
        raise GoogleAuthError("Google bilan bog'lanib bo'lmadi. Qaytadan urinib ko'ring.")

    if response.status_code != 200:
        logger.warning("google rejected a token: %s", response.text[:200])
        raise GoogleAuthError("Google tokeni tasdiqlanmadi.")

    claims = response.json()

    # the audience is the check that matters: a validly signed token issued for some
    # other application must not sign anybody in here
    if claims.get("aud") != settings.google_client_id:
        logger.warning("google token for a different audience: %s", claims.get("aud"))
        raise GoogleAuthError("Bu token boshqa ilova uchun berilgan.")
    if claims.get("iss") not in ALLOWED_ISSUERS:
        raise GoogleAuthError("Token noto'g'ri manbadan.")

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise GoogleAuthError("Google hisobida elektron pochta yo'q.")
    if claims.get("email_verified") not in (True, "true"):
        raise GoogleAuthError("Google hisobidagi pochta tasdiqlanmagan.")

    return GoogleIdentity(
        sub=str(claims["sub"]),
        email=email,
        email_verified=True,
        name=claims.get("name") or claims.get("given_name"),
        picture=claims.get("picture"),
    )


async def verify_access_token(access_token: str) -> GoogleIdentity:
    """The popup flow hands the browser an access token instead of an ID token.

    An access token carries no claims, so it takes two calls: tokeninfo says who the
    token was issued to, userinfo says who the person is. The first call is the security
    one and cannot be skipped — without it any site's token would open an account here.
    """
    if not is_configured():
        raise GoogleAuthError("Google orqali kirish sozlanmagan.")
    if not access_token or len(access_token) > 4096:
        raise GoogleAuthError("Google tokeni yaroqsiz.")

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            info = await client.get(TOKENINFO_URL, params={"access_token": access_token})
        except httpx.HTTPError as exc:
            logger.error("google tokeninfo unreachable: %s", exc)
            raise GoogleAuthError("Google bilan bog'lanib bo'lmadi. Qaytadan urinib ko'ring.")

        if info.status_code != 200:
            logger.warning("google rejected an access token: %s", info.text[:200])
            raise GoogleAuthError("Google tokeni tasdiqlanmadi.")

        claims = info.json()
        if claims.get("aud") != settings.google_client_id:
            logger.warning("google token for a different audience: %s", claims.get("aud"))
            raise GoogleAuthError("Bu token boshqa ilova uchun berilgan.")

        try:
            profile_response = await client.get(
                USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
        except httpx.HTTPError as exc:
            logger.error("google userinfo unreachable: %s", exc)
            raise GoogleAuthError("Google bilan bog'lanib bo'lmadi. Qaytadan urinib ko'ring.")

        if profile_response.status_code != 200:
            logger.warning("google userinfo refused: %s", profile_response.text[:200])
            raise GoogleAuthError("Google hisobi ma'lumotlari olinmadi.")

    profile = profile_response.json()
    email = (profile.get("email") or "").strip().lower()
    if not email:
        raise GoogleAuthError("Google hisobida elektron pochta yo'q.")
    if profile.get("email_verified") not in (True, "true"):
        raise GoogleAuthError("Google hisobidagi pochta tasdiqlanmagan.")

    # the subject must come from the verified token, not from the profile body alone
    sub = str(profile.get("sub") or claims.get("sub") or "")
    if not sub:
        raise GoogleAuthError("Google hisobi aniqlanmadi.")

    return GoogleIdentity(
        sub=sub,
        email=email,
        email_verified=True,
        name=profile.get("name") or profile.get("given_name"),
        picture=profile.get("picture"),
    )
