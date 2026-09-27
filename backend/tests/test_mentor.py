"""Separate, evidence-grounded coaching with honest monotonic assistance data."""

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
    "client_role": "project_lead", "goal": "deadline", "duration_minutes": 10,
    "format": "text", "response_seconds": 0,
}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.setattr(live, "analyze", lambda *args: pytest.fail("Mentor must not call AI"))
    monkeypatch.setattr(ai_conversation, "generate_reply", lambda *args: pytest.fail("Mentor must not call AI"))
    return create_app(tmp_path / "mentor.sqlite3")


@pytest.fixture
def client(app):
    with TestClient(app) as browser:
        yield browser


def start(client, action="start", **changes):
    response = client.post("/api/training/start", json={
        "configuration": CONFIG | changes, "client_action_id": action, "mode": "demo",
    })
    assert response.status_code == 200, response.text
    return response.json()


def coach(client, session, action="hint", key="coach-1", **body):
    return client.post(f"/api/sessions/{session['id']}/mentor", json={
        "action": action, "client_action_id": key, **body,
    })


def mode(client, session, value, key="mode-1"):
    return client.post(f"/api/sessions/{session['id']}/mentor-mode", json={
        "mode": value, "client_action_id": key,
    })


def say(client, session, text="Что для вас важнее всего?", key="message-1"):
    response = client.post(f"/api/sessions/{session['id']}/messages", json={"text": text, "client_message_id": key})
    assert response.status_code == 200, response.text
    return response.json()


def last_user(session):
    return next(item for item in reversed(session["messages"]) if item["role"] == "user")


def test_new_attempt_tracks_assistance_from_start_without_marking_it_used(client):
    session = start(client)
    assert session["mentor_state"] == {
        "mode": "guided", "tracking_started": True, "tracked_from_start": True,
        "used": False, "counts": {"hint": 0, "example": 0, "review": 0}, "last_advice": None,
    }


def test_hint_is_separate_does_not_spend_turn_or_change_dialogue(client):
    session = start(client)
    response = coach(client, session)
    assert response.status_code == 200, response.text
    result = response.json()
    for field in ("messages", "turns", "scenario", "proposal", "discovered_interests", "feedback", "status"):
        assert result["session"][field] == session[field]
    state = result["session"]["mentor_state"]
    assert state["used"] is True
    assert state["counts"] == {"hint": 1, "example": 0, "review": 0}
    assert state["last_advice"] == result["advice"]
    assert result["advice"]["method"] == "rules"
    assert result["advice"]["context_message_id"] == session["messages"][-1]["id"]
    stored = client.app.state.repository.get(session["id"])
    assert len(stored["_mentor_events"]) == 1
    assert stored["_dialogue_events"] == []
    assert "_mentor_events" not in result["session"]


@pytest.mark.parametrize("action", ["hint", "example"])
def test_advice_does_not_reveal_undisclosed_priority(client, action):
    first = start(client, action="first", goal="deadline")
    second = start(client, action="second", goal="full_scope")
    one = coach(client, first, action).json()["advice"]
    two = coach(client, second, action).json()["advice"]
    for field in ("title", "text", "example", "choice_id"):
        assert one.get(field) == two.get(field)
    assert first["scenario"]["client_interest"] not in str(one)
    assert second["scenario"]["client_interest"] not in str(two)


def test_example_counts_usage_without_sending_text_and_rejects_stale_choice(client):
    session = start(client)
    choice = session["reply_choices"][2]
    response = coach(client, session, "example", choice_id=choice["id"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["advice"]["example"] == choice["text"]
    assert result["session"]["messages"] == session["messages"]
    assert result["session"]["mentor_state"]["counts"]["example"] == 1
    assert coach(client, session, "example", key="bad", choice_id="unknown").status_code == 409
    assert client.app.state.repository.get(session["id"])["mentor_state"]["counts"]["example"] == 1


def test_independent_mode_disables_new_help_and_does_not_erase_usage(client):
    session = start(client)
    independent = mode(client, session, "independent").json()["session"]
    assert independent["mentor_state"]["used"] is False
    assert independent["reply_choices"] == independent["suggestions"] == []
    assert independent["conversation_hint"] == ""
    assert coach(client, session).status_code == 409
    assert mode(client, session, "guided", "mode-2").status_code == 200
    assisted = coach(client, session).json()
    switched = mode(client, session, "independent", "mode-3").json()["session"]
    assert switched["mentor_state"]["used"] is True
    assert switched["mentor_state"]["counts"] == assisted["session"]["mentor_state"]["counts"]
    assert coach(client, session, key="new-hint").status_code == 409
    # Recovery of an earlier successful action is not a new use of the mentor.
    recovered = coach(client, session).json()
    assert recovered["advice"] == assisted["advice"]
    assert recovered["session"]["mentor_state"]["mode"] == "independent"


def test_generic_example_tracks_visible_stage_instead_of_repeating_discovery(client):
    session = start(client)
    first = coach(client, session, "example").json()["advice"]
    assert first["choice_id"] == "explore-priority"
    say(client, session)
    explanation = coach(client, session, "example", "example-2").json()["advice"]
    assert explanation["choice_id"] == "respond-reasoning"
    rejected = client.post(f"/api/sessions/{session['id']}/proposal", json={"option_id": "extend_deadline"}).json()
    assert rejected["proposal"]["client_status"] == "rejected"
    refusal = coach(client, session, "example", "example-3").json()["advice"]
    assert refusal["choice_id"] == "explore-rejection"
    accepted = client.post(f"/api/sessions/{session['id']}/proposal", json={"option_id": "prioritize_swap"}).json()
    assert accepted["proposal"]["client_status"] == "accepted"
    summary = coach(client, session, "example", "example-4").json()["advice"]
    assert summary["choice_id"] == "respond-summary"


def test_existing_untracked_attempt_is_never_retroactively_independent(client):
    session = start(client)
    repo = client.app.state.repository
    legacy = repo.get(session["id"])
    del legacy["mentor_state"]
    del legacy["_mentor_events"]
    repo.save(legacy)
    public = client.get(f"/api/sessions/{session['id']}").json()
    assert public["mentor_state"]["tracking_started"] is False
    assert public["mentor_state"]["tracked_from_start"] is False
    assert public["mentor_state"]["mode"] == "guided"
    assert "mentor_state" not in repo.get(session["id"])
    changed = mode(client, session, "independent").json()["session"]
    assert changed["mentor_state"]["tracking_started"] is True
    assert changed["mentor_state"]["tracked_from_start"] is False
    assert changed["mentor_state"]["used"] is False
    mode(client, session, "guided", "mode-2")
    assisted = coach(client, session).json()["session"]
    assert assisted["mentor_state"]["used"] is True
    assert assisted["mentor_state"]["tracked_from_start"] is False


def test_review_credits_actual_argument_in_proposal_using_exact_saved_evidence(client):
    session = start(client)
    text = "Предлагаю выбрать только необходимые к запуску задачи, чтобы сохранить дату и не обещать лишнего. Остальные изменения обсудим отдельно."
    session = say(client, session, text)
    target = last_user(session)
    result = coach(client, session, "review", message_id=target["id"]).json()
    advice = result["advice"]
    assert advice["observation"] == "argument"
    assert advice["evidence"]["message_id"] == target["id"]
    assert advice["evidence"]["quote"] in text
    assert "чтобы сохранить дату" in advice["evidence"]["quote"]
    assert result["session"]["turns"] == session["turns"]
    assert result["session"]["mentor_state"]["counts"]["review"] == 1


@pytest.mark.parametrize("text", [
    "Клиент сказал: «Сократим объём, чтобы сохранить дату запуска».",
    "Я не буду объяснять, почему цена ниже, потому что так захотелось.",
    "Сократим объём, чтобы сохранить дату запуска — это не аргумент.",
    "Предлагаю оставить только необходимые задачи.",
])
def test_review_does_not_invent_argument_from_quotes_denial_or_bare_proposal(client, text):
    session = say(client, start(client), text)
    advice = coach(client, session, "review", message_id=last_user(session)["id"]).json()["advice"]
    assert advice["observation"] == "not_enough_evidence"
    assert "evidence" not in advice
    assert "не означает, что реплика неправильная" in advice["text"]


def test_review_only_accepts_latest_freeform_user_message(client):
    session = start(client)
    assert coach(client, session, "review", message_id=session["messages"][-1]["id"]).status_code == 422
    first = say(client, session)
    earlier = last_user(first)["id"]
    current = say(client, session, "Какой следующий шаг обсудим?", "message-2")
    assert coach(client, session, "review", message_id=earlier).status_code == 422
    reviewed = coach(client, session, "review", message_id=last_user(current)["id"])
    assert reviewed.status_code == 200
    proposal = client.post(f"/api/sessions/{session['id']}/proposal", json={"option_id": "prioritize_swap"}).json()
    proposal_id = next(item["id"] for item in reversed(proposal["messages"]) if item.get("kind") == "proposal")
    assert coach(client, session, "review", key="card", message_id=proposal_id).status_code == 422


def test_advice_and_mode_keys_are_idempotent_and_conflict_across_actions(client):
    session = start(client)
    result = coach(client, session).json()
    assert coach(client, session).json() == result
    assert coach(client, session, "example").status_code == 409
    assert mode(client, session, "independent", "coach-1").status_code == 409
    assert client.post(f"/api/sessions/{session['id']}/proposal", json={"option_id": "prioritize_swap", "client_action_id": "coach-1"}).status_code == 409
    changed = mode(client, session, "independent").json()
    assert mode(client, session, "independent").json() == changed
    assert mode(client, session, "guided").status_code == 409
    assert len(client.app.state.repository.get(session["id"])["_mentor_events"]) == 2


def test_advice_keeps_original_context_for_ui_after_next_turn(client):
    session = start(client)
    original = coach(client, session).json()["advice"]
    latest = say(client, session)
    recovered = coach(client, session).json()
    assert recovered["advice"] == original
    assert original["context_message_id"] != latest["messages"][-1]["id"]
    assert recovered["session"]["mentor_state"]["last_advice"] == original


def test_completed_attempt_allows_only_recovery_and_retry_starts_clean(client):
    session = start(client)
    advice = coach(client, session).json()["advice"]
    completed = client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "no_agreement"}).json()
    assert coach(client, session, key="new").status_code == 409
    assert mode(client, session, "independent").status_code == 409
    assert coach(client, session).json() == {"session": completed, "advice": advice}
    retry = client.post(f"/api/sessions/{session['id']}/retry", json={"client_action_id": "retry"}).json()
    assert retry["mentor_state"] == start(client, action="fresh")["mentor_state"]
    assert retry["scenario"] == session["scenario"]


def test_mentor_is_owner_protected(app):
    with TestClient(app) as owner, TestClient(app) as stranger:
        session = start(owner)
        assert coach(owner, session).status_code == 200
        assert coach(stranger, session).status_code == 404
        assert mode(stranger, session, "independent").status_code == 404


def test_failed_save_does_not_leave_advice_or_usage(client, monkeypatch):
    session = start(client)
    repo = client.app.state.repository
    before = deepcopy(repo.get(session["id"]))
    original = repo.save

    def fail(value):
        raise StorageError("Test storage unavailable")

    monkeypatch.setattr(repo, "save", fail)
    assert coach(client, session).status_code == 503
    assert repo.get(session["id"]) == before
    monkeypatch.setattr(repo, "save", original)
    result = coach(client, session).json()
    assert result["session"]["mentor_state"]["counts"]["hint"] == 1


def test_lost_save_ack_recovers_exact_advice_once(client, monkeypatch):
    session = start(client)
    repo = client.app.state.repository
    original = repo.save

    def save_then_fail(value):
        original(value)
        raise StorageError("Test acknowledgement lost")

    monkeypatch.setattr(repo, "save", save_then_fail)
    assert coach(client, session).status_code == 503
    stored = repo.get(session["id"])
    result = coach(client, session)
    assert result.status_code == 200
    assert result.json()["advice"] == stored["mentor_state"]["last_advice"]
    assert result.json()["session"]["mentor_state"]["counts"]["hint"] == 1


def test_concurrent_duplicate_hint_is_saved_once(app):
    barrier = Barrier(2)
    with TestClient(app) as first, TestClient(app) as second:
        session = start(first)
        second.cookies.update(dict(first.cookies))

        def request(client):
            barrier.wait(timeout=5)
            return coach(client, session).json()

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(request, [first, second]))
    assert results[0] == results[1]
    assert results[0]["session"]["mentor_state"]["counts"]["hint"] == 1
    assert len(app.state.repository.get(session["id"])["_mentor_events"]) == 1


@pytest.mark.parametrize("patch", [
    {"action": "unknown"}, {"client_action_id": " "}, {"message_id": "not-for-hint"},
    {"choice_id": "not-for-hint"}, {"action": "review"}, {"unexpected": True},
])
def test_invalid_requests_leave_attempt_unchanged(client, patch):
    session = start(client)
    before = client.app.state.repository.get(session["id"])
    response = client.post(f"/api/sessions/{session['id']}/mentor", json={"action": "hint", "client_action_id": "action", **patch})
    assert response.status_code == 422
    assert client.app.state.repository.get(session["id"]) == before
