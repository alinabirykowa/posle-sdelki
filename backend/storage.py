"""Select local development storage or persistent cloud PostgreSQL storage."""

import os
from pathlib import Path

from .postgres_repository import PostgresRepository, StorageError
from .repository import Repository

ROOT = Path(__file__).resolve().parents[1]


def create_repository(db_path=None):
    # An explicit path makes tests/development independent of ambient cloud env.
    if db_path is not None:
        return Repository(db_path)
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        return PostgresRepository(database_url)
    if os.environ.get("VERCEL") == "1":
        raise StorageError("Для публикации на Vercel настройте DATABASE_URL: локальная SQLite не сохраняется между облачными запусками.")
    return Repository(os.environ.get("DB_PATH", str(ROOT / "backend" / "data" / "sessions.sqlite3")))
