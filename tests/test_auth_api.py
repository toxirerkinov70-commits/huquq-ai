"""The registration endpoints, and the gate the offer puts in front of the chat."""

from backend.app.config import settings


def test_auth_config_tells_the_screen_what_to_offer(client):
    data = client.get("/api/auth/config").json()
    assert data["allow_anonymous"] is True
    assert data["terms_version"] == settings.terms_version
    assert data["google_enabled"] is False  # no client id in the test settings


def test_google_sign_in_is_refused_when_unconfigured(client):
    response = client.post("/api/auth/google", json={"credential": "x" * 40})
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "google_auth_failed"


def test_google_popup_flow_is_refused_when_unconfigured(client):
    response = client.post("/api/auth/google", json={"access_token": "x" * 40})
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "google_auth_failed"


def test_google_sign_in_needs_one_of_the_two_tokens(client):
    response = client.post("/api/auth/google", json={})
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "google_auth_failed"


def test_a_foreign_number_never_reaches_the_code_step(client):
    response = client.post("/api/auth/phone/start", json={"phone": "+79001234567"})
    assert response.status_code == 400
    assert response.json()["detail"]["error"] in ("bad_phone", "bad_operator")


def test_phone_registration_creates_an_account(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "sms_provider", "console")

    start = client.post("/api/auth/phone/start", json={"phone": "901234567"}).json()
    assert start["registered"] is False
    assert start["phone_masked"].startswith("+998 90")

    verified = client.post(
        "/api/auth/phone/verify", json={"phone": "901234567", "code": start["debug_code"]}
    ).json()
    assert verified["token"]
    # a brand new account has neither a name nor an acceptance yet
    assert verified["needs_profile"] is True
    assert verified["needs_terms"] is True


def test_signing_in_again_finds_the_same_account(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)

    first = client.post("/api/auth/phone/start", json={"phone": "901234567"}).json()
    one = client.post(
        "/api/auth/phone/verify", json={"phone": "901234567", "code": first["debug_code"]}
    ).json()

    second = client.post("/api/auth/phone/start", json={"phone": "+998 90 123 45 67"}).json()
    assert second["registered"] is True
    two = client.post(
        "/api/auth/phone/verify", json={"phone": "901234567", "code": second["debug_code"]}
    ).json()
    assert one["user_id"] == two["user_id"]


def test_a_wrong_code_does_not_let_anybody_in(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "test")
    client.post("/api/auth/phone/start", json={"phone": "901234567"})
    response = client.post(
        "/api/auth/phone/verify", json={"phone": "901234567", "code": "000000"}
    )
    assert response.status_code == 400


def test_the_chat_is_closed_until_the_offer_is_accepted(client, auth):
    response = client.post("/api/chat", json={"question": "savol"}, headers=auth)
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "terms_required"


def test_accepting_the_offer_opens_the_chat(client, auth):
    from backend.app.db import sqlite
    from backend.app.services import auth as auth_service

    completed = client.post(
        "/api/auth/complete", json={"name": "Toxirbek", "accept_terms": True}, headers=auth
    )
    assert completed.status_code == 200
    assert completed.json()["needs_terms"] is False
    assert completed.json()["name"] == "Toxirbek"

    user_id = auth_service.verify_token(auth["Authorization"][7:])
    assert sqlite.get_user(user_id)["terms_version"] == settings.terms_version
    # past the gate, the ordinary quota rules apply again
    assert client.get("/api/account", headers=auth).json()["accepted_terms"] is True


def test_completing_without_accepting_is_refused(client, auth):
    response = client.post(
        "/api/auth/complete", json={"name": "Toxirbek", "accept_terms": False}, headers=auth
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "terms_required"


def test_a_new_offer_version_asks_again(client, auth, monkeypatch):
    client.post("/api/auth/complete", json={"name": "Toxirbek", "accept_terms": True}, headers=auth)
    monkeypatch.setattr(settings, "terms_version", "2027-01-01")

    assert client.get("/api/account", headers=auth).json()["accepted_terms"] is False
    response = client.post("/api/chat", json={"question": "savol"}, headers=auth)
    assert response.status_code == 403


def test_the_name_is_what_the_greeting_uses(client, auth):
    client.post("/api/auth/complete", json={"name": "  Toxirbek  ", "accept_terms": True}, headers=auth)
    assert client.get("/api/account", headers=auth).json()["name"] == "Toxirbek"


def test_a_one_letter_name_is_refused(client, auth):
    response = client.post(
        "/api/auth/complete", json={"name": "T", "accept_terms": True}, headers=auth
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "bad_name"
