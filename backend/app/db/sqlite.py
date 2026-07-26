import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent TEXT NOT NULL DEFAULT 'umumiy',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""

HISTORY_LIMIT = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    path = Path(settings.sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)


def ensure_session(session_id: str | None, agent: str = "umumiy") -> str:
    with connect() as connection:
        if session_id:
            row = connection.execute(
                "SELECT id FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is not None:
                return session_id
        new_id = session_id or str(uuid.uuid4())
        connection.execute(
            "INSERT INTO sessions (id, agent, created_at) VALUES (?, ?, ?)",
            (new_id, agent, _now()),
        )
        return new_id


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
