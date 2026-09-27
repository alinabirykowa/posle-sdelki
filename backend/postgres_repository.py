"""Persistent cloud storage with a transaction-scoped lock per training session.

The synchronous FastAPI endpoint must keep ``hold()`` and its repository calls
on the same thread. The lock, reads, and writes use one connection, including
when a hosted PostgreSQL service uses a transaction pooler. No connection is
kept open between requests; local SQLite continues to use SessionLocks.
"""

import hashlib
import json
from contextlib import contextmanager
from threading import Lock, local


class StorageError(RuntimeError):
    """A safe, user-facing error that never includes connection credentials."""


def advisory_key(session_id):
    """Stable across processes; Python's randomized hash() cannot be used here."""
    digest = hashlib.sha256(f"posle/session/{session_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class PostgresRepository:
    def __init__(self, database_url):
        try:
            import psycopg
        except ImportError:
            raise StorageError("Для облачного хранения установите серверную зависимость psycopg.") from None
        if not database_url or not database_url.strip():
            raise StorageError("Не настроено подключение к постоянной базе данных.")
        self._database_url = database_url
        self._driver = psycopg
        self._local = local()
        self._schema_guard = Lock()
        self._schema_ready = False

    @contextmanager
    def _transaction(self):
        try:
            # Disable prepared statements for transaction-pooling compatibility.
            connection = self._driver.connect(self._database_url, connect_timeout=10, prepare_threshold=None)
            try:
                with connection:
                    connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                    connection.execute("SELECT set_config('lock_timeout', '10000', true)")
                    connection.execute("SELECT set_config('statement_timeout', '15000', true)")
                    yield connection
            finally:
                # psycopg 3.3's context can exit before its close() if commit()
                # raises. Release the connection even when acknowledgement of
                # the commit is lost; retry IDs resolve the uncertain outcome.
                connection.close()
        except self._driver.Error:
            raise StorageError("Хранилище временно недоступно. Повторите запрос с тем же идентификатором действия.") from None

    def _ensure_schema(self):
        if self._schema_ready:
            return
        with self._schema_guard:
            if self._schema_ready:
                return
            with self._transaction() as connection:
                # Serialize first-time DDL across serverless instances too.
                schema_key = int.from_bytes(hashlib.sha256(b"posle/schema/v1").digest()[:8], "big", signed=True)
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (schema_key,))
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        data JSONB NOT NULL,
                        owner TEXT NOT NULL DEFAULT ''
                    )
                """)
                connection.execute("CREATE INDEX IF NOT EXISTS sessions_owner_created_at ON sessions(owner, created_at DESC)")
            self._schema_ready = True

    @contextmanager
    def connect(self):
        """Reuse hold()'s transaction; otherwise complete one transaction here."""
        pinned = getattr(self._local, "connection", None)
        if pinned is not None:
            yield pinned
            return
        self._ensure_schema()
        with self._transaction() as connection:
            yield connection

    @contextmanager
    def hold(self, session_id):
        """Atomically read, decide, and persist a session across workers.

        Nested holds are deliberately rejected: endpoints need one session lock
        only, and acquiring arbitrary additional locks could create deadlocks.
        save_many() may write the parent and its newly created retry together.
        """
        if getattr(self._local, "connection", None) is not None:
            raise StorageError("Вложенная блокировка тренировки не поддерживается.")
        self._ensure_schema()
        with self._transaction() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (advisory_key(session_id),))
            self._local.connection = connection
            try:
                yield
            finally:
                del self._local.connection

    def save(self, session):
        self.save_many([session])

    def save_many(self, sessions):
        """Persist all related sessions or none; ownership cannot be replaced."""
        with self.connect() as connection:
            # The connection already has a transaction. This creates a savepoint
            # so save_many remains atomic if its caller catches an error inside
            # hold() and continues other work in the outer transaction.
            with connection.transaction():
                for session in sessions:
                    row = connection.execute(
                        """
                        INSERT INTO sessions(id, created_at, data, owner)
                        VALUES (%s, %s, %s::jsonb, %s)
                        ON CONFLICT(id) DO UPDATE SET data = excluded.data
                        WHERE sessions.owner = excluded.owner
                          AND sessions.created_at = excluded.created_at
                        RETURNING id
                        """,
                        (session["id"], session["created_at"], json.dumps(session, ensure_ascii=False), session.get("_owner", "")),
                    ).fetchone()
                    if row is None:
                        raise StorageError("Сохранение тренировки отклонено: владелец или дата создания изменились.")

    def get(self, session_id):
        with self.connect() as connection:
            row = connection.execute("SELECT data FROM sessions WHERE id = %s", (session_id,)).fetchone()
        return self._decode(row[0]) if row else None

    def list(self, owner, limit=30):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT data FROM sessions WHERE owner = %s ORDER BY created_at DESC LIMIT %s", (owner, limit),
            ).fetchall()
        return [self._decode(row[0]) for row in rows]

    def list_all(self, owner):
        """Complete owner-scoped history; the conversation list stays bounded."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT data FROM sessions WHERE owner = %s ORDER BY created_at DESC, id", (owner,),
            ).fetchall()
        return [self._decode(row[0]) for row in rows]

    @staticmethod
    def _decode(value):
        # psycopg returns JSONB as dicts; also accept JSON text from compatible
        # drivers or an existing table created with a text data column.
        return json.loads(value) if isinstance(value, str) else value
