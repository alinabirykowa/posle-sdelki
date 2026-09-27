"""Opt-in tests against a real, dedicated PostgreSQL test database.

Run explicitly with TEST_DATABASE_URL configured by the operator. Each test
creates a uniquely named schema and removes ONLY that owned schema afterwards;
it never touches the default/public sessions table. The account needs CREATE
SCHEMA permission. Ordinary test runs skip these tests without contacting a DB.
"""

import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import pytest

from backend import engine
from backend.postgres_repository import PostgresRepository, StorageError


@pytest.fixture
def postgres_factory():
    database_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("Real PostgreSQL integration requires explicit TEST_DATABASE_URL")
    psycopg = pytest.importorskip("psycopg")
    schema = f"posle_test_{uuid.uuid4().hex}"
    assert re.fullmatch(r"posle_test_[0-9a-f]{32}", schema)
    identifier = psycopg.sql.Identifier(schema)

    class IsolatedRepository(PostgresRepository):
        @contextmanager
        def _transaction(self):
            with super()._transaction() as connection:
                # SET LOCAL is transaction-scoped, including with a pooler. A
                # connection returned to a pool cannot retain this search path.
                connection.execute(psycopg.sql.SQL("SET LOCAL search_path TO {}").format(identifier))
                yield connection

    created = False
    try:
        try:
            with psycopg.connect(database_url, connect_timeout=10, autocommit=True) as connection:
                connection.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(identifier))
            created = True
        except psycopg.Error:
            raise RuntimeError("Could not create an isolated PostgreSQL test schema; check TEST_DATABASE_URL and permissions.") from None
        yield lambda: IsolatedRepository(database_url)
    finally:
        if created:
            try:
                with psycopg.connect(database_url, connect_timeout=10, autocommit=True) as connection:
                    connection.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(identifier))
            except psycopg.Error:
                raise RuntimeError(f"Could not remove owned PostgreSQL test schema {schema}; remove that schema manually.") from None


def sample(session_id="one", owner="browser-one", **extra):
    return {"id": session_id, "_owner": owner, "created_at": "2026-09-20T12:00:00Z", "text": "Обсудим условия?", **extra}


def test_postgres_round_trip_restart_jsonb_and_owner_isolation(postgres_factory):
    first = postgres_factory()
    value = sample(messages=[{"text": "Бюджет — 200 000 ₽"}], turns=0)
    first.save_many([value, sample("foreign", owner="browser-two")])
    restarted = postgres_factory()
    assert restarted.get("one") == value
    assert restarted.get("missing") is None
    assert [item["id"] for item in restarted.list("browser-one")] == ["one"]
    with restarted.connect() as connection:
        assert connection.execute("SELECT pg_typeof(data)::text FROM sessions WHERE id = %s", ("one",)).fetchone()[0] == "jsonb"


def test_postgres_savepoint_and_outer_failure_are_atomic(postgres_factory):
    repo = postgres_factory()
    repo.save(sample(turns=0))
    with pytest.raises(ValueError, match="abort whole operation"):
        with repo.hold("one"):
            repo.save(sample(turns=1))
            with pytest.raises(StorageError, match="владелец"):
                repo.save_many([sample("child"), sample(owner="wrong-owner")])
            assert repo.get("child") is None
            assert repo.get("one")["turns"] == 1
            raise ValueError("abort whole operation")
    assert repo.get("one")["turns"] == 0
    assert repo.get("child") is None
    with pytest.raises(StorageError):
        with repo.hold("one"):
            repo.save(sample(turns=2))
            with repo.connect() as connection:
                connection.execute("SELECT 1 / 0")
    assert postgres_factory().get("one")["turns"] == 0


def test_postgres_two_workers_duplicate_message_is_applied_once(postgres_factory):
    repositories = [postgres_factory(), postgres_factory()]
    value = engine.new_session("scope", "deadline", "hard", "demo", "browser-one")
    repositories[0].save(value)
    barrier = Barrier(4)
    text = "Что для вас важнее всего?"

    def send(index):
        repo = repositories[index % 2]
        barrier.wait(timeout=10)
        with repo.hold(value["id"]):
            current = repo.get(value["id"])
            if not engine.message_is_duplicate(current, text, "same-request"):
                response = engine.process_message(current, text, "same-request")
                engine.add_message(current, "assistant", response, "reply")
                repo.save(current)
            return engine.public(current)

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(send, range(4)))
    assert all(result == results[0] for result in results)
    restarted = postgres_factory().get(value["id"])
    assert restarted["turns"] == 1
    assert sum(message.get("client_message_id") == "same-request" for message in restarted["messages"]) == 1
    assert engine.message_is_duplicate(restarted, text, "same-request") is True


def test_postgres_lock_pins_connection_without_blocking_other_session(postgres_factory):
    first, second = postgres_factory(), postgres_factory()
    first.save_many([sample("one"), sample("two")])

    def update_other_session():
        with second.hold("two"):
            value = second.get("two")
            value["turns"] = 1
            second.save(value)
        return second.get("two")

    with ThreadPoolExecutor(max_workers=1) as worker:
        with first.hold("one"):
            with first.connect() as connection:
                before = connection.execute("SELECT pg_backend_pid()").fetchone()[0]
            assert worker.submit(update_other_session).result(timeout=15)["turns"] == 1
            value = first.get("one")
            value["turns"] = 1
            first.save(value)
            with first.connect() as connection:
                after = connection.execute("SELECT pg_backend_pid()").fetchone()[0]
            assert before == after
    assert second.get("one")["turns"] == 1
