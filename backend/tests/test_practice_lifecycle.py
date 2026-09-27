"""Fresh practice versus lost-response recovery, with real account ownership."""

from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

from backend import live
from backend.app import create_app
from backend.tests.test_catalog import CONTENT
from backend.tests.test_training_builder import configuration


PASSWORD = "local-lifecycle-test-password"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "available", lambda: False)
    for key in ("VERCEL", "COOKIE_SECURE", "INITIAL_ADMIN_USERNAME", "INITIAL_ADMIN_DISPLAY_NAME", "INITIAL_ADMIN_PASSWORD_HASH"):
        monkeypatch.delenv(key, raising=False)
    return create_app(tmp_path / "lifecycle.sqlite3")


def register(client, username):
    response = client.post("/api/auth/register", json={
        "username": username, "display_name": username, "password": PASSWORD,
    })
    assert response.status_code == 201, response.text
    return response.json()["user"]


def start_request(app, kind, key):
    if kind == "training":
        return "/api/training/start", {"configuration": configuration(), "mode": "demo", "client_action_id": key}
    store = app.state.catalog
    # Fixture content is published locally; admin access is tested separately.
    item = store.get("local-published-case")
    if item is None:
        item = store.create("local-published-case", deepcopy(CONTENT), "local-test-author")
        item = store.mutate(item["id"], item["revision"], "publish")
    return f"/api/catalog/{item['id']}/start", {"revision": item["published_revision"], "mode": "demo", "client_action_id": key}


def start(client, kind, key):
    path, body = start_request(client.app, kind, key)
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def speak(client, session):
    response = client.post(f"/api/sessions/{session['id']}/messages", json={
        "text": "Что для вас важнее всего в этом проекте?", "client_message_id": "my-private-question",
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("kind", ["training", "catalog"])
@pytest.mark.parametrize("complete_old", [False, True])
def test_normal_start_is_fresh_and_preserves_existing_conversation(app, kind, complete_old):
    with TestClient(app) as client:
        register(client, "learner")
        old = speak(client, start(client, kind, "first-deliberate-start"))
        if complete_old:
            response = client.post(f"/api/sessions/{old['id']}/finish", json={"outcome": "no_agreement"})
            assert response.status_code == 200, response.text
            old = response.json()
            assert old["feedback"]["outcome"] == "no_agreement"
            assert "не означает неудачу" in old["feedback"]["summary"]
        stored_old = app.state.repository.get(old["id"])
        new = start(client, kind, "second-deliberate-start")
        assert new["id"] != old["id"]
        assert new["scenario"] == old["scenario"]
        assert new["context_key"] == old["context_key"]
        assert new["status"] == "active" and new["turns"] == 0
        assert new["proposal"] is None and new["feedback"] is None
        assert new["discovered_interests"] == []
        assert "retry_of" not in new
        assert not any(message["role"] == "user" for message in new["messages"])
        assert client.get(f"/api/sessions/{old['id']}").json() == old
        assert app.state.repository.get(old["id"]) == stored_old
        assert {item["id"] for item in client.get("/api/sessions").json()["sessions"]} == {old["id"], new["id"]}
        report = client.get("/api/progress").json()
        assert report["summary"]["total"] == 2
        assert report["summary"]["completed"] == int(complete_old)
        assert report["summary"]["active"] == 2 - int(complete_old)
        assert (report["latest_completed"] is not None) is complete_old
        # Replaying old network requests must not be reinterpreted as new intent.
        assert start(client, kind, "first-deliberate-start") == old
        assert start(client, kind, "second-deliberate-start") == new
        assert app.state.repository.get(old["id"]) == stored_old


@pytest.mark.parametrize("kind", ["training", "catalog"])
def test_lost_start_response_recovers_latest_state_after_process_restart(app, kind):
    with TestClient(app) as client:
        register(client, "learner")
        session = start(client, kind, "recover-this-request")
        updated = speak(client, session)
        request_path, request_body = start_request(app, kind, "recover-this-request")
        cookies = dict(client.cookies)
    restarted = create_app(app.state.repository.path)
    with TestClient(restarted) as client:
        client.cookies.update(cookies)
        recovered = client.post(request_path, json=request_body)
        assert recovered.status_code == 200, recovered.text
        assert recovered.json() == updated
        assert len(client.get("/api/sessions").json()["sessions"]) == 1
        new = start(client, kind, "explicit-new-conversation")
        assert new["id"] != updated["id"]
        assert client.get(f"/api/sessions/{updated['id']}").json() == updated


def test_list_detail_and_progress_are_private_even_to_catalog_administrator(app):
    app.state.accounts.store.create_user("administrator", "Администратор", PASSWORD, role="admin")
    with TestClient(app) as owner, TestClient(app) as stranger, TestClient(app) as guest, TestClient(app) as admin:
        owner_user = register(owner, "owner")
        register(stranger, "stranger")
        assert admin.post("/api/auth/login", json={"username": "administrator", "password": PASSWORD}).status_code == 200
        original = speak(owner, start(owner, "training", "shared-start-id"))
        finished = owner.post(f"/api/sessions/{original['id']}/finish", json={"outcome": "no_agreement"}).json()
        for viewer in (stranger, guest, admin):
            guessed_owner = {"owner": "account:" + owner_user["id"]}
            listing = viewer.get("/api/sessions", params=guessed_owner)
            assert listing.status_code == 200 and listing.json() == {"sessions": []}
            assert listing.headers["cache-control"] == "no-store"
            detail = viewer.get(f"/api/sessions/{original['id']}")
            missing = viewer.get("/api/sessions/not-a-real-session")
            assert detail.status_code == missing.status_code == 404
            assert detail.json() == missing.json()
            report = viewer.get("/api/progress", params=guessed_owner)
            assert report.status_code == 200
            assert report.json()["summary"]["total"] == 0
            assert report.json()["latest_completed"] is None
            assert original["id"] not in json.dumps(report.json())
        # Even knowledge of a start ID cannot recover a different owner's data.
        own_other = start(stranger, "training", "shared-start-id")
        assert own_other["id"] != original["id"] and own_other["turns"] == 0
        assert len(stranger.get("/api/sessions").json()["sessions"]) == 1
        assert owner.get(f"/api/sessions/{original['id']}").json() == finished
        assert owner.get("/api/progress").json()["latest_completed"]["session_id"] == original["id"]
        assert owner.post("/api/auth/logout", json={}).status_code == 200
        assert owner.get("/api/sessions").json()["sessions"] == []
        assert owner.get("/api/progress").json()["latest_completed"] is None
        assert owner.get(f"/api/sessions/{original['id']}").status_code == 404
        assert owner.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
        assert owner.get(f"/api/sessions/{original['id']}").json() == finished
