"""Buying a plan, and the conversation-row actions."""

from datetime import date, timedelta

import pytest

from backend.app.routers.orders import TERM_DISCOUNTS, activate, price_for
from backend.app.services import plans


def test_a_longer_term_costs_less_per_month():
    monthly = price_for("standart", 1)
    yearly = price_for("standart", 12)
    assert yearly < monthly * 12
    assert round(yearly / 12) < monthly


def test_prices_are_round_numbers():
    for months in TERM_DISCOUNTS:
        assert price_for("pro", months) % 1000 == 0


def test_activation_sets_an_expiry(db):
    user = db.create_user()["id"]
    order = db.create_order(user, "standart", 3, price_for("standart", 3), "transfer")
    activate(order)

    updated = db.get_user(user)
    assert updated["plan"] == "standart"
    expiry = date.fromisoformat(updated["plan_expires_at"])
    assert expiry > date.today() + timedelta(days=80)
    assert db.get_order(order["id"])["status"] == "paid"


def test_renewing_early_adds_to_the_term_instead_of_replacing_it(db):
    user = db.create_user()["id"]
    future = (date.today() + timedelta(days=20)).isoformat()
    db.set_plan(user, "standart", future)

    order = db.create_order(user, "standart", 1, price_for("standart", 1), None)
    activate(order)

    expiry = date.fromisoformat(db.get_user(user)["plan_expires_at"])
    # the twenty days already paid for are still there, plus the new month
    assert expiry > date.today() + timedelta(days=45)


def test_a_lapsed_plan_falls_back_on_its_own(db):
    user = db.create_user()["id"]
    db.set_plan(user, "pro", (date.today() - timedelta(days=1)).isoformat())
    assert plans.for_user(db.get_user(user)).key == "free"


# --- api --------------------------------------------------------------------


@pytest.fixture()
def paid_client(client, auth):
    """A client whose account has accepted the offer, as the chat requires."""
    from backend.app.config import settings
    from backend.app.db import sqlite
    from backend.app.services import auth as auth_service

    user_id = auth_service.verify_token(auth["Authorization"][7:])
    sqlite.accept_terms(user_id, settings.terms_version)
    return client, auth, user_id


def test_quote_lists_every_term(paid_client):
    client, auth, _ = paid_client
    response = client.get("/api/plans/standart/quote", headers=auth)
    assert response.status_code == 200
    months = [option["months"] for option in response.json()["options"]]
    assert months == [1, 3, 6, 12]


def test_the_free_plan_cannot_be_ordered(paid_client):
    client, auth, _ = paid_client
    assert client.get("/api/plans/free/quote", headers=auth).status_code == 400
    assert client.post("/api/orders", json={"plan": "free"}, headers=auth).status_code == 400


def test_the_owner_plan_cannot_be_ordered(paid_client):
    client, auth, _ = paid_client
    response = client.post("/api/orders", json={"plan": "owner"}, headers=auth)
    assert response.status_code == 400


def test_ordering_twice_returns_the_same_order(paid_client):
    client, auth, _ = paid_client
    first = client.post("/api/orders", json={"plan": "pro", "months": 3}, headers=auth).json()
    second = client.post("/api/orders", json={"plan": "pro", "months": 3}, headers=auth).json()
    assert first["id"] == second["id"]
    assert first["status"] == "pending"


def test_an_admin_confirmation_activates_the_plan(paid_client):
    client, auth, user_id = paid_client
    order = client.post("/api/orders", json={"plan": "pro", "months": 1}, headers=auth).json()

    admin = {"X-Admin-Key": "test-admin-key"}
    confirmed = client.post(f"/api/admin/orders/{order['id']}/confirm", headers=admin)
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "paid"
    assert client.get("/api/account", headers=auth).json()["plan"]["key"] == "pro"


def test_orders_belong_to_their_owner(client, paid_client):
    _, auth, _ = paid_client
    stranger = client.post("/api/auth/anon").json()
    other = {"Authorization": f"Bearer {stranger['token']}"}

    order = client.post("/api/orders", json={"plan": "pro"}, headers=auth).json()
    assert client.delete(f"/api/orders/{order['id']}", headers=other).status_code == 404
    assert client.get("/api/orders", headers=other).json() == []


# --- session rows -----------------------------------------------------------


def test_a_conversation_can_be_renamed_and_pinned(paid_client):
    from backend.app.db import sqlite

    client, auth, user_id = paid_client
    first = sqlite.ensure_session(None, user_id)
    sqlite.add_message(first, "user", "birinchi savol")
    second = sqlite.ensure_session(None, user_id)
    sqlite.add_message(second, "user", "ikkinchi savol")

    assert client.patch(
        f"/api/sessions/{first}", json={"title": "Mehnat nizosi"}, headers=auth
    ).status_code == 200
    assert client.patch(
        f"/api/sessions/{first}", json={"pinned": True}, headers=auth
    ).status_code == 200

    rows = client.get("/api/sessions", headers=auth).json()
    # pinned first, and carrying the name it was given rather than its first question
    assert rows[0]["id"] == first
    assert rows[0]["title"] == "Mehnat nizosi"
    assert rows[0]["pinned"] is True


def test_a_stranger_cannot_rename_your_conversation(client, paid_client):
    from backend.app.db import sqlite

    _, auth, user_id = paid_client
    session = sqlite.ensure_session(None, user_id)
    sqlite.add_message(session, "user", "savol")

    stranger = client.post("/api/auth/anon").json()
    other = {"Authorization": f"Bearer {stranger['token']}"}
    response = client.patch(f"/api/sessions/{session}", json={"title": "boshqa"}, headers=other)
    assert response.status_code == 404
    assert sqlite.list_sessions(user_id)[0]["title"] == "savol"


def test_an_empty_patch_is_refused(paid_client):
    from backend.app.db import sqlite

    client, auth, user_id = paid_client
    session = sqlite.ensure_session(None, user_id)
    assert client.patch(f"/api/sessions/{session}", json={}, headers=auth).status_code == 400
