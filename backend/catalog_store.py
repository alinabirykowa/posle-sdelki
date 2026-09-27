"""Persistent case drafts and immutable publication snapshots.

The catalogue shares the application's configured SQLite/PostgreSQL database.
Schema creation is lazy so application startup and unrelated endpoints do not
require the catalogue tables. Every mutation locks its row (or SQLite writer)
before checking the revision; a stale editor cannot overwrite newer work.
"""

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from threading import Lock

from .engine import RuleError, now


def content_digest(content):
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CatalogStore:
    def __init__(self, repository):
        self.repository = repository
        self.postgres = hasattr(repository, "hold")
        self._schema_ready = False
        self._schema_guard = Lock()

    def execute(self, connection, sql, params=()):
        return connection.execute(sql.replace("?", "%s") if self.postgres else sql, params)

    def ensure_schema(self):
        if self._schema_ready:
            return
        with self._schema_guard:
            if self._schema_ready:
                return
            with self.repository.connect() as connection:
                if self.postgres:
                    key = int.from_bytes(hashlib.sha256(b"posle/catalog/schema/v1").digest()[:8], "big", signed=True)
                    connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS catalog_cases (
                        id TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL,
                        data TEXT NOT NULL
                    )
                """)
            self._schema_ready = True

    @contextmanager
    def _write(self, case_id):
        self.ensure_schema()
        with self.repository.connect() as connection:
            if self.postgres:
                # Also locks a not-yet-created row, making duplicate creates
                # serial across independent serverless workers.
                key = int.from_bytes(hashlib.sha256(f"posle/catalog/{case_id}".encode()).digest()[:8], "big", signed=True)
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
            else:
                connection.execute("BEGIN IMMEDIATE")
            yield connection

    def _read(self, connection, case_id):
        row = self.execute(connection, "SELECT data FROM catalog_cases WHERE id = ?", (case_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def _save(self, connection, item):
        self.execute(connection, """
            INSERT INTO catalog_cases(id, updated_at, data) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at, data = excluded.data
        """, (item["id"], item["updated_at"], json.dumps(item, ensure_ascii=False)))

    def get(self, case_id):
        self.ensure_schema()
        with self.repository.connect() as connection:
            return self._read(connection, case_id)

    def list(self):
        self.ensure_schema()
        with self.repository.connect() as connection:
            rows = connection.execute("SELECT data FROM catalog_cases ORDER BY updated_at DESC, id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def create(self, case_id, content, author):
        with self._write(case_id) as connection:
            existing = self._read(connection, case_id)
            if existing is not None:
                if existing["_created_by"] != author or existing["_create_digest"] != content_digest(content):
                    raise RuleError("Этот идентификатор создания уже использован с другим содержимым. Создайте новый идентификатор.", 409)
                return existing
            timestamp = now()
            item = {
                "id": case_id, "revision": 1, "status": "draft", "content": deepcopy(content),
                "created_at": timestamp, "updated_at": timestamp,
                "published_at": None, "published_revision": None, "published_content": None,
                "_created_by": author, "_create_digest": content_digest(content),
            }
            self._save(connection, item)
            return item

    def mutate(self, case_id, revision, action, content=None):
        with self._write(case_id) as connection:
            item = self._read(connection, case_id)
            if item is None:
                raise RuleError("Ситуация не найдена.", 404)
            if item["revision"] != revision:
                raise RuleError("Ситуация уже изменена. Обновите страницу и проверьте последнюю версию перед сохранением.", 409)
            if item["status"] == "archived" and action not in {"edit", "publish"}:
                raise RuleError("Ситуация уже в архиве. Для восстановления отредактируйте её и опубликуйте.", 409)
            timestamp = now()
            item["revision"] += 1
            item["updated_at"] = timestamp
            if action == "edit":
                item["content"] = deepcopy(content)
            elif action == "publish":
                if content is not None:
                    # An explicit new publication may move an old financial
                    # template to conversation practice; old snapshots remain.
                    item["content"] = deepcopy(content)
                item["published_content"] = deepcopy(item["content"])
                item["published_revision"] = item["revision"]
                item["published_at"] = timestamp
                item["status"] = "published"
            elif action == "unpublish":
                item["status"] = "draft"
            elif action == "archive":
                item["status"] = "archived"
            else:
                raise ValueError("Unknown catalogue mutation")
            self._save(connection, item)
            return item


def admin_case(item):
    return {
        key: deepcopy(item[key]) for key in (
            "id", "revision", "status", "content", "created_at", "updated_at", "published_at", "published_revision"
        )
    } | {"has_unpublished_changes": item["content"] != item.get("published_content")}


def published_case(item):
    if item is None or item["status"] != "published" or item.get("published_content") is None:
        raise RuleError("Ситуация недоступна. Возможно, администратор снял её с публикации.", 404)
    return {
        "id": item["id"], "revision": item["published_revision"], "status": "published",
        "content": deepcopy(item["published_content"]), "published_at": item["published_at"],
        # Draft edits must not change the publicly visible publication data.
        "updated_at": item["published_at"],
    }
