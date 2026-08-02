"""The access rules as the network sees them."""

BASE64_TXT = "c2Fsb20="  # "salom"


def test_endpoints_require_a_token(client):
    for path in ("/api/sessions", "/api/documents", "/api/account", "/api/quota"):
        assert client.get(path).status_code == 401, path


def test_chat_requires_a_token(client):
    assert client.post("/api/chat", json={"question": "savol"}).status_code == 401


def test_public_endpoints_stay_public(client):
    assert client.get("/api/plans").status_code == 200
    assert client.get("/api/agents").status_code == 200
    assert client.get("/api/updates").status_code == 200


def test_anonymous_signup_gives_a_working_account(client):
    data = client.post("/api/auth/anon").json()
    assert data["plan"] == "free"
    assert data["quota"]["daily_limit"] == 5
    headers = {"Authorization": f"Bearer {data['token']}"}
    assert client.get("/api/account", headers=headers).status_code == 200


def test_a_forged_token_is_refused(client):
    assert client.get("/api/account", headers={"Authorization": "Bearer v1.a.b.c"}).status_code == 401


def test_one_account_cannot_read_anothers_session(client, db):
    first = client.post("/api/auth/anon").json()
    second = client.post("/api/auth/anon").json()

    from backend.app.db import sqlite

    session = sqlite.ensure_session(None, first["user_id"])
    sqlite.add_message(session, "user", "nozik savol")

    headers = {"Authorization": f"Bearer {second['token']}"}
    assert client.get(f"/api/sessions/{session}", headers=headers).status_code == 404
    assert client.delete(f"/api/sessions/{session}", headers=headers).status_code == 404

    owner_headers = {"Authorization": f"Bearer {first['token']}"}
    assert client.get(f"/api/sessions/{session}", headers=owner_headers).status_code == 200


def test_agentic_mode_is_refused_on_the_free_plan(client, ready_auth):
    response = client.post("/api/chat/agentic", json={"question": "savol"}, headers=ready_auth)
    assert response.status_code == 402
    assert response.json()["detail"]["error"] == "feature_not_in_plan"


def test_attachments_are_refused_on_the_free_plan(client, ready_auth):
    response = client.post(
        "/api/chat",
        json={
            "question": "shartnomani tekshir",
            "attachment": {"name": "a.txt", "mime": "text/plain", "data": BASE64_TXT},
        },
        headers=ready_auth,
    )
    assert response.status_code == 402


def test_quota_is_enforced(client, ready_auth):
    from backend.app.db import sqlite
    from backend.app.services import auth as auth_service

    user_id = auth_service.verify_token(ready_auth["Authorization"][7:])
    for _ in range(5):
        sqlite.record_usage(user_id, "/api/chat", "question")

    response = client.post("/api/chat", json={"question": "yana bir savol"}, headers=ready_auth)
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["error"] == "quota_exceeded"
    assert detail["limit"] == 5
    assert "Retry-After" in response.headers


def test_admin_needs_its_own_key(client):
    assert client.get("/api/admin/stats").status_code == 401
    assert client.get("/api/admin/stats", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.get("/api/admin/stats", headers={"X-Admin-Key": "test-admin-key"}).status_code == 200


def test_admin_can_move_an_account_between_plans(client, auth):
    from backend.app.services import auth as auth_service

    user_id = auth_service.verify_token(auth["Authorization"][7:])
    admin = {"X-Admin-Key": "test-admin-key"}

    assert client.post("/api/account/keys", json={"name": "k"}, headers=auth).status_code == 403
    upgrade = client.post(
        "/api/admin/users/plan", json={"user_id": user_id, "plan": "biznes"}, headers=admin
    )
    assert upgrade.status_code == 200
    assert client.post("/api/account/keys", json={"name": "k"}, headers=auth).status_code == 200


def test_an_api_key_authenticates_on_its_own(client, auth):
    from backend.app.services import auth as auth_service

    user_id = auth_service.verify_token(auth["Authorization"][7:])
    admin = {"X-Admin-Key": "test-admin-key"}
    client.post("/api/admin/users/plan", json={"user_id": user_id, "plan": "biznes"}, headers=admin)
    key = client.post("/api/account/keys", json={"name": "k"}, headers=auth).json()["key"]

    response = client.get("/api/account", headers={"X-API-Key": key})
    assert response.status_code == 200
    assert response.json()["user_id"] == user_id
    assert client.get("/api/account", headers={"X-API-Key": "hq_live_wrong"}).status_code == 401


def test_a_blocked_account_is_turned_away(client, auth):
    from backend.app.services import auth as auth_service

    user_id = auth_service.verify_token(auth["Authorization"][7:])
    admin = {"X-Admin-Key": "test-admin-key"}
    client.post(
        "/api/admin/users/status", json={"user_id": user_id, "status": "blocked"}, headers=admin
    )
    assert client.get("/api/account", headers=auth).status_code == 403


def test_update_reports_reject_a_path_instead_of_a_date(client, auth):
    assert client.get("/api/updates/not-a-date", headers=auth).status_code == 400
    assert client.get("/api/updates/....//secret", headers=auth).status_code in (400, 404)


def test_account_data_can_be_erased(client, auth):
    from backend.app.db import sqlite
    from backend.app.services import auth as auth_service

    user_id = auth_service.verify_token(auth["Authorization"][7:])
    session = sqlite.ensure_session(None, user_id)
    sqlite.add_message(session, "user", "savol")

    response = client.delete("/api/account/data", headers=auth)
    assert response.status_code == 200
    assert client.get("/api/sessions", headers=auth).json() == []
