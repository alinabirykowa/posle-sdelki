"""Storage contract/transaction tests with a deliberately explicit fake driver.

These tests exercise adapter control flow and concurrent connection pinning.
They do not prove PostgreSQL SQL syntax, network behavior, or hosted durability;
those require a separate integration run against a provisioned database.
"""

import copy
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Lock, RLock
from types import SimpleNamespace

import pytest

from backend.postgres_repository import PostgresRepository, StorageError, advisory_key
from backend.repository import Repository
from backend.storage import create_repository


class FakeDriverError(Exception):
    pass


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = copy.deepcopy(list(rows))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeDatabase:
    def __init__(self):
        self.rows = {}
        self.connections = []
        self.guard = Lock()
        self.advisory_locks = {}
        self.connect_error = False
        self.fail_statement = None
        self.fail_commit = False

    def connect(self, url, **kwargs):
        if self.connect_error:
            raise FakeDriverError(f"Unable to connect to {url}")
        connection = FakeConnection(self, kwargs)
        with self.guard:
            self.connections.append(connection)
        return connection


class FakeConnection:
    def __init__(self, database, options):
        self.database = database
        self.options = options
        self.pending = {}
        self.locks = []
        self.statements = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def __enter__(self):
        return self

    @contextmanager
    def transaction(self):
        before = copy.deepcopy(self.pending)
        try:
            yield
        except BaseException:
            self.pending = before
            raise

    def __exit__(self, error_type, error, traceback):
        # Match psycopg's path where a failed commit raises before its close().
        if error_type is None and self.database.fail_commit:
            self.database.fail_commit = False
            raise FakeDriverError("Secret commit connection details")
        try:
            if error_type is None:
                with self.database.guard:
                    self.database.rows.update(copy.deepcopy(self.pending))
                self.committed = True
            else:
                self.rolled_back = True
        finally:
            self.close()

    def close(self):
        if not self.closed:
            for lock in reversed(self.locks):
                lock.release()
            self.closed = True

    def execute(self, query, params=None):
        assert not self.closed
        normalized = " ".join(query.split())
        self.statements.append((normalized, params))
        if self.database.fail_statement and self.database.fail_statement in normalized:
            self.database.fail_statement = None
            raise FakeDriverError("Secret connection details should never leave the driver")
        if normalized.startswith("SELECT pg_advisory_xact_lock"):
            with self.database.guard:
                lock = self.database.advisory_locks.setdefault(params[0], RLock())
            lock.acquire()
            self.locks.append(lock)
            return FakeCursor()
        if normalized.startswith(("CREATE ", "SET ", "SELECT set_config(")):
            return FakeCursor()
        with self.database.guard:
            visible = dict(self.database.rows, **self.pending)
        if normalized.startswith("INSERT INTO sessions"):
            session_id, created_at, data, owner = params
            old = visible.get(session_id)
            if old and (old["owner"] != owner or old["created_at"] != created_at):
                return FakeCursor()
            self.pending[session_id] = {"data": json.loads(data), "owner": owner, "created_at": created_at}
            return FakeCursor([(session_id,)])
        if normalized == "SELECT data FROM sessions WHERE id = %s":
            row = visible.get(params[0])
            return FakeCursor([(row["data"],)] if row else [])
        if normalized == "SELECT data FROM sessions WHERE owner = %s ORDER BY created_at DESC LIMIT %s":
            rows = sorted((row for row in visible.values() if row["owner"] == params[0]), key=lambda row: row["created_at"], reverse=True)
            return FakeCursor([(row["data"],) for row in rows[:params[1]]])
        raise AssertionError(f"Fake driver has no implementation for: {normalized}")


@pytest.fixture
def database(monkeypatch):
    database = FakeDatabase()
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=database.connect, Error=FakeDriverError))
    return database


@pytest.fixture
def repo(database):
    return PostgresRepository("postgresql://fake-user:fake-password@unused.invalid/test")


def session(session_id="one", owner="browser-one", created_at="2026-09-20T10:00:00Z", **extra):
    return {"id": session_id, "created_at": created_at, "_owner": owner, "text": "Русский текст", **extra}


def test_round_trip_and_missing_session(repo, database):
    assert repo.get("missing") is None
    value = session(messages=[{"text": "Какой бюджет?"}], nested={"a": [1, True, None]})
    repo.save(value)
    assert repo.get("one") == value
    assert all(connection.closed and connection.committed for connection in database.connections)
    assert all(connection.options == {"connect_timeout": 10, "prepare_threshold": None} for connection in database.connections)


def test_schema_initialized_only_once_per_repository(repo, database):
    repo.get("one")
    repo.get("two")
    ddl = [query for connection in database.connections for query, _ in connection.statements if query.startswith("CREATE TABLE")]
    assert len(ddl) == 1
    schema = database.connections[0]
    lock_position = next(i for i, (query, _) in enumerate(schema.statements) if "pg_advisory_xact_lock" in query)
    ddl_position = next(i for i, (query, _) in enumerate(schema.statements) if query.startswith("CREATE TABLE"))
    assert lock_position < ddl_position


def test_failed_schema_can_be_retried(repo, database):
    database.fail_statement = "CREATE TABLE"
    with pytest.raises(StorageError):
        repo.get("one")
    assert database.connections[0].rolled_back
    assert repo.get("one") is None
    assert database.connections[1].committed


def test_list_is_owner_scoped_latest_first_and_limited(repo):
    repo.save_many([session(str(i), created_at=f"2026-09-20T10:{i:02}:00Z") for i in range(35)])
    repo.save(session("other", owner="browser-two", created_at="2026-09-21T00:00:00Z"))
    rows = repo.list("browser-one")
    assert len(rows) == 30
    assert [item["id"] for item in rows] == [str(i) for i in range(34, 4, -1)]
    assert [item["id"] for item in repo.list("browser-one", limit=2)] == ["34", "33"]
    assert repo.list("unknown") == []


@pytest.mark.parametrize("changed", [{"_owner": "attacker"}, {"created_at": "2030-01-01"}])
def test_update_preserves_owner_and_creation_date(repo, changed):
    original = session()
    repo.save(original)
    with pytest.raises(StorageError, match="владелец или дата"):
        repo.save(dict(original, **changed))
    assert repo.get("one") == original


def test_save_many_is_atomic_on_bad_second_item(repo, database):
    repo.save(session("one", turns=0))
    with pytest.raises(TypeError):
        repo.save_many([session("one", turns=1), session("child", invalid=object())])
    assert database.connections[-1].closed and database.connections[-1].rolled_back
    assert repo.get("one")["turns"] == 0
    assert repo.get("child") is None


def test_save_many_rolls_back_first_item_on_owner_conflict(repo):
    repo.save(session("existing"))
    with pytest.raises(StorageError):
        repo.save_many([session("child"), session("existing", owner="attacker")])
    assert repo.get("child") is None
    assert repo.get("existing")["_owner"] == "browser-one"


def test_save_many_remains_atomic_when_error_is_caught_inside_hold(repo):
    repo.save(session("existing", turns=0))
    with repo.hold("existing"):
        with pytest.raises(StorageError):
            repo.save_many([session("child"), session("existing", owner="attacker")])
        assert repo.get("child") is None
        repo.save(session("existing", turns=1))
    assert repo.get("child") is None
    assert repo.get("existing")["turns"] == 1


def test_hold_pins_lock_read_and_all_writes_until_commit(repo, database):
    repo.save(session(turns=0))
    before = len(database.connections)
    with repo.hold("one"):
        current = repo.get("one")
        current["turns"] += 1
        repo.save_many([current, session("child")])
        assert repo.get("child")["id"] == "child"
        assert "child" not in database.rows
        assert database.rows["one"]["data"]["turns"] == 0
        assert len(database.connections) == before + 1
    connection = database.connections[-1]
    assert connection.committed and connection.closed
    lock_position = next(i for i, (query, _) in enumerate(connection.statements) if "pg_advisory_xact_lock" in query)
    read_position = next(i for i, (query, _) in enumerate(connection.statements) if query.startswith("SELECT data"))
    assert lock_position < read_position
    assert database.rows["one"]["data"]["turns"] == 1
    assert database.rows["child"]["data"]["id"] == "child"


def test_hold_rolls_back_application_error_and_releases_pinned_connection(repo, database):
    repo.save(session(turns=0))
    with pytest.raises(ValueError, match="Business rule"):
        with repo.hold("one"):
            repo.save(session(turns=1))
            raise ValueError("Business rule")
    failed = database.connections[-1]
    assert failed.closed and failed.rolled_back
    with repo.hold("one"):
        assert repo.get("one")["turns"] == 0
        repo.save(session(turns=2))
    assert repo.get("one")["turns"] == 2


def test_nested_hold_fails_clearly_and_rolls_back(repo):
    with pytest.raises(StorageError, match="Вложенная"):
        with repo.hold("one"):
            repo.save(session())
            with repo.hold("two"):
                pass
    assert repo.get("one") is None


def test_workers_share_advisory_lock_but_not_connections(repo, database):
    other_worker = PostgresRepository("postgresql://fake/other-worker")
    repo.save(session(turns=0))

    def increment(index):
        worker = repo if index % 2 else other_worker
        with worker.hold("one"):
            value = worker.get("one")
            value["turns"] += 1
            worker.save(value)

    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(increment, range(100)))
    assert repo.get("one")["turns"] == 100
    assert all(connection.closed for connection in database.connections)


def test_other_session_can_progress_while_one_is_locked(repo):
    entered, release = Event(), Event()

    def blocked_session():
        with repo.hold("one"):
            entered.set()
            assert release.wait(3)
            repo.save(session("one"))

    with ThreadPoolExecutor(max_workers=2) as workers:
        pending = workers.submit(blocked_session)
        try:
            assert entered.wait(2)
            with repo.hold("two"):
                repo.save(session("two"))
            assert repo.get("two") is not None
        finally:
            release.set()
        pending.result(timeout=2)


def test_keys_are_stable_and_fit_postgres_bigint():
    assert advisory_key("one") == advisory_key("one")
    assert advisory_key("one") != advisory_key("two")
    assert -2 ** 63 <= advisory_key("одна тренировка") < 2 ** 63
    assert advisory_key("one") == 8874750284682800170


@pytest.mark.parametrize("during_hold", [False, True])
def test_driver_errors_hide_credentials_and_close_transactions(repo, database, during_hold):
    repo.save(session())
    database.fail_statement = "SELECT data"
    with pytest.raises(StorageError) as error:
        if during_hold:
            with repo.hold("one"):
                repo.get("one")
        else:
            repo.get("one")
    assert "Secret" not in str(error.value)
    assert error.value.__suppress_context__ is True
    assert database.connections[-1].rolled_back and database.connections[-1].closed
    assert repo.get("one") is not None


def test_connect_error_hides_url(repo, database):
    database.connect_error = True
    with pytest.raises(StorageError) as error:
        repo.get("one")
    assert "fake-password" not in str(error.value)
    assert "unused.invalid" not in str(error.value)


def test_commit_error_always_closes_connection_and_releases_hold(repo, database):
    repo.save(session(turns=0))
    database.fail_commit = True
    with pytest.raises(StorageError) as error:
        with repo.hold("one"):
            repo.save(session(turns=1))
    assert "Secret" not in str(error.value)
    assert database.connections[-1].closed
    with repo.hold("one"):
        repo.save(session(turns=2))
    assert repo.get("one")["turns"] == 2


def test_queries_bind_untrusted_values_as_parameters(repo, database):
    malicious = "one'; DROP TABLE sessions; --"
    repo.save(session(malicious, owner="owner'; --"))
    assert repo.get(malicious)["id"] == malicious
    assert len(repo.list("owner'; --")) == 1
    for connection in database.connections:
        for query, params in connection.statements:
            assert malicious not in query
            assert "owner'; --" not in query


def test_explicit_path_forces_sqlite_even_in_cloud(tmp_path, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused.invalid/must-not-connect")
    value = create_repository(tmp_path / "explicit.sqlite3")
    assert isinstance(value, Repository)
    value.save(session())
    assert value.get("one")["text"] == "Русский текст"


def test_local_default_honors_db_path(tmp_path, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    path = tmp_path / "local.sqlite3"
    monkeypatch.setenv("DB_PATH", str(path))
    value = create_repository()
    assert isinstance(value, Repository)
    assert value.path == str(path)


@pytest.mark.parametrize("url", ["", "  "])
def test_cloud_without_persistent_database_fails_closed(tmp_path, monkeypatch, url):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DATABASE_URL", url)
    path = tmp_path / "must-not-exist.sqlite3"
    monkeypatch.setenv("DB_PATH", str(path))
    with pytest.raises(StorageError, match="DATABASE_URL"):
        create_repository()
    assert not path.exists()


def test_configured_postgres_is_lazy_and_never_falls_back(database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:test@unused.invalid/cloud")
    value = create_repository()
    assert isinstance(value, PostgresRepository)
    assert database.connections == []
    database.connect_error = True
    with pytest.raises(StorageError):
        value.save(session())


def test_missing_driver_has_safe_actionable_message(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)
    with pytest.raises(StorageError, match="psycopg"):
        PostgresRepository("postgresql://username:password@host/database")


def test_json_text_compatibility():
    assert PostgresRepository._decode('{"id": "one"}') == {"id": "one"}
