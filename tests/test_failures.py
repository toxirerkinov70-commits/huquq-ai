"""What the user is told when the model call fails, and what makes it fail silently.

A byte order mark at the start of .env once attached itself to the first variable's
name. GEMINI_API_KEY read as empty, every request went to Google without a key, and
Google answered 403 — which reached the user as the single word "Xatolik".
"""

from backend.app.config import Settings, settings
from backend.app.routers.chat import _failure_message
from backend.app.services.llm import LLMError


def test_env_files_written_with_a_byte_order_mark_still_load(tmp_path, monkeypatch):
    # the process environment wins over the file, and the test suite sets a key there
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env = tmp_path / ".env"
    # PowerShell's Set-Content -Encoding utf8 and several Windows editors write this
    env.write_bytes("﻿GEMINI_API_KEY=secret-key\nEMBED_DIM=768\n".encode("utf-8"))

    loaded = Settings(_env_file=str(env))
    assert loaded.gemini_api_key == "secret-key"
    assert loaded.embed_dim == 768


def test_a_plain_env_file_still_loads(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=plain-key\n", encoding="utf-8")
    assert Settings(_env_file=str(env)).gemini_api_key == "plain-key"


def test_the_status_code_decides_what_the_user_is_told():
    assert LLMError("x", 403).reason == "auth"
    assert LLMError("x", 401).reason == "auth"
    assert LLMError("x", 429).reason == "quota"
    assert LLMError("x", 503).reason == "provider"
    assert LLMError("x").reason == "network"


def test_each_failure_gets_its_own_sentence():
    auth = _failure_message(LLMError("403", 403))
    quota = _failure_message(LLMError("429", 429))
    provider = _failure_message(LLMError("503", 503))
    generic = _failure_message(ValueError("something else"))

    assert "kalit" in auth.lower()
    assert "kvota" in quota.lower()
    assert auth != quota != provider != generic
    # none of them leaks the provider's own text
    assert "403" not in auth and "429" not in quota


def test_health_reports_a_missing_key(client, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    body = client.get("/health").json()
    assert body["llm_key"] is False
    assert body["status"] == "degraded"


def test_health_is_content_when_the_key_is_present(client, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "present")
    assert client.get("/health").json()["llm_key"] is True
