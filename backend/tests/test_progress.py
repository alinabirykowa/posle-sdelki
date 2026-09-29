"""Personal progress reports observations, never a score or inferred duration."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import pytest

from backend import engine, live
from backend.app import COOKIE_NAME, create_app
from backend.postgres_repository import PostgresRepository
from backend.progress import build_progress
from backend.training import TrainingConfig, build_preview


CONFIG = {
    "industry": "it", "topic": "scope", "goal": "deadline", "difficulty": "hard",
    "tone": "collaborative", "client_role": "project_lead", "duration_minutes": 15,
    "format": "text", "response_seconds": 0,
}
QUESTION = "Что для вас важнее всего в этом проекте?"


def say(session, text):
    reply = engine.process_message(session, text, f"message-{session['turns']}")
    engine.add_message(session, "assistant", reply)


def stamp(session, order):
    date = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=order)
    session["created_at"] = date.isoformat()
    for index, message in enumerate(session["messages"]):
        message["created_at"] = (date + timedelta(seconds=index)).isoformat()
    if session["status"] == "completed":
        session["completed_at"] = session["messages"][-1]["created_at"]
    return session


def attempt(order=0, *, owner="one", complete=True, text=QUESTION, refusal=False,
            after_refusal=None, mode="demo", assistance="independent", used=False, config=None):
    preview = build_preview(TrainingConfig(**(CONFIG | (config or {}))))
    session = engine.new_session(
        "scope", "deadline", "hard", mode, owner,
        scenario_snapshot=preview["scenario"], training_config=preview["configuration"],
        context_key=preview["context_key"], max_turns=preview["max_turns"],
    )
    if assistance == "unknown":
        del session["mentor_state"]
    else:
        session["mentor_state"].update({"mode": assistance, "used": used})
        if used:
            session["mentor_state"]["counts"]["hint"] = 1
    if text:
        say(session, text)
    if refusal:
        reply = engine.submit_proposal(session, "extend_deadline")
        engine.add_message(session, "assistant", reply, "proposal_response")
    if after_refusal:
        say(session, after_refusal)
    if complete:
        engine.finish(session, "no_agreement")
    return stamp(session, order)


def skill(report, key):
    return next(item for item in report["skills"] if item["id"] == key)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "available", lambda: False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    return create_app(tmp_path / "progress.sqlite3")


def test_empty_history_is_an_invitation_not_a_zero_skill_grade(app):
    with TestClient(app) as client:
        response = client.get("/api/progress")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    report = response.json()
    assert report["scope"] == "all_owner_history"
    assert report["summary"] == {
        "total": 0, "completed": 0, "active": 0, "conversation_completed": 0,
        "unique_situations": 0, "legacy_completed": 0,
        "assistance": {"guided": 0, "independent": 0, "unknown": 0},
    }
    assert report["recent_practice"] == []
    assert report["latest_completed"] is None
    assert report["comparison"]["eligible"] is False
    assert report["recommendation"]["kind"] == "start"
    assert all(row["status"] == "not_practiced" and row["evidence"] == [] for row in report["skills"])
    assert report["negotiator_route"]["active_stage"] == "discover"
    assert [stage["status"] for stage in report["negotiator_route"]["stages"]] == [
        "available", "locked", "locked", "locked",
    ]


def test_negotiator_route_unlocks_only_with_saved_skill_evidence():
    first = attempt(0)
    report = build_progress([first])
    route = report["negotiator_route"]
    assert route["completed_stages"] == 1
    assert route["active_stage"] == "explain"
    assert route["stages"][0]["evidence"][0]["quote"] == QUESTION
    assert route["stages"][1]["status"] == "available"
    assert route["stages"][2]["status"] == "locked"

    early_argument = attempt(
        1,
        text="Предлагаю оставить обязательные задачи к запуску, потому что так мы сохраним дату проекта.",
    )
    locked_route = build_progress([early_argument])["negotiator_route"]
    assert locked_route["stages"][1]["status"] == "locked"
    assert locked_route["stages"][1]["evidence"] == []


def test_independent_route_stage_needs_all_three_skills_in_one_unguided_attempt():
    preview = build_preview(TrainingConfig(**CONFIG))
    session = engine.new_session(
        "scope", "deadline", "hard", "demo", "one",
        scenario_snapshot=preview["scenario"], training_config=preview["configuration"],
        context_key=preview["context_key"], max_turns=preview["max_turns"],
    )
    session["mentor_state"].update({"mode": "independent", "used": False})
    say(session, QUESTION)
    say(session, "Предлагаю оставить обязательные задачи к запуску, потому что так мы сохраним дату проекта.")
    reply = engine.submit_proposal(session, "extend_deadline")
    engine.add_message(session, "assistant", reply, "proposal_response")
    say(session, "Что в моём предложении вам не подходит?")
    engine.finish(session, "no_agreement")
    route = build_progress([stamp(session, 0)])["negotiator_route"]
    assert route["completed_stages"] == 4
    assert route["active_stage"] is None
    assert all(stage["status"] == "complete" for stage in route["stages"])


def test_all_history_above_thirty_is_owner_scoped_and_quotes_stay_private(app):
    with TestClient(app) as first, TestClient(app) as stranger:
        first.get("/api/health")
        stranger.get("/api/health")
        owner = first.cookies[COOKIE_NAME]
        records = [attempt(index, owner=owner) for index in range(40)]
        foreign = attempt(41, owner=stranger.cookies[COOKIE_NAME], text="Что для вас важно в чужом секретном проекте?")
        app.state.repository.save_many([*records, foreign])
        assert len(app.state.repository.list(owner)) == 30
        report = first.get("/api/progress", params={"owner": stranger.cookies[COOKIE_NAME]}).json()
        assert report["summary"]["completed"] == 40
        assert report["summary"]["assistance"]["independent"] == 40
        assert report["observation_scope"]["attempts"] == 40
        assert skill(report, "clarified_need")["observed_count"] == 40
        assert len(report["recent_practice"]) == 6
        assert foreign["id"] not in json.dumps(report)
        assert report["latest_completed"]["session_id"] == records[-1]["id"]
        assert stranger.get("/api/progress").json()["summary"]["total"] == 1
        for row in report["skills"]:
            for evidence in row["evidence"]:
                source = next(item for item in records if item["id"] == evidence["session_id"])
                message = next(item for item in source["messages"] if item["id"] == evidence["message_id"])
                assert evidence["quote"] in message["text"] and message["role"] == "user"
                assert evidence["assistance"] == "independent"


def test_account_progress_never_adopts_guest_history_or_another_account(app):
    with TestClient(app) as first, TestClient(app) as second:
        first.get("/api/progress")
        guest_owner = first.cookies[COOKIE_NAME]
        app.state.repository.save(attempt(owner=guest_owner))
        users = []
        for client, name in ((first, "first"), (second, "second")):
            response = client.post("/api/auth/register", json={"username": name, "display_name": name, "password": "test-only-long-pass"})
            assert response.status_code == 201, response.text
            users.append(response.json()["user"])
        assert first.get("/api/progress").json()["summary"]["total"] == 0
        assert first.get("/api/progress").json()["latest_completed"] is None
        personal = attempt(owner="account:" + users[0]["id"])
        app.state.repository.save(personal)
        assert first.get("/api/progress").json()["summary"]["total"] == 1
        assert first.get("/api/progress").json()["latest_completed"]["session_id"] == personal["id"]
        foreign_report = second.get("/api/progress", params={"owner": "account:" + users[0]["id"]}).json()
        assert foreign_report["summary"]["total"] == 0
        assert foreign_report["latest_completed"] is None


def test_latest_completed_orders_by_completion_not_creation_or_activity():
    started_first, started_later = attempt(0), attempt(1)
    started_first["completed_at"] = "2026-09-20T20:00:00+03:00"
    started_later["completed_at"] = "2026-09-20T16:00:00Z"
    # Neither later activity on another record nor an active attempt is a finish.
    started_later["messages"][-1]["created_at"] = "2026-10-01T00:00:00Z"
    active = attempt(30, complete=False)
    report = build_progress([started_later, active, started_first])
    assert report["latest_completed"]["session_id"] == started_first["id"]
    assert report["latest_completed"]["completed_at"] == started_first["completed_at"]
    assert build_progress([active])["latest_completed"] is None


def test_latest_completed_survives_more_than_thirty_newer_active_attempts(app):
    with TestClient(app) as client:
        client.get("/api/health")
        owner = client.cookies[COOKIE_NAME]
        finished = attempt(0, owner=owner)
        active = [attempt(index, owner=owner, complete=False) for index in range(1, 35)]
        app.state.repository.save_many([finished, *active])
        assert finished["id"] not in {item["id"] for item in app.state.repository.list(owner)}
        report = client.get("/api/progress").json()
        assert len(report["recent_practice"]) == 6
        assert finished["id"] not in {item["session_id"] for item in report["recent_practice"]}
        assert report["latest_completed"]["session_id"] == finished["id"]


def test_latest_completed_includes_legacy_even_when_conversation_stats_stay_separate():
    modern = attempt(0)
    legacy = engine.new_session("scope", "deadline", "hard", "demo", "one")
    engine.finish(legacy, "no_agreement")
    stamp(legacy, 1)
    report = build_progress([modern, legacy])
    assert report["latest_completed"]["session_id"] == legacy["id"]
    assert report["latest_completed"]["practice_model"] == "financial"
    assert report["latest_completed"]["status"] == "completed"
    assert report["summary"]["conversation_completed"] == 1
    assert report["observation_scope"]["attempts"] == 1
    assert report["comparison"]["current"]["session_id"] == modern["id"]
    # Historical records without a finish timestamp retain the existing fallback.
    del legacy["completed_at"]
    assert build_progress([legacy, modern])["latest_completed"]["session_id"] == legacy["id"]


@pytest.mark.parametrize("refusal,after,status", [
    (False, None, "not_practiced"),
    (True, None, "not_practiced"),
    (True, "Понятно.", "not_observed"),
    (True, "Что в моём предложении вам не подходит?", "observed"),
])
def test_response_requires_a_real_opportunity_after_refusal(refusal, after, status):
    session = attempt(refusal=refusal, after_refusal=after)
    saved_behavior = next(item for item in session["feedback"]["behaviors"] if item["id"] == "responded_to_objection")
    assert saved_behavior["eligible"] is (status != "not_practiced")
    report = build_progress([session])
    row = skill(report, "responded_to_objection")
    assert row["status"] == status
    assert row["eligible_count"] == (status != "not_practiced")
    assert bool(row["evidence"]) == (status == "observed")
    refusal_advice = "После отказа уточните причину или объясните, как новый вариант учитывает ограничение клиента."
    assert (refusal_advice in session["feedback"]["improvements"]) is (status == "not_observed")
    if status == "not_practiced":
        assert "не проверялась" in saved_behavior["explanation"]
        assert session["feedback"]["next_step"] != refusal_advice


def test_a_reply_after_another_proposal_does_not_create_a_refusal_opportunity():
    session = attempt(refusal=True, complete=False)
    reply = engine.submit_proposal(session, "prioritize_swap")
    engine.add_message(session, "assistant", reply, "proposal_response")
    say(session, "Что в моём предложении вам не подходит?")
    engine.finish(session, "agreement")
    assert skill(build_progress([session]), "responded_to_objection")["status"] == "not_practiced"
    assert next(item for item in session["feedback"]["behaviors"] if item["id"] == "responded_to_objection")["eligible"] is False


def test_new_feedback_explicitly_marks_unpracticed_and_practiced_behaviors():
    silent = attempt(text=None)
    assert all(item["eligible"] is False for item in silent["feedback"]["behaviors"])
    speaking = attempt(text="Понятно.")
    behaviors = {item["id"]: item for item in speaking["feedback"]["behaviors"]}
    assert behaviors["clarified_need"]["eligible"] is True
    assert behaviors["justified_proposal"]["eligible"] is True
    assert behaviors["responded_to_objection"]["eligible"] is False
    assert all(item["status"] == "not_observed" for item in behaviors.values())


@pytest.mark.parametrize("field,value", [("max_turns", 30), ("extra_turns", 4), ("extra_turns", 8)])
def test_different_practice_allowances_are_not_comparable(field, value):
    standard, extended = attempt(0), attempt(1)
    extended[field] = value
    report = build_progress([standard, extended])
    assert report["comparison"]["eligible"] is False
    assert report["observation_scope"]["attempts"] == 1


def test_different_route_stage_goals_are_not_compared_as_the_same_learning_attempt():
    previous, current = attempt(0), attempt(1)
    previous["route_stage"] = "discover"
    current["route_stage"] = "explain"
    report = build_progress([previous, current])
    assert report["comparison"]["eligible"] is False
    assert report["observation_scope"]["attempts"] == 1


def test_missing_extension_means_zero_and_base_limit_defaults_to_thirty():
    first, second = attempt(0), attempt(1)
    first.pop("max_turns")
    first.pop("extra_turns", None)
    second.update({"max_turns": 30, "extra_turns": 0})
    assert build_progress([first, second])["comparison"]["eligible"] is True


@pytest.mark.parametrize("changes", [
    {"config": {"industry": "consulting"}}, {"mode": "live"},
    {"assistance": "guided"}, {"assistance": "independent", "used": True},
    {"assistance": "unknown"},
])
def test_comparisons_do_not_mix_context_mode_or_help(changes):
    previous = attempt(0, **changes)
    current = attempt(1)
    report = build_progress([previous, current])
    assert report["comparison"]["eligible"] is False
    assert report["observation_scope"]["attempts"] == 1
    assert skill(report, "clarified_need")["observed_count"] == 1


def test_comparable_observations_are_not_scores_and_do_not_skip_empty_previous():
    first, previous, current = attempt(0), attempt(1), attempt(2)
    report = build_progress([current, first, previous])
    assert report["comparison"]["eligible"] is True
    assert report["comparison"]["previous"]["session_id"] == previous["id"]
    assert report["comparison"]["current"]["session_id"] == current["id"]
    previous["feedback"]["behaviors"] = []
    report = build_progress([first, previous, current])
    assert report["comparison"]["eligible"] is False
    assert report["comparison"]["previous"] is None
    assert report["observation_scope"]["attempts"] == 3


def test_comparison_shows_each_cited_phrase_with_the_client_reaction():
    previous, current = attempt(0), attempt(1)
    comparison = build_progress([previous, current])["comparison"]
    assert comparison["eligible"] is True
    before = comparison["previous"]["skills"][0]["evidence"][0]
    after = comparison["current"]["skills"][0]["evidence"][0]
    assert before["quote"] == after["quote"] == QUESTION
    assert before["delivery_tone"] == after["delivery_tone"] == "constructive"
    assert before["client_reply"] and after["client_reply"]


def test_old_help_metadata_and_toggling_cannot_be_called_independent():
    old = attempt(0)
    old["mentor_state"].update({"tracked_from_start": False, "tracking_started": True})
    used = attempt(1, assistance="independent", used=True)
    guided = attempt(2, assistance="guided", used=False)
    report = build_progress([old, used, guided])
    assert report["summary"]["assistance"] == {"guided": 2, "independent": 0, "unknown": 1}
    assert report["comparison"]["eligible"] is False
    assert report["observation_scope"]["attempts"] == 1
    latest = {item["session_id"]: item for item in report["recent_practice"]}
    assert latest[old["id"]]["mentor_used"] is None
    assert latest[used["id"]]["mentor_used"] is True
    assert latest[guided["id"]]["mentor_used"] is False


@pytest.mark.parametrize("difference", ["advice_used", "reply_mode", "engine_version"])
def test_comparisons_keep_advice_use_ai_response_mode_and_engine_version_separate(difference):
    older, latest = attempt(0, assistance="guided"), attempt(1, assistance="guided")
    if difference == "advice_used":
        older["mentor_state"]["used"] = True
    elif difference == "reply_mode":
        older["mode"] = latest["mode"] = "live"
        older["reply_mode"] = "generated"
    else:
        older["_engine_version"] = 1
    report = build_progress([older, latest])
    assert report["comparison"]["eligible"] is False
    assert report["observation_scope"]["attempts"] == 1


@pytest.mark.parametrize("mutation", ["missing", "invented", "assistant", "duplicate_id"])
def test_progress_cannot_publish_unverified_behavior_evidence(mutation):
    session = attempt()
    row = next(item for item in session["feedback"]["behaviors"] if item["id"] == "clarified_need")
    evidence = row["evidence"][0]
    if mutation == "missing":
        evidence["message_id"] = "missing"
    elif mutation == "invented":
        evidence["quote"] = "Полностью выдуманное утверждение."
    elif mutation == "assistant":
        source = next(item for item in session["messages"] if item["role"] == "assistant")
        evidence.update({"message_id": source["id"], "quote": source["text"]})
    else:
        source = next(item for item in session["messages"] if item["id"] == evidence["message_id"])
        session["messages"].append(deepcopy(source))
    result = skill(build_progress([session]), "clarified_need")
    assert result["status"] != "observed"
    assert result["evidence"] == []


def test_legacy_is_history_only_and_does_not_displace_conversation_timeline():
    modern = attempt(0)
    legacy = []
    for index in range(8):
        session = engine.new_session("scope", "deadline", "hard", "demo", "one")
        say(session, QUESTION)
        engine.finish(session, "no_agreement")
        legacy.append(stamp(session, index + 1))
    report = build_progress([modern, *legacy])
    assert report["summary"]["completed"] == 9
    assert report["summary"]["legacy_completed"] == 8
    assert report["summary"]["conversation_completed"] == 1
    assert report["summary"]["unique_situations"] == 1
    assert report["summary"]["assistance"]["independent"] == 1
    assert [item["session_id"] for item in report["recent_practice"]] == [modern["id"]]
    assert report["observation_scope"]["attempts"] == 1


def test_missing_context_cannot_invent_a_distinct_situation_or_comparison():
    first, second = attempt(0), attempt(1)
    for session in (first, second):
        session.pop("context_key")
    report = build_progress([first, second])
    assert report["summary"]["completed"] == 2
    assert report["summary"]["unique_situations"] == 0
    assert report["comparison"]["eligible"] is False
    assert report["observation_scope"]["attempts"] == 1


def test_recommendations_continue_then_retry_and_respect_ai_availability():
    done = attempt(0)
    active = attempt(1, complete=False)
    unavailable = attempt(2, complete=False, mode="live")
    report = build_progress([done, active, unavailable])
    assert report["recommendation"]["kind"] == "continue"
    assert report["recommendation"]["session_id"] == active["id"]
    report = build_progress([done, unavailable], ai_available=True)
    assert report["recommendation"]["session_id"] == unavailable["id"]
    report = build_progress([done, unavailable])
    assert report["recommendation"]["kind"] == "retry"
    assert report["recommendation"]["session_id"] == done["id"]
    assert build_progress([attempt(text="Понятно.")])["recommendation"]["kind"] == "start"


def test_recommended_catalog_retry_uses_frozen_snapshot_after_archive(app):
    with TestClient(app) as client:
        client.get("/api/health")
        done = attempt(owner=client.cookies[COOKIE_NAME])
        # No active catalogue row exists; completed attempts still own a snapshot.
        done.update({"catalog_case_id": "archived-or-removed", "catalog_revision": 7})
        app.state.repository.save(done)
        recommended = client.get("/api/progress").json()["recommendation"]
        assert recommended["kind"] == "retry"
        response = client.post(f"/api/sessions/{recommended['session_id']}/retry", json={"client_action_id": "retry-frozen"})
        assert response.status_code == 200, response.text
        assert response.json()["scenario"] == done["scenario"]
        assert response.json()["mentor_state"]["tracked_from_start"] is True


def test_progress_exposes_neither_internal_events_nor_estimated_time_or_ratings():
    session = attempt()
    before = deepcopy(session)
    report = build_progress([session])
    assert session == before
    forbidden = {"minutes", "duration", "duration_minutes", "elapsed", "score", "rating", "percent", "percentage", "_owner", "_dialogue_events", "_mentor_events", "_proposal_events", "client_interest"}

    def check(value):
        if isinstance(value, dict):
            assert not (value.keys() & forbidden)
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(report)


def test_postgres_all_history_query_is_bound_to_owner_and_unlimited():
    # Adapter contract, not a substitute for the opt-in real PostgreSQL suite.
    calls = []
    records = [{"id": f"owned-{index}"} for index in range(40)]

    class Connection:
        def execute(self, query, params):
            calls.append((query, params))
            return self

        def fetchall(self):
            return [(json.dumps(record) if index % 2 else record,) for index, record in enumerate(records)]

    @contextmanager
    def connect():
        yield Connection()

    repo = object.__new__(PostgresRepository)
    repo.connect = connect
    assert repo.list_all("account:exact-owner") == records
    query, params = calls[0]
    assert "WHERE owner = %s" in query and "LIMIT" not in query.upper()
    assert params == ("account:exact-owner",)
