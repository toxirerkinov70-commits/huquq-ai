"""Accounts, conversations and metered usage.

Every connection is opened and closed around a single unit of work. The previous
version relied on ``with sqlite3.connect(...)`` alone, which ends the transaction but
leaves the connection open until the garbage collector gets to it — under concurrent
requests that runs the process out of file handles and produces "database is locked".

WAL is enabled so a reader never blocks the writer, which matters as soon as more than
one person is asking a question at a time.
"""

import json
import logging
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from ..config import settings

logger = logging.getLogger(__name__)

# quota windows follow the user's day, not UTC, or the free allowance resets at 5am
LOCAL_TZ = ZoneInfo("Asia/Tashkent")

# Tables first, then the column migration, then the indexes. In that order because an
# index over a column an older database does not have yet fails outright, and
# CREATE TABLE IF NOT EXISTS will not add the column to a table that already exists.
SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'anon',
    email TEXT,
    plan TEXT NOT NULL DEFAULT 'free',
    plan_expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    label TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    name TEXT,
    phone TEXT,
    google_sub TEXT,
    picture TEXT,
    accepted_terms_at TEXT,
    terms_version TEXT
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'register',
    attempts INTEGER NOT NULL DEFAULT 0,
    sent_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    plan TEXT NOT NULL,
    months INTEGER NOT NULL DEFAULT 1,
    amount_uzs INTEGER NOT NULL,
    provider TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    paid_at TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    key_hash TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL,
    name TEXT,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    agent TEXT NOT NULL DEFAULT 'umumiy',
    created_at TEXT NOT NULL,
    title TEXT,
    pinned INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id TEXT,
    endpoint TEXT NOT NULL,
    kind TEXT NOT NULL,
    model TEXT,
    llm_calls INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    day TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

SCHEMA_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone) WHERE phone IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google ON users(google_sub) WHERE google_sub IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_usage_user_day ON usage_events(user_id, day);
CREATE INDEX IF NOT EXISTS idx_usage_day ON usage_events(day);
CREATE INDEX IF NOT EXISTS idx_otp_phone ON otp_codes(phone, id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at);
"""

HISTORY_LIMIT = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(LOCAL_TZ).date().isoformat()


def seconds_until_reset() -> int:
    now = datetime.now(LOCAL_TZ)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - now).total_seconds())


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """One connection per unit of work, committed on success and always closed."""
    path = Path(settings.sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 15000")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with connect() as connection:
        # WAL is a property of the database file, so it survives every later connection
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.executescript(SCHEMA_TABLES)
        _migrate(connection)
        connection.executescript(SCHEMA_INDEXES)


# columns added after the first release; ALTER TABLE is the only way into a table that
# CREATE TABLE IF NOT EXISTS has already skipped
ADDED_COLUMNS = {
    "sessions": {
        "user_id": "TEXT",
        "title": "TEXT",
        "pinned": "INTEGER NOT NULL DEFAULT 0",
    },
    "users": {
        "name": "TEXT",
        "phone": "TEXT",
        "google_sub": "TEXT",
        "picture": "TEXT",
        "accepted_terms_at": "TEXT",
        "terms_version": "TEXT",
    },
}


def _migrate(connection: sqlite3.Connection) -> None:
    """Bring a database written by an earlier version up to the current shape."""
    for table, columns in ADDED_COLUMNS.items():
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column not in existing:
                logger.info("migrating %s: adding %s", table, column)
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    orphans = connection.execute(
        "SELECT COUNT(*) AS n FROM sessions WHERE user_id IS NULL"
    ).fetchone()["n"]
    if orphans:
        # conversations recorded before accounts existed cannot be attributed to
        # anyone, so they go to one holding account rather than staying readable by
        # whoever asks next
        legacy_id = "legacy-anonymous"
        connection.execute(
            "INSERT OR IGNORE INTO users (id, kind, plan, status, label, created_at) "
            "VALUES (?, 'anon', 'free', 'archived', 'migratsiyadan oldingi suhbatlar', ?)",
            (legacy_id, _now()),
        )
        connection.execute(
            "UPDATE sessions SET user_id = ? WHERE user_id IS NULL", (legacy_id,)
        )
        logger.info("attached %s legacy session(s) to %s", orphans, legacy_id)


# --- users -------------------------------------------------------------------


def create_user(
    kind: str = "anon",
    plan: str | None = None,
    email: str | None = None,
    label: str | None = None,
    name: str | None = None,
    phone: str | None = None,
    google_sub: str | None = None,
    picture: str | None = None,
) -> dict:
    user_id = str(uuid.uuid4())
    with connect() as connection:
        connection.execute(
            "INSERT INTO users (id, kind, email, plan, status, label, created_at, last_seen_at, "
            "name, phone, google_sub, picture) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                kind,
                email,
                plan or settings.default_plan,
                label,
                _now(),
                _now(),
                name,
                phone,
                google_sub,
                picture,
            ),
        )
    return get_user(user_id)  # type: ignore[return-value]


def get_user(user_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def find_user_by(field: str, value: str) -> dict | None:
    if field not in ("phone", "email", "google_sub"):
        raise ValueError(f"unsupported lookup field: {field}")
    with connect() as connection:
        row = connection.execute(
            f"SELECT * FROM users WHERE {field} = ?", (value,)
        ).fetchone()
    return dict(row) if row else None


def update_user(user_id: str, **fields) -> dict | None:
    """Set only the columns named, so a partial profile update cannot blank the rest."""
    allowed = {
        "name",
        "phone",
        "email",
        "google_sub",
        "picture",
        "kind",
        "accepted_terms_at",
        "terms_version",
        "label",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return get_user(user_id)
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with connect() as connection:
        connection.execute(
            f"UPDATE users SET {assignments} WHERE id = ?", (*updates.values(), user_id)
        )
    return get_user(user_id)


def accept_terms(user_id: str, version: str) -> dict | None:
    return update_user(user_id, accepted_terms_at=_now(), terms_version=version)


def touch_user(user_id: str) -> None:
    with connect() as connection:
        connection.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (_now(), user_id))


def set_plan(user_id: str, plan: str, expires_at: str | None = None) -> dict | None:
    with connect() as connection:
        connection.execute(
            "UPDATE users SET plan = ?, plan_expires_at = ? WHERE id = ?",
            (plan, expires_at, user_id),
        )
    return get_user(user_id)


def set_status(user_id: str, status: str) -> dict | None:
    with connect() as connection:
        connection.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
    return get_user(user_id)


def list_users(limit: int = 100, offset: int = 0) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT u.*,
                   (SELECT COUNT(*) FROM usage_events e
                    WHERE e.user_id = u.id AND e.day = ?) AS today_events,
                   (SELECT COALESCE(SUM(cost_usd), 0) FROM usage_events e
                    WHERE e.user_id = u.id) AS total_cost_usd
            FROM users u
            ORDER BY COALESCE(u.last_seen_at, u.created_at) DESC
            LIMIT ? OFFSET ?
            """,
            (today(), limit, offset),
        ).fetchall()
    return [dict(row) for row in rows]


# --- api keys ----------------------------------------------------------------


def create_api_key(user_id: str, key_hash: str, prefix: str, name: str | None = None) -> int:
    with connect() as connection:
        cursor = connection.execute(
            "INSERT INTO api_keys (user_id, key_hash, prefix, name, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, key_hash, prefix, name, _now()),
        )
    return int(cursor.lastrowid)


def find_api_key(key_hash: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL", (key_hash,)
        ).fetchone()
        if row is not None:
            connection.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE id = ?", (_now(), row["id"])
            )
    return dict(row) if row else None


def list_api_keys(user_id: str) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, prefix, name, created_at, last_used_at, revoked_at "
            "FROM api_keys WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def revoke_api_key(user_id: str, key_id: int) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
            (_now(), key_id, user_id),
        )
    return cursor.rowcount > 0


# --- one time codes ----------------------------------------------------------


def save_otp(phone: str, code_hash: str, purpose: str, ttl_seconds: int) -> int:
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    with connect() as connection:
        # an earlier code for the same number is retired, or two live codes would both
        # be valid and the newest one would not be the only way in
        connection.execute(
            "UPDATE otp_codes SET consumed_at = ? WHERE phone = ? AND consumed_at IS NULL",
            (_now(), phone),
        )
        cursor = connection.execute(
            "INSERT INTO otp_codes (phone, code_hash, purpose, sent_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (phone, code_hash, purpose, _now(), expires.isoformat(timespec="seconds")),
        )
    return int(cursor.lastrowid)


def latest_otp(phone: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM otp_codes WHERE phone = ? ORDER BY id DESC LIMIT 1", (phone,)
        ).fetchone()
    return dict(row) if row else None


def active_otp(phone: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM otp_codes WHERE phone = ? AND consumed_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (phone,),
        ).fetchone()
    return dict(row) if row else None


def bump_otp_attempts(otp_id: int) -> int:
    with connect() as connection:
        connection.execute(
            "UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?", (otp_id,)
        )
        row = connection.execute(
            "SELECT attempts FROM otp_codes WHERE id = ?", (otp_id,)
        ).fetchone()
    return int(row["attempts"]) if row else 0


def consume_otp(otp_id: int) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE otp_codes SET consumed_at = ? WHERE id = ?", (_now(), otp_id)
        )


def otp_sent_today(phone: str) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    with connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM otp_codes WHERE phone = ? AND sent_at >= ?",
            (phone, since),
        ).fetchone()
    return int(row["n"])


# --- orders ------------------------------------------------------------------


def create_order(
    user_id: str, plan: str, months: int, amount_uzs: int, provider: str | None
) -> dict:
    order_id = "HQ-" + uuid.uuid4().hex[:10].upper()
    with connect() as connection:
        connection.execute(
            "INSERT INTO orders (id, user_id, plan, months, amount_uzs, provider, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (order_id, user_id, plan, months, amount_uzs, provider, _now()),
        )
    return get_order(order_id)  # type: ignore[return-value]


def get_order(order_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return dict(row) if row else None


def list_orders(user_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
    clauses = []
    params: list = []
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM orders {where} ORDER BY created_at DESC LIMIT ?", params
        ).fetchall()
    return [dict(row) for row in rows]


def set_order_status(order_id: str, status: str, note: str | None = None) -> dict | None:
    paid_at = _now() if status == "paid" else None
    with connect() as connection:
        connection.execute(
            "UPDATE orders SET status = ?, paid_at = COALESCE(?, paid_at), "
            "note = COALESCE(?, note) WHERE id = ?",
            (status, paid_at, note, order_id),
        )
    return get_order(order_id)


# --- sessions ----------------------------------------------------------------


def ensure_session(session_id: str | None, user_id: str, agent: str = "umumiy") -> str:
    """Return the caller's session, creating it when needed.

    A session id belonging to somebody else is not reused: the caller gets a new one
    instead, so guessing an id can never attach a stranger's history to your account.
    """
    with connect() as connection:
        if session_id:
            row = connection.execute(
                "SELECT id, user_id FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is not None:
                if row["user_id"] == user_id:
                    return session_id
                logger.warning("session %s belongs to another account, issuing a new one", session_id)
                session_id = None
        new_id = session_id or str(uuid.uuid4())
        connection.execute(
            "INSERT INTO sessions (id, user_id, agent, created_at) VALUES (?, ?, ?, ?)",
            (new_id, user_id, agent, _now()),
        )
        return new_id


def session_owner(session_id: str) -> str | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT user_id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return row["user_id"] if row else None


def add_message(
    session_id: str, role: str, content: str, sources: list[dict] | None = None
) -> None:
    with connect() as connection:
        connection.execute(
            "INSERT INTO messages (session_id, role, content, sources, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                json.dumps(sources, ensure_ascii=False) if sources else None,
                _now(),
            ),
        )


def get_history(session_id: str, limit: int = HISTORY_LIMIT) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


def list_sessions(user_id: str, limit: int = 100) -> list[dict]:
    """The caller's sessions that hold at least one message.

    A renamed conversation keeps the name it was given; the rest fall back to their
    first question. Pinned ones sort to the top regardless of when they were last used.
    """
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT s.id, s.agent, s.created_at, s.pinned,
                   COALESCE(s.title,
                            (SELECT content FROM messages
                             WHERE session_id = s.id AND role = 'user'
                             ORDER BY id LIMIT 1)) AS title,
                   (SELECT created_at FROM messages
                    WHERE session_id = s.id ORDER BY id DESC LIMIT 1) AS updated_at
            FROM sessions s
            WHERE s.user_id = ?
              AND EXISTS (SELECT 1 FROM messages WHERE session_id = s.id)
            ORDER BY s.pinned DESC, updated_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def update_session(
    session_id: str, user_id: str, title: str | None = None, pinned: bool | None = None
) -> bool:
    updates: dict = {}
    if title is not None:
        updates["title"] = title.strip() or None
    if pinned is not None:
        updates["pinned"] = 1 if pinned else 0
    if not updates:
        return False
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with connect() as connection:
        cursor = connection.execute(
            f"UPDATE sessions SET {assignments} WHERE id = ? AND user_id = ?",
            (*updates.values(), session_id, user_id),
        )
    return cursor.rowcount > 0


def get_session_messages(session_id: str, user_id: str) -> list[dict] | None:
    with connect() as connection:
        owner = connection.execute(
            "SELECT user_id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if owner is None or owner["user_id"] != user_id:
            return None
        rows = connection.execute(
            "SELECT role, content, sources, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [
        {
            "role": row["role"],
            "content": row["content"],
            "sources": json.loads(row["sources"]) if row["sources"] else [],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def delete_session(session_id: str, user_id: str) -> bool:
    with connect() as connection:
        owner = connection.execute(
            "SELECT user_id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if owner is None or owner["user_id"] != user_id:
            return False
        connection.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return True


def delete_user_data(user_id: str) -> dict:
    """Erase every conversation held for one account, on request."""
    with connect() as connection:
        sessions = connection.execute(
            "SELECT id FROM sessions WHERE user_id = ?", (user_id,)
        ).fetchall()
        ids = [row["id"] for row in sessions]
        for session_id in ids:
            connection.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return {"sessions": len(ids)}


# --- usage -------------------------------------------------------------------


def record_usage(
    user_id: str,
    endpoint: str,
    kind: str,
    session_id: str | None = None,
    model: str | None = None,
    llm_calls: int = 0,
    prompt_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    latency_ms: int = 0,
) -> None:
    with connect() as connection:
        connection.execute(
            "INSERT INTO usage_events (user_id, session_id, endpoint, kind, model, llm_calls, "
            "prompt_tokens, output_tokens, cost_usd, latency_ms, day, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                session_id,
                endpoint,
                kind,
                model,
                llm_calls,
                prompt_tokens,
                output_tokens,
                cost_usd,
                latency_ms,
                today(),
                _now(),
            ),
        )


BILLABLE_KINDS = ("question", "agentic", "attachment")


def count_today(user_id: str, kinds: tuple[str, ...] = BILLABLE_KINDS) -> int:
    placeholders = ",".join("?" for _ in kinds)
    with connect() as connection:
        row = connection.execute(
            f"SELECT COUNT(*) AS n FROM usage_events "
            f"WHERE user_id = ? AND day = ? AND kind IN ({placeholders})",
            (user_id, today(), *kinds),
        ).fetchone()
    return int(row["n"])


def usage_summary(user_id: str, days: int = 30) -> dict:
    since = (datetime.now(LOCAL_TZ).date() - timedelta(days=days)).isoformat()
    with connect() as connection:
        totals = connection.execute(
            """
            SELECT COUNT(*) AS events,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(cost_usd), 0) AS cost_usd
            FROM usage_events WHERE user_id = ? AND day >= ?
            """,
            (user_id, since),
        ).fetchone()
        daily = connection.execute(
            """
            SELECT day, COUNT(*) AS events, COALESCE(SUM(cost_usd), 0) AS cost_usd
            FROM usage_events WHERE user_id = ? AND day >= ?
            GROUP BY day ORDER BY day DESC
            """,
            (user_id, since),
        ).fetchall()
    return {
        "window_days": days,
        "totals": dict(totals),
        "daily": [dict(row) for row in daily],
    }


def platform_summary(days: int = 30) -> dict:
    since = (datetime.now(LOCAL_TZ).date() - timedelta(days=days)).isoformat()
    with connect() as connection:
        totals = connection.execute(
            """
            SELECT COUNT(*) AS events,
                   COUNT(DISTINCT user_id) AS active_users,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(cost_usd), 0) AS cost_usd,
                   COALESCE(AVG(latency_ms), 0) AS avg_latency_ms
            FROM usage_events WHERE day >= ?
            """,
            (since,),
        ).fetchone()
        by_plan = connection.execute(
            "SELECT plan, COUNT(*) AS users FROM users GROUP BY plan"
        ).fetchall()
        daily = connection.execute(
            """
            SELECT day, COUNT(*) AS events, COUNT(DISTINCT user_id) AS users,
                   COALESCE(SUM(cost_usd), 0) AS cost_usd
            FROM usage_events WHERE day >= ? GROUP BY day ORDER BY day DESC
            """,
            (since,),
        ).fetchall()
        top = connection.execute(
            """
            SELECT user_id, COUNT(*) AS events, COALESCE(SUM(cost_usd), 0) AS cost_usd
            FROM usage_events WHERE day >= ?
            GROUP BY user_id ORDER BY cost_usd DESC LIMIT 10
            """,
            (since,),
        ).fetchall()
    return {
        "window_days": days,
        "totals": dict(totals),
        "users_by_plan": {row["plan"]: row["users"] for row in by_plan},
        "daily": [dict(row) for row in daily],
        "top_users": [dict(row) for row in top],
    }


def purge_old_data(message_days: int, usage_days: int) -> dict:
    """Retention policy, enforced rather than merely promised in the privacy notice."""
    message_cutoff = (datetime.now(timezone.utc) - timedelta(days=message_days)).isoformat(
        timespec="seconds"
    )
    usage_cutoff = (datetime.now(LOCAL_TZ).date() - timedelta(days=usage_days)).isoformat()
    with connect() as connection:
        stale = connection.execute(
            "SELECT id FROM sessions WHERE created_at < ?", (message_cutoff,)
        ).fetchall()
        ids = [row["id"] for row in stale]
        removed_messages = 0
        for session_id in ids:
            cursor = connection.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            removed_messages += cursor.rowcount
        connection.execute("DELETE FROM sessions WHERE created_at < ?", (message_cutoff,))
        usage_cursor = connection.execute(
            "DELETE FROM usage_events WHERE day < ?", (usage_cutoff,)
        )
        removed_usage = usage_cursor.rowcount
    return {
        "sessions": len(ids),
        "messages": removed_messages,
        "usage_events": removed_usage,
    }


def new_token_secret() -> str:
    return secrets.token_urlsafe(48)
