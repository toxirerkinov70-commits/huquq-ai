"""Ownership, metering and retention at the storage layer."""

from backend.app.services import plans, usage


def test_session_is_bound_to_its_owner(db):
    alice = db.create_user()["id"]
    bob = db.create_user()["id"]
    session = db.ensure_session(None, alice)
    db.add_message(session, "user", "Meros haqida savol")

    assert db.get_session_messages(session, alice) is not None
    assert db.get_session_messages(session, bob) is None
    assert [row["id"] for row in db.list_sessions(bob)] == []
    assert [row["id"] for row in db.list_sessions(alice)] == [session]


def test_a_stranger_cannot_delete_a_session(db):
    alice = db.create_user()["id"]
    bob = db.create_user()["id"]
    session = db.ensure_session(None, alice)
    db.add_message(session, "user", "savol")

    assert db.delete_session(session, bob) is False
    assert db.get_session_messages(session, alice) is not None
    assert db.delete_session(session, alice) is True


def test_claiming_someone_elses_session_id_issues_a_new_one(db):
    alice = db.create_user()["id"]
    bob = db.create_user()["id"]
    session = db.ensure_session(None, alice)

    issued = db.ensure_session(session, bob)
    assert issued != session
    assert db.session_owner(session) == alice
    assert db.session_owner(issued) == bob


def test_usage_counts_only_billable_kinds(db):
    user = db.create_user()["id"]
    db.record_usage(user, "/api/chat", "question")
    db.record_usage(user, "/api/chat", "question")
    db.record_usage(user, "/api/chat", "conversational")
    db.record_usage(user, "/api/search", "search")

    assert db.count_today(user) == 2
    assert db.count_today(user, kinds=("conversational",)) == 1


def test_quota_raises_once_the_day_is_spent(db):
    user = db.create_user()["id"]
    free = plans.get("free")
    for _ in range(free.daily_questions):
        db.record_usage(user, "/api/chat", "question")

    try:
        usage.check_quota(user, free)
    except usage.QuotaExceeded as exc:
        assert exc.limit == free.daily_questions
        assert exc.as_detail()["error"] == "quota_exceeded"
    else:
        raise AssertionError("quota should have been refused")


def test_quota_allows_the_last_question_of_the_day(db):
    user = db.create_user()["id"]
    free = plans.get("free")
    for _ in range(free.daily_questions - 1):
        db.record_usage(user, "/api/chat", "question")
    assert usage.check_quota(user, free)["remaining"] == 1


def test_usage_summary_adds_up_the_cost(db):
    user = db.create_user()["id"]
    db.record_usage(user, "/api/chat", "question", cost_usd=0.004, prompt_tokens=1000)
    db.record_usage(user, "/api/chat", "question", cost_usd=0.006, prompt_tokens=2000)

    totals = db.usage_summary(user)["totals"]
    assert totals["events"] == 2
    assert round(totals["cost_usd"], 4) == 0.01
    assert totals["prompt_tokens"] == 3000


def test_erasing_account_data_leaves_the_ledger(db):
    user = db.create_user()["id"]
    session = db.ensure_session(None, user)
    db.add_message(session, "user", "nozik savol")
    db.record_usage(user, "/api/chat", "question", cost_usd=0.01)

    db.delete_user_data(user)
    assert db.list_sessions(user) == []
    # the usage row carries no question text and is what an invoice is rebuilt from
    assert db.usage_summary(user)["totals"]["events"] == 1


def test_retention_removes_old_conversations(db):
    user = db.create_user()["id"]
    session = db.ensure_session(None, user)
    db.add_message(session, "user", "eski savol")

    with db.connect() as connection:
        connection.execute(
            "UPDATE sessions SET created_at = '2019-01-01T00:00:00+00:00' WHERE id = ?",
            (session,),
        )

    removed = db.purge_old_data(message_days=30, usage_days=30)
    assert removed["sessions"] == 1
    assert removed["messages"] == 1
    assert db.list_sessions(user) == []


def test_migration_attaches_orphan_sessions(db):
    """A database written before accounts existed must not stay world-readable."""
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO sessions (id, user_id, agent, created_at) "
            "VALUES ('old', NULL, 'umumiy', '2024-01-01T00:00:00+00:00')"
        )
    db.init_db()
    assert db.session_owner("old") == "legacy-anonymous"
