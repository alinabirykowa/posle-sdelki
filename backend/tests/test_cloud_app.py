"""App wiring for cloud storage; no actual PostgreSQL or provider calls."""

from contextlib import contextmanager
from importlib import import_module

import pytest
from fastapi.testclient import TestClient

from backend.repository import Repository
from backend.storage import StorageError

app_module = import_module("backend.app")


class TransactionRepository:
    """Assert endpoints hold a shared transaction around their mutations."""

    def __init__(self, path):
        self.local = Repository(path)
        self.held = None
        self.holds = []

    @contextmanager
    def hold(self, session_id):
        assert self.held is None
        self.held = session_id
        self.holds.append(session_id)
        try:
            yield
        finally:
            self.held = None

    def get(self, session_id):
        assert self.held is not None
        return self.local.get(session_id)

    def save(self, session):
        if self.local.get(session["id"]):
            assert self.held == session["id"]
        self.local.save(session)

    def save_many(self, sessions):
        assert self.held == sessions[0]["id"]
        self.local.save_many(sessions)

    def list(self, owner, limit=30):
        return self.local.list(owner, limit)


def test_mutating_endpoints_use_repository_transaction(monkeypatch, tmp_path):
    repo = TransactionRepository(tmp_path / "wiring.sqlite3")
    monkeypatch.setattr(app_module, "create_repository", lambda path: repo)
    with TestClient(app_module.create_app()) as client:
        response = client.post("/api/sessions", json={"scenario_id": "scope", "priority": "deadline"})
        assert response.status_code == 200
        session_id = response.json()["id"]
        prefix = f"/api/sessions/{session_id}"
        actions = [
            ("messages", {"text": "Что для вас важнее всего?", "client_message_id": "m1"}),
            ("proposal", {"option_id": "prioritize_swap", "client_action_id": "p1"}),
            ("finish", {"outcome": "agreement"}),
            ("retry", {"client_action_id": "r1"}),
        ]
        for route, payload in actions:
            response = client.post(f"{prefix}/{route}", json=payload)
            assert response.status_code == 200, response.text
        child = response.json()["id"]
        again = client.post(f"{prefix}/retry", json={"client_action_id": "r1"})
        assert again.status_code == 200
        assert again.json()["id"] == child
        assert repo.holds == [session_id] * 5
        assert repo.held is None


def test_storage_failure_returns_safe_recoverable_api_error(monkeypatch, tmp_path):
    app = app_module.create_app(tmp_path / "error.sqlite3")

    def unavailable(*args):
        raise StorageError("Хранилище временно недоступно. Повторите запрос с тем же идентификатором действия.")

    monkeypatch.setattr(app.state.repository, "list", unavailable)
    with TestClient(app) as client:
        response = client.get("/api/sessions")
        assert response.status_code == 503
        assert "тем же идентификатором" in response.json()["detail"]


@pytest.mark.parametrize("vercel,secure,expected", [("1", "0", True), ("0", "1", True), ("0", "0", False)])
def test_cloud_cookie_always_requires_https(monkeypatch, tmp_path, vercel, secure, expected):
    monkeypatch.setenv("VERCEL", vercel)
    monkeypatch.setenv("COOKIE_SECURE", secure)
    with TestClient(app_module.create_app(tmp_path / "cookie.sqlite3"), base_url="https://testserver") as client:
        response = client.get("/api/health")
        assert ("; Secure" in response.headers["set-cookie"]) is expected
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=lax" in response.headers["set-cookie"]
