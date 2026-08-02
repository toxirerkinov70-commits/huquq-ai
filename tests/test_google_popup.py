"""The popup sign-in flow, which hands the backend an access token.

The check worth testing is the audience one. An access token is a bearer string with no
claims attached, so anybody with a Google account can obtain one from their own site and
post it here; only asking Google who the token was issued for keeps that from opening
somebody else's account.
"""

import pytest

from backend.app.config import settings
from backend.app.services import google

CLIENT_ID = "test-client.apps.googleusercontent.com"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeClient:
    """Answers tokeninfo and userinfo in the order verify_access_token calls them."""

    def __init__(self, tokeninfo: FakeResponse, userinfo: FakeResponse):
        self._tokeninfo = tokeninfo
        self._userinfo = userinfo
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        self.calls.append(url)
        if url == google.TOKENINFO_URL:
            return self._tokeninfo
        return self._userinfo


def install(monkeypatch, tokeninfo: dict, userinfo: dict, tokeninfo_status: int = 200):
    fake = FakeClient(
        FakeResponse(tokeninfo_status, tokeninfo), FakeResponse(200, userinfo)
    )
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(google.httpx, "AsyncClient", lambda **kwargs: fake)
    return fake


@pytest.mark.asyncio
async def test_a_token_issued_for_another_app_is_refused(monkeypatch):
    fake = install(
        monkeypatch,
        tokeninfo={"aud": "somebody-else.apps.googleusercontent.com", "sub": "1"},
        userinfo={"sub": "1", "email": "victim@gmail.com", "email_verified": True},
    )

    with pytest.raises(google.GoogleAuthError):
        await google.verify_access_token("a" * 40)

    # refused before the profile was ever fetched
    assert fake.calls == [google.TOKENINFO_URL]


@pytest.mark.asyncio
async def test_a_rejected_token_never_reaches_userinfo(monkeypatch):
    fake = install(
        monkeypatch,
        tokeninfo={"error": "invalid_token"},
        userinfo={},
        tokeninfo_status=400,
    )

    with pytest.raises(google.GoogleAuthError):
        await google.verify_access_token("a" * 40)
    assert fake.calls == [google.TOKENINFO_URL]


@pytest.mark.asyncio
async def test_an_unverified_email_is_refused(monkeypatch):
    install(
        monkeypatch,
        tokeninfo={"aud": CLIENT_ID, "sub": "42"},
        userinfo={"sub": "42", "email": "someone@gmail.com", "email_verified": False},
    )

    with pytest.raises(google.GoogleAuthError):
        await google.verify_access_token("a" * 40)


@pytest.mark.asyncio
async def test_a_valid_token_yields_the_identity(monkeypatch):
    install(
        monkeypatch,
        tokeninfo={"aud": CLIENT_ID, "sub": "42"},
        userinfo={
            "sub": "42",
            "email": "Toxir@Gmail.com",
            "email_verified": True,
            "name": "Toxir",
            "picture": "https://example.com/a.png",
        },
    )

    identity = await google.verify_access_token("a" * 40)
    assert identity.sub == "42"
    assert identity.email == "toxir@gmail.com"  # normalised, so it matches on file
    assert identity.name == "Toxir"


@pytest.mark.asyncio
async def test_an_unconfigured_client_refuses_before_any_call(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    with pytest.raises(google.GoogleAuthError):
        await google.verify_access_token("a" * 40)
