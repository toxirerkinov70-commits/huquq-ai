import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# every setting the app reads is fixed before the module that reads it is imported,
# so a developer's own .env can never change what the tests assert
os.environ.update(
    {
        "SQLITE_PATH": str(Path(tempfile.mkdtemp(prefix="huquq-test-")) / "test.db"),
        "AUTH_SECRET": "test-secret-not-for-production",
        "ADMIN_API_KEY": "test-admin-key",
        "GEMINI_API_KEY": "test-key",
        # a real client id in the developer's .env would otherwise decide what these
        # tests see on the sign-in screen
        "GOOGLE_CLIENT_ID": "",
        "SMS_PROVIDER": "console",
        "ENABLE_SCHEDULER": "false",
        "ENVIRONMENT": "test",
        "RATE_LIMIT": "1000/minute",
        "DEFAULT_PLAN": "free",
    }
)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A database of its own per test, so ordering never matters."""
    from backend.app.config import settings
    from backend.app.db import sqlite

    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "app.db"))
    sqlite.init_db()
    return sqlite


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app.config import settings
    from backend.app.db import sqlite

    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "api.db"))
    sqlite.init_db()

    from backend.app.main import app

    # the real retriever loads a 1.1 GB model and needs Qdrant; the tests here are about
    # access control and accounting, so it is replaced with a stub
    class StubRetriever:
        async def close(self):
            pass

    class StubLLM:
        model = "stub"
        prompt_tokens = 0
        output_tokens = 0

        async def close(self):
            pass

    monkeypatch.setattr("backend.app.main.Retriever", lambda *a, **k: StubRetriever())
    monkeypatch.setattr("backend.app.main.LLMClient", lambda *a, **k: StubLLM())

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def token(client):
    return client.post("/api/auth/anon").json()["token"]


@pytest.fixture()
def auth(token):
    """A fresh account: signed in, but the offer not yet accepted."""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def ready_auth(auth):
    """An account past registration, which is the state most tests are about."""
    from backend.app.config import settings
    from backend.app.db import sqlite
    from backend.app.services import auth as auth_service

    sqlite.accept_terms(auth_service.verify_token(auth["Authorization"][7:]), settings.terms_version)
    return auth
