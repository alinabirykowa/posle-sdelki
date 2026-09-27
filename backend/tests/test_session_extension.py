"""Extra turns are explicit, owner-scoped, atomic and never a scenario rewrite."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from backend import ai_conversation, live
from backend.app import create_app
from backend.storage import StorageError


CONFIG = {
    "industry": "it", "topic": "scope", "difficulty": "standard", "tone": "reserved",
    "client_role": "project_lead", "goal": "deadline", "duration_minutes": 5,
    "format": "text", "response_seconds": 0,
}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.setattr(live, "analyze", lambda *args: pytest.fail("Extension must not call AI"))
    monkeypatch.setattr(ai_conversation, "generate_reply", lambda *args: pytest.fail("Extension must not call AI"))
    return create_app(tmp_path / "extension.sqlite3")


@pytest.fixture
def client(app):
    with TestClient(app) as browser:
        yield browser


def start(client, duration=5):
    response = client.post("/api/training/start", json={
        "configuration": CONFIG | {"duration_minutes": duration}, "client_action_id": "start", "mode": "demo",
    })
    assert response.status_code == 200, response.text
    return response.json()


def say(client, session, key):
    return client.post(f"/api/sessions/{session['id']}/messages", json={
        "text": "Что для вас важнее всего?", "client_message_id": key,
    })


def at_limit(client, session):
    for turn in range(session["turns"], session["turn_limit"]):
        response = say(client, session, f"turn-{turn}")
        assert response.status_code == 200, response.text
        session = response.json()
    return session


def extend(client, session, key="extend-1"):
    return client.post(f"/api/sessions/{session['id']}/extend", json={"client_action_id": key})


@pytest.mark.parametrize("duration,base", [(5, 8), (10, 16), (15, 24)])
def test_extension_adds_four_turns_without_rewriting_training_or_dialogue(client, duration, base):
    session = start(client, duration)
    assert session["extra_turns"] == 0
    assert session["turn_limit"] == session["max_turns"] == base
    coached = client.post(f"/api/sessions/{session['id']}/mentor", json={"action": "hint", "client_action_id": "hint"})
    assert coached.status_code == 200
    session = at_limit(client, coached.json()["session"])
    before = deepcopy(client.app.state.repository.get(session["id"]))
    assert say(client, session, "blocked-before-extension").status_code == 409
    response = extend(client, session)
    assert response.status_code == 200, response.text
    result = response.json()["session"]
    assert result["extra_turns"] == 4
    assert result["turn_limit"] == base + 4
    assert result["max_turns"] == base
    for field in ("messages", "turns", "training_config", "context_key", "scenario", "mentor_state", "proposal", "feedback", "discovered_interests"):
        assert result[field] == session[field]
    stored = client.app.state.repository.get(session["id"])
    for field in ("_dialogue_events", "_proposal_events", "_mentor_events", "_client_message_ids"):
        assert stored[field] == before[field]
    assert stored["_extension_events"][0]["from_limit"] == base
    assert stored["_extension_events"][0]["to_limit"] == base + 4
    assert "_extension_events" not in result
    continued = say(client, result, "blocked-before-extension")
    assert continued.status_code == 200, continued.text
    assert continued.json()["turns"] == base + 1


def test_same_extension_is_recovered_at_new_limit_and_new_key_adds_next_block(client):
    session = at_limit(client, start(client))
    first = extend(client, session).json()["session"]
    assert extend(client, session).json()["session"] == first
    assert extend(client, session, "too-soon").status_code == 409
    second_limit = at_limit(client, first)
    recovered = extend(client, session).json()["session"]
    assert recovered == second_limit
    assert recovered["extra_turns"] == 4
    second = extend(client, session, "too-soon")
    assert second.status_code == 200
    assert second.json()["session"]["extra_turns"] == 8
    assert second.json()["session"]["turn_limit"] == 16
    assert len(client.app.state.repository.get(session["id"])["_extension_events"]) == 2


def test_extension_is_denied_before_limit_without_mutation(client):
    session = start(client)
    before = client.app.state.repository.get(session["id"])
    assert extend(client, session).status_code == 409
    assert client.app.state.repository.get(session["id"]) == before


def test_completed_attempt_allows_only_recovery_and_retry_starts_with_original_limit(client):
    session = at_limit(client, start(client))
    assert extend(client, session).status_code == 200
    finished = client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "no_agreement"})
    assert finished.status_code == 200
    before = client.app.state.repository.get(session["id"])
    assert extend(client, session, "new-extension").status_code == 409
    recovered = extend(client, session)
    assert recovered.status_code == 200
    assert recovered.json()["session"]["status"] == "completed"
    assert recovered.json()["session"]["extra_turns"] == 4
    assert client.app.state.repository.get(session["id"]) == before
    retry = client.post(f"/api/sessions/{session['id']}/retry", json={"client_action_id": "retry"})
    assert retry.status_code == 200
    child = retry.json()
    assert child["extra_turns"] == 0
    assert child["turn_limit"] == child["max_turns"] == 8
    assert child["context_key"] == session["context_key"]
    assert child["scenario"] == session["scenario"]


def test_legacy_attempt_uses_original_30_turn_fallback_without_rewriting_snapshot(client):
    response = client.post("/api/sessions", json={"scenario_id": "scope", "priority": "deadline", "difficulty": "standard", "mode": "demo"})
    assert response.status_code == 200
    session = response.json()
    repo = client.app.state.repository
    old = repo.get(session["id"])
    old.pop("extra_turns")
    repo.save(old)
    read = client.get(f"/api/sessions/{session['id']}").json()
    assert read["turn_limit"] == 30
    assert read["extra_turns"] == 0
    assert "extra_turns" not in repo.get(session["id"])
    session = at_limit(client, read)
    extended = extend(client, session).json()["session"]
    assert extended["turn_limit"] == 34
    assert "max_turns" not in extended
    assert "training_config" not in extended
    assert extended["scenario"] == session["scenario"]


def test_proposal_uses_extended_limit_and_duplicate_keys_do_not_cross_actions(client):
    session = at_limit(client, start(client))
    assert extend(client, session).status_code == 200
    proposal = {"option_id": "prioritize_swap", "client_action_id": "extend-1"}
    assert client.post(f"/api/sessions/{session['id']}/proposal", json=proposal).status_code == 409
    proposal["client_action_id"] = "proposal"
    accepted = client.post(f"/api/sessions/{session['id']}/proposal", json=proposal)
    assert accepted.status_code == 200
    assert accepted.json()["turns"] == 9
    assert extend(client, session, "proposal").status_code == 409


def test_extension_is_owner_protected(app):
    with TestClient(app) as owner, TestClient(app) as stranger:
        session = at_limit(owner, start(owner))
        assert extend(stranger, session).status_code == 404
        assert extend(owner, session).status_code == 200
        assert extend(stranger, session).status_code == 404


def test_failed_save_leaves_no_extra_turn_or_reserved_key(client, monkeypatch):
    session = at_limit(client, start(client))
    repo = client.app.state.repository
    before = repo.get(session["id"])
    original = repo.save

    def fail(value):
        raise StorageError("Test storage unavailable")

    monkeypatch.setattr(repo, "save", fail)
    assert extend(client, session).status_code == 503
    assert repo.get(session["id"]) == before
    monkeypatch.setattr(repo, "save", original)
    assert extend(client, session).json()["session"]["extra_turns"] == 4


def test_lost_acknowledgement_recovers_one_extension(client, monkeypatch):
    session = at_limit(client, start(client))
    repo = client.app.state.repository
    original = repo.save

    def save_then_fail(value):
        original(value)
        raise StorageError("Test acknowledgement lost")

    monkeypatch.setattr(repo, "save", save_then_fail)
    assert extend(client, session).status_code == 503
    recovered = extend(client, session)
    assert recovered.status_code == 200
    assert recovered.json()["session"]["extra_turns"] == 4
    assert len(repo.get(session["id"])["_extension_events"]) == 1


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_requests_grant_only_one_block(app, same_key):
    barrier = Barrier(2)
    with TestClient(app) as first, TestClient(app) as second:
        session = at_limit(first, start(first))
        second.cookies.update(dict(first.cookies))

        def request(pair):
            client, key = pair
            barrier.wait(timeout=5)
            return extend(client, session, key)

        with ThreadPoolExecutor(max_workers=2) as workers:
            responses = list(workers.map(request, [(first, "one"), (second, "one" if same_key else "two")]))
    assert sorted(response.status_code for response in responses) == ([200, 200] if same_key else [200, 409])
    stored = app.state.repository.get(session["id"])
    assert stored["extra_turns"] == 4
    assert len(stored["_extension_events"]) == 1


@pytest.mark.parametrize("body", [{}, {"client_action_id": " "}, {"client_action_id": "x" * 101}, {"client_action_id": "one", "turns": 100}])
def test_invalid_extension_body_does_not_change_attempt(client, body):
    session = at_limit(client, start(client))
    before = client.app.state.repository.get(session["id"])
    assert client.post(f"/api/sessions/{session['id']}/extend", json=body).status_code == 422
    assert client.app.state.repository.get(session["id"]) == before
