"""Lost HTTP responses must not replay proposals or create extra retry sessions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient

from backend import engine, live
from backend.app import create_app
from backend.locking import SessionLocks
from backend.repository import Repository


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "actions.sqlite3")) as browser:
        yield browser


def create(browser):
    response = browser.post("/api/sessions", json={"scenario_id": "scope", "priority": "deadline"})
    assert response.status_code == 200, response.text
    return response.json()


def offer(browser, session, option="prioritize_swap", action_id="proposal-1"):
    payload = {"option_id": option}
    if action_id is not None:
        payload["client_action_id"] = action_id
    return browser.post(f"/api/sessions/{session['id']}/proposal", json=payload)


def retry(browser, session, action_id="retry-1"):
    return browser.post(f"/api/sessions/{session['id']}/retry", json={"client_action_id": action_id})


def test_duplicate_proposal_returns_current_completed_state(client):
    session = create(client)
    first = offer(client, session)
    assert first.status_code == 200
    assert offer(client, session).json() == first.json()
    assert offer(client, session, "accept_all", "proposal-2").status_code == 200
    final = client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "agreement"}).json()
    recovered = offer(client, session)
    assert recovered.status_code == 200
    assert recovered.json() == final
    assert recovered.json()["turns"] == 2
    assert recovered.json()["proposal"]["option_id"] == "accept_all"
    assert offer(client, session, action_id="brand-new").status_code == 409


def test_duplicate_proposal_precedes_turn_limit(client):
    session = create(client)
    assert offer(client, session).status_code == 200
    repository = client.app.state.repository
    stored = repository.get(session["id"])
    stored["turns"] = 30
    repository.save(stored)
    assert offer(client, session).status_code == 200
    assert offer(client, session).json()["turns"] == 30
    assert offer(client, session, action_id="new-id").status_code == 409


def test_proposal_payload_conflict_never_changes_saved_state(client):
    session = create(client)
    saved = offer(client, session).json()
    conflict = offer(client, session, "accept_all")
    assert conflict.status_code == 409
    assert isinstance(conflict.json()["detail"], str)
    assert client.get(f"/api/sessions/{session['id']}").json() == saved


def test_proposal_transcript_acknowledges_only_the_action_that_created_it(client):
    session = create(client)
    first = offer(client, session).json()
    assert "_client_action_ids" not in first
    acknowledgments = [message for message in first["messages"] if "client_action_id" in message]
    assert len(acknowledgments) == 1
    assert acknowledgments[0]["role"] == "user"
    assert acknowledgments[0]["kind"] == "proposal"
    assert acknowledgments[0]["client_action_id"] == "proposal-1"
    # Deliberately resubmitting the same package under a fresh ID is a new turn.
    second = offer(client, session, action_id="proposal-2").json()
    assert second["turns"] == 2
    assert [message["client_action_id"] for message in second["messages"] if "client_action_id" in message] == ["proposal-1", "proposal-2"]
    without_id = offer(client, session, action_id=None).json()
    assert "client_action_id" not in without_id["messages"][-2]
    assert offer(client, session).json() == without_id


@pytest.mark.parametrize("first_kind", ["proposal", "retry"])
def test_action_ids_share_namespace_across_kinds(client, first_kind):
    session = create(client)
    first = offer(client, session, action_id="shared") if first_kind == "proposal" else retry(client, session, "shared")
    assert first.status_code == 200
    conflict = retry(client, session, "shared") if first_kind == "proposal" else offer(client, session, action_id="shared")
    assert conflict.status_code == 409
    assert len(client.get("/api/sessions").json()["sessions"]) == (1 if first_kind == "proposal" else 2)


def test_ids_are_scoped_to_parent_and_private(client):
    first, second = create(client), create(client)
    assert offer(client, first, action_id="same").status_code == 200
    child = retry(client, second, "same").json()
    # The child also has its own namespace; the parent map is not copied.
    assert offer(client, child, action_id="same").status_code == 200
    for session in client.get("/api/sessions").json()["sessions"]:
        assert not any(key.startswith("_") for key in session)
        assert not any(key.startswith("_") for key in client.get(f"/api/sessions/{session['id']}").json())


def test_proposal_recovery_survives_process_restart(tmp_path):
    database = tmp_path / "restart.sqlite3"
    with TestClient(create_app(database)) as browser:
        session = create(browser)
        saved = offer(browser, session).json()
        cookies = dict(browser.cookies)
    with TestClient(create_app(database)) as browser:
        browser.cookies.update(cookies)
        recovered = offer(browser, session)
        assert recovered.status_code == 200
        assert recovered.json() == saved
        assert recovered.json()["turns"] == 1


def test_retry_recovery_survives_restart_and_returns_updated_child(tmp_path):
    database = tmp_path / "retry-restart.sqlite3"
    with TestClient(create_app(database)) as browser:
        parent = create(browser)
        browser.post(f"/api/sessions/{parent['id']}/finish", json={"outcome": "no_agreement"})
        child = retry(browser, parent).json()
        assert child["retry_of"] == parent["id"]
        assert offer(browser, child).status_code == 200
        completed_child = browser.post(f"/api/sessions/{child['id']}/finish", json={"outcome": "agreement"}).json()
        cookies = dict(browser.cookies)
    with TestClient(create_app(database)) as browser:
        browser.cookies.update(cookies)
        recovered = retry(browser, parent)
        assert recovered.status_code == 200
        assert recovered.json() == completed_child
        assert len(browser.get("/api/sessions").json()["sessions"]) == 2


def test_legacy_parents_and_requests_without_ids_keep_existing_behavior(client):
    parent = create(client)
    assert "_client_action_ids" not in client.app.state.repository.get(parent["id"])
    assert offer(client, parent, action_id=None).json()["turns"] == 1
    assert offer(client, parent, action_id=None).json()["turns"] == 2
    first = client.post(f"/api/sessions/{parent['id']}/retry").json()
    second = client.post(f"/api/sessions/{parent['id']}/retry", json={}).json()
    assert first["id"] != second["id"]
    assert "_client_action_ids" not in client.app.state.repository.get(parent["id"])
    keyed = retry(client, parent).json()
    assert retry(client, parent).json() == keyed
    assert len(client.get("/api/sessions").json()["sessions"]) == 4


def test_ownership_is_checked_before_action_recovery(tmp_path):
    app = create_app(tmp_path / "ownership.sqlite3")
    with TestClient(app) as owner, TestClient(app) as stranger:
        parent = create(owner)
        assert offer(owner, parent, action_id="known-proposal").status_code == 200
        assert retry(owner, parent, "known-retry").status_code == 200
        assert offer(stranger, parent, action_id="known-proposal").status_code == 404
        assert retry(stranger, parent, "known-retry").status_code == 404
        # Conflicting payloads also cannot reveal that an ID has been recorded.
        assert offer(stranger, parent, "accept_all", "known-proposal").status_code == 404
        assert retry(stranger, parent, "known-proposal").status_code == 404
        assert stranger.get("/api/sessions").json() == {"sessions": []}


@pytest.mark.parametrize("action_id", ["", "   ", "x" * 101, 123])
@pytest.mark.parametrize("kind", ["proposal", "retry"])
def test_invalid_action_id_is_rejected_without_changes(client, action_id, kind):
    parent = create(client)
    response = offer(client, parent, action_id=action_id) if kind == "proposal" else retry(client, parent, action_id)
    assert response.status_code == 422
    assert client.get(f"/api/sessions/{parent['id']}").json() == parent
    assert len(client.get("/api/sessions").json()["sessions"]) == 1


def test_action_id_boundary_and_invalid_option_dont_reserve_id(client):
    parent = create(client)
    action_id = "x" * 100
    assert offer(client, parent, "missing-option", action_id).status_code == 422
    accepted = offer(client, parent, action_id=action_id)
    assert accepted.status_code == 200
    assert offer(client, parent, action_id=action_id).json() == accepted.json()


def test_retry_records_and_child_are_atomic_on_database_failure(tmp_path):
    app = create_app(tmp_path / "rollback.sqlite3")
    with TestClient(app, raise_server_exceptions=False) as browser:
        parent = create(browser)
        repository = app.state.repository
        original = repository.get(parent["id"])
        # Parent upsert succeeds; the subsequent child INSERT fails inside the
        # same transaction. No recovery key or child may survive that failure.
        with repository.connect() as connection:
            connection.execute(f"CREATE TRIGGER fail_child BEFORE INSERT ON sessions WHEN NEW.id != '{parent['id']}' BEGIN SELECT RAISE(ABORT, 'injected child failure'); END")
        assert retry(browser, parent).status_code == 500
        assert repository.get(parent["id"]) == original
        assert len(browser.get("/api/sessions").json()["sessions"]) == 1
        with repository.connect() as connection:
            connection.execute("DROP TRIGGER fail_child")
        recovered = retry(browser, parent)
        assert recovered.status_code == 200
        assert retry(browser, parent).json() == recovered.json()
        assert len(browser.get("/api/sessions").json()["sessions"]) == 2


def test_save_many_rolls_back_inserted_child_if_later_serialization_fails(tmp_path):
    repository = Repository(tmp_path / "save-many.sqlite3")
    child = engine.new_session("scope", "deadline", "standard", "demo", "owner")
    parent = engine.new_session("scope", "deadline", "standard", "demo", "owner")
    parent["invalid"] = object()
    with pytest.raises(TypeError):
        repository.save_many([child, parent])
    assert repository.get(child["id"]) is None
    assert repository.get(parent["id"]) is None


@pytest.mark.parametrize("kind", ["proposal", "retry"])
def test_concurrent_duplicate_actions_execute_once(tmp_path, monkeypatch, kind):
    entered, release, second_entered = Event(), Event(), Event()
    counter_lock = Lock()
    counts = {"requests": 0, "executions": 0}
    original_hold = SessionLocks.hold
    operation_name = "submit_proposal" if kind == "proposal" else "new_session"
    original_operation = getattr(engine, operation_name)

    @contextmanager
    def observed_hold(self, session_id):
        with counter_lock:
            counts["requests"] += 1
            if counts["requests"] == 2:
                second_entered.set()
        with original_hold(self, session_id):
            yield

    def slow_operation(*args, **kwargs):
        with counter_lock:
            counts["executions"] += 1
        entered.set()
        assert release.wait(10), "The test did not release the first action"
        return original_operation(*args, **kwargs)

    app = create_app(tmp_path / "concurrent.sqlite3")
    with TestClient(app) as first_browser, TestClient(app) as second_browser:
        parent = create(first_browser)
        second_browser.cookies.update(dict(first_browser.cookies))
        monkeypatch.setattr(SessionLocks, "hold", observed_hold)
        monkeypatch.setattr(engine, operation_name, slow_operation)
        action = offer if kind == "proposal" else retry
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(action, first_browser, parent)
            try:
                assert entered.wait(3)
                second = pool.submit(action, second_browser, parent)
                assert second_entered.wait(3)
                assert not first.done()
                assert not second.done()
            finally:
                release.set()
            first_response, second_response = first.result(timeout=3), second.result(timeout=3)
        assert first_response.status_code == second_response.status_code == 200
        assert first_response.json() == second_response.json()
        assert counts["executions"] == 1
        if kind == "proposal":
            assert first_response.json()["turns"] == 1
            assert len([message for message in first_response.json()["messages"] if message["kind"] == "proposal"]) == 1
        else:
            assert len(first_browser.get("/api/sessions").json()["sessions"]) == 2


def test_retry_recovery_does_not_recheck_unavailable_provider(client, monkeypatch):
    # Recovery only reads an already persisted child, even if its provider's
    # configuration changed after the successful original operation.
    monkeypatch.setattr(live, "available", lambda: True)
    response = client.post("/api/sessions", json={"scenario_id": "scope", "priority": "deadline", "mode": "live"})
    parent = response.json()
    child = retry(client, parent).json()
    monkeypatch.setattr(live, "available", lambda: False)
    assert retry(client, parent).json() == child
    assert retry(client, parent, "new-retry").status_code == 503
