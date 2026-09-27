"""Локальное сохранение. save и save_many используют атомарные транзакции SQLite."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Repository:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '')")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
            if "owner" not in columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN owner TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, session):
        self.save_many([session])

    def save_many(self, sessions):
        """Persist related sessions together, rolling everything back on failure."""
        with self.connect() as connection:
            for session in sessions:
                connection.execute(
                    "INSERT INTO sessions(id, created_at, data, owner) VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                    (session["id"], session["created_at"], json.dumps(session, ensure_ascii=False), session.get("_owner", "")),
                )

    def get(self, session_id):
        with self.connect() as connection:
            row = connection.execute("SELECT data FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, owner, limit=30):
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM sessions WHERE owner = ? ORDER BY created_at DESC LIMIT ?", (owner, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_all(self, owner):
        """All attempts of one owner for factual aggregates, never other users."""
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM sessions WHERE owner = ? ORDER BY created_at DESC, id", (owner,)).fetchall()
        return [json.loads(row[0]) for row in rows]
