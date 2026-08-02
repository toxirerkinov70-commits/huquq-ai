"""What the sign-in screen is told about its own configuration.

A missing Google button reads as a broken page, so outside production the screen is
given the reason. In production it is given nothing: a dead button, or a note about
which environment variable is empty, is not something a customer should see.
"""

from backend.app.config import settings


def test_development_explains_the_missing_google_button(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "google_client_id", "")

    config = client.get("/api/auth/config").json()
    assert config["google_enabled"] is False
    assert config["google_hint"] and "GOOGLE_CLIENT_ID" in config["google_hint"]


def test_production_says_nothing_about_configuration(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "sms_provider", "console")

    config = client.get("/api/auth/config").json()
    assert config["google_enabled"] is False
    assert config["google_hint"] is None
    assert config["sms_hint"] is None


def test_a_configured_google_needs_no_hint(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "google_client_id", "123.apps.googleusercontent.com")

    config = client.get("/api/auth/config").json()
    assert config["google_enabled"] is True
    assert config["google_client_id"] == "123.apps.googleusercontent.com"
    assert config["google_hint"] is None


def test_the_console_sender_is_announced_in_development(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "sms_provider", "console")
    assert client.get("/api/auth/config").json()["sms_hint"]


def test_a_real_sender_needs_no_note(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "sms_provider", "eskiz")
    assert client.get("/api/auth/config").json()["sms_hint"] is None
