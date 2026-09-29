"""Configured B2B cases must remain deterministic, isolated and recoverable."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from importlib import import_module
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient

from backend import engine, live, training
from backend.app import create_app
from backend.locking import SessionLocks
from backend.repository import Repository


def configuration(**changes):
    return {
        "industry": "it", "topic": "scope", "difficulty": "hard", "tone": "reserved",
        "client_role": "procurement", "goal": "deadline", "duration_minutes": 5,
        "format": "text", "response_seconds": 0, **changes,
    }


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "training.sqlite3")) as browser:
        yield browser


def start(browser, config=None, key="start-1", **body):
    return browser.post("/api/training/start", json={
        "configuration": config or configuration(), "client_action_id": key, **body,
    })


def preview(browser, **changes):
    return browser.post("/api/training/preview", json={"configuration": configuration(**changes)})


def say(browser, session, text="Что для вас важнее всего?", key="message-1"):
    return browser.post(f"/api/sessions/{session['id']}/messages", json={"text": text, "client_message_id": key})


def propose(browser, session, option="prioritize_swap", key="offer-1"):
    return browser.post(f"/api/sessions/{session['id']}/proposal", json={"option_id": option, "client_action_id": key})


def test_preview_is_deterministic_read_only_and_start_matches(client):
    first = preview(client)
    assert first.status_code == 200
    result = first.json()
    assert preview(client).json() == result
    assert client.get("/api/sessions").json() == {"sessions": []}
    session = start(client).json()
    assert session["scenario"] == result["scenario"]
    assert session["training_config"] == result["configuration"] == configuration()
    assert session["context_key"] == result["context_key"]
    assert session["generation_method"] == result["generation_method"] == "template"
    assert session["max_turns"] == result["max_turns"] == 8
    assert session["mode"] == "demo"
    assert session["messages"][1]["text"].startswith(result["scenario"]["opening"])
    assert not any(key.startswith("_") for key in session)


@pytest.mark.parametrize("industry,expected", [("digital", "сайт"), ("it", "CRM"), ("consulting", "аудит")])
@pytest.mark.parametrize("topic,goal", [("scope", "deadline"), ("discount", "budget")])
def test_industry_changes_context_without_inventing_financial_conditions(client, industry, expected, topic, goal):
    session = start(client, configuration(industry=industry, topic=topic, goal=goal)).json()
    scenario = session["scenario"]
    assert expected.lower() in (scenario["briefing"] + scenario["opening"]).lower()
    assert "дизайн-студии" not in scenario["briefing"]
    assert "дизайн-проект" not in scenario["briefing"]
    assert scenario["practice_model"] == "conversation"
    assert scenario["baseline"] is None
    assert all(option["terms"] is None and option["description"] for option in scenario["options"])
    assert "minimum_contribution" not in scenario
    assert not any(amount in str(scenario) for amount in ("200 000", "120 000", "180 000", "240 000", "₽", "себестоим", "марж"))
    interest = say(client, session).json()["messages"][-1]["text"]
    assert scenario["client_interest"] in interest


def test_roles_and_tones_change_speech_without_changing_acceptance(client):
    openings, replies, roles = set(), set(), set()
    for index, (role, tone) in enumerate(zip(training.ROLES, ("collaborative", "reserved", "pressing"))):
        session = start(client, configuration(client_role=role, tone=tone), str(index)).json()
        openings.add(session["messages"][1]["text"])
        roles.add(session["scenario"]["client_role"])
        updated = say(client, session).json()
        replies.add(updated["messages"][-1]["text"])
        accepted = propose(client, session).json()
        assert accepted["proposal"]["client_status"] == "accepted"
        assert "Предложение принято." in accepted["messages"][-1]["text"]
        assert accepted["proposal"]["reason"] in accepted["messages"][-1]["text"]
        assert accepted["proposal"]["terms"] is None
        assert accepted["proposal"]["description"]
    assert len(openings) == len(replies) == len(roles) == 3


def test_same_deal_option_changes_outcome_when_the_wording_is_hostile(client):
    diplomatic = start(client, configuration(difficulty="standard"), "diplomatic").json()
    hostile = start(client, configuration(difficulty="standard"), "hostile").json()

    clear = say(client, diplomatic, "Что для вас важнее всего в этом проекте?", "diplomatic-question").json()
    attacked = say(client, hostile, "Вы идиот. Что для вас важнее всего в этом проекте?", "hostile-question").json()
    assert diplomatic["scenario"]["client_interest"] in clear["messages"][-1]["text"]
    assert "не буду раскрывать дополнительные детали" in attacked["messages"][-1]["text"]

    accepted = propose(client, clear, "prioritize_swap", "diplomatic-offer").json()
    rejected = propose(client, attacked, "prioritize_swap", "hostile-offer").json()
    assert accepted["proposal"]["client_status"] == "accepted"
    assert rejected["proposal"]["client_status"] == "rejected"
    assert "прозвучала как давление" in rejected["proposal"]["reason"]
    assert accepted["proposal"]["terms"] is None
    assert rejected["proposal"]["terms"] is None


def test_two_constructive_turns_reopen_a_guarded_negotiation(client):
    session = start(client, configuration(difficulty="standard"), "repair").json()
    session = say(client, session, "Вы идиот. Что для вас важно?", "repair-hostile").json()
    session = say(client, session, "Давайте уточним, что для вас важно?", "repair-one").json()
    session = say(client, session, "Понимаю, что дата для вас важна. Давайте обсудим приоритетные задачи.", "repair-two").json()
    result = propose(client, session, "prioritize_swap", "repair-offer").json()
    assert result["proposal"]["client_status"] == "accepted"
    assert "pressure" not in result["proposal"]["reason"].lower()


def test_route_stage_is_saved_and_kept_when_the_same_situation_is_retried(client):
    session = start(
        client,
        configuration(difficulty="standard"),
        "route-goal",
        route_stage="objection",
    ).json()
    assert session["route_stage"] == "objection"
    retried = client.post(
        f"/api/sessions/{session['id']}/retry",
        json={"client_action_id": "route-goal-retry"},
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["route_stage"] == "objection"


@pytest.mark.parametrize("changes", [
    {"industry": "medical"}, {"topic": "other"}, {"difficulty": "easy"},
    {"tone": "rude"}, {"client_role": "administrator"}, {"goal": "budget"},
    {"duration_minutes": 6}, {"duration_minutes": "5"}, {"duration_minutes": 5.0},
    {"format": "video"}, {"response_seconds": True}, {"response_seconds": 30},
    {"response_seconds": "45"}, {"extra": "unknown"},
])
def test_invalid_configuration_never_creates_sessions(client, changes):
    config = configuration(**changes)
    assert start(client, config).status_code == 422
    assert client.post("/api/training/preview", json={"configuration": config}).status_code == 422
    assert client.get("/api/sessions").json() == {"sessions": []}


def test_every_configuration_field_is_required_and_start_id_is_required(client):
    for field in configuration():
        config = configuration()
        del config[field]
        assert start(client, config).status_code == 422
    assert client.post("/api/training/start", json={"configuration": configuration()}).status_code == 422
    for bad_key in ("", "   ", "x" * 101, None, 123):
        assert start(client, key=bad_key).status_code == 422
    assert start(client, extra="forbidden").status_code == 422


def test_context_key_includes_every_setting_but_not_identity(client):
    initial = preview(client).json()["context_key"]
    alternatives = {
        "industry": "digital", "difficulty": "standard", "tone": "pressing",
        "client_role": "business_owner", "goal": "full_scope", "duration_minutes": 15,
        "format": "voice", "response_seconds": 45,
    }
    keys = {initial}
    for field, value in alternatives.items():
        keys.add(preview(client, **{field: value}).json()["context_key"])
    keys.add(preview(client, topic="discount", goal="cashflow").json()["context_key"])
    assert len(keys) == len(alternatives) + 2
    assert start(client, key="one").json()["context_key"] == start(client, key="two").json()["context_key"]


@pytest.mark.parametrize("minutes,limit", [(5, 8), (10, 16), (15, 24)])
def test_duration_limits_actions_not_finishing_or_recovery(client, minutes, limit):
    session = start(client, configuration(duration_minutes=minutes, difficulty="standard")).json()
    assert session["max_turns"] == limit
    assert propose(client, session).status_code == 200
    for index in range(limit - 1):
        assert say(client, session, "Понятно", str(index)).status_code == 200
    blocked = say(client, session, "Ещё один вопрос", "over-limit")
    assert blocked.status_code == 409
    assert str(limit) in blocked.json()["detail"]
    assert propose(client, session, key="new-offer").status_code == 409
    assert propose(client, session).json()["turns"] == limit
    final = client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "agreement"})
    assert final.status_code == 200
    assert final.json()["feedback"]["outcome"] == "agreement"
    assert final.json()["feedback"]["metrics"] is None
    assert start(client, configuration(duration_minutes=minutes, difficulty="standard")).json() == final.json()


def test_goal_and_hard_gating_are_authoritative(client):
    session = start(client).json()
    assert propose(client, session).json()["proposal"]["client_status"] == "rejected"
    say(client, session)
    assert propose(client, session, key="offer-2").json()["proposal"]["client_status"] == "accepted"
    full = start(client, configuration(goal="full_scope", difficulty="standard"), "full").json()
    assert propose(client, full).json()["proposal"]["client_status"] == "rejected"
    assert propose(client, full, "extend_deadline", "phases").json()["proposal"]["client_status"] == "accepted"
    cash = start(client, configuration(topic="discount", goal="cashflow", difficulty="standard"), "cash").json()
    assert propose(client, cash, "staged_payment").json()["proposal"]["client_status"] == "accepted"
    assert propose(client, cash, "reduce_scope", "reduce").json()["proposal"]["client_status"] == "rejected"


def test_retry_preserves_snapshot_even_after_templates_change(client, monkeypatch):
    config = configuration(industry="consulting", format="voice", response_seconds=45)
    parent = start(client, config).json()
    say(client, parent)
    monkeypatch.setitem(training.INDUSTRIES["consulting"], "project", "ИЗМЕНЁННЫЙ ШАБЛОН")
    child = client.post(f"/api/sessions/{parent['id']}/retry", json={"client_action_id": "retry"}).json()
    assert child["id"] != parent["id"]
    assert child["retry_of"] == parent["id"]
    for field in ("scenario", "training_config", "context_key", "max_turns", "generation_method"):
        assert child[field] == parent[field]
    assert child["messages"][1]["text"] == parent["messages"][1]["text"]
    assert child["turns"] == 0 and child["discovered_interests"] == []
    stored = client.app.state.repository.get(child["id"])
    assert "_start_payload" not in stored
    assert client.post(f"/api/sessions/{parent['id']}/retry", json={"client_action_id": "retry"}).json() == child


def test_start_dedup_survives_restart_and_conflicting_payload_is_rejected(tmp_path):
    path = tmp_path / "restart.sqlite3"
    with TestClient(create_app(path)) as browser:
        session = start(browser).json()
        updated = say(browser, session).json()
        cookies = dict(browser.cookies)
    with TestClient(create_app(path)) as browser:
        browser.cookies.update(cookies)
        assert start(browser).json() == updated
        assert start(browser, configuration(tone="pressing")).status_code == 409
        assert start(browser, mode="live").status_code == 409
        assert len(browser.get("/api/sessions").json()["sessions"]) == 1


def test_same_start_id_is_isolated_by_browser_owner(tmp_path):
    app = create_app(tmp_path / "owners.sqlite3")
    with TestClient(app) as first, TestClient(app) as second:
        one, two = start(first).json(), start(second).json()
        assert one["id"] != two["id"]
        assert one["context_key"] == two["context_key"]
        assert first.get(f"/api/sessions/{two['id']}").status_code == 404
        assert second.get(f"/api/sessions/{one['id']}").status_code == 404
        assert len(first.get("/api/sessions").json()["sessions"]) == len(second.get("/api/sessions").json()["sessions"]) == 1


def test_start_uses_shared_repository_transaction_for_read_and_write(tmp_path, monkeypatch):
    app_module = import_module("backend.app")

    class HeldRepository(Repository):
        held = None

        @contextmanager
        def hold(self, session_id):
            assert self.held is None
            self.held = session_id
            try:
                yield
            finally:
                self.held = None

        def get(self, session_id):
            assert self.held == session_id
            return super().get(session_id)

        def save(self, session):
            assert self.held == session["id"]
            return super().save(session)

    repository = HeldRepository(tmp_path / "transaction.sqlite3")
    monkeypatch.setattr(app_module, "create_repository", lambda _: repository)
    with TestClient(create_app()) as browser:
        session = start(browser)
        assert session.status_code == 200
        assert start(browser).json() == session.json()
    assert repository.held is None


def test_concurrent_start_executes_once(tmp_path, monkeypatch):
    entered, release, second_entered = Event(), Event(), Event()
    guard = Lock()
    counts = {"holds": 0, "creates": 0}
    original_hold, original_new = SessionLocks.hold, engine.new_session

    @contextmanager
    def observed_hold(self, key):
        with guard:
            counts["holds"] += 1
            if counts["holds"] == 2:
                second_entered.set()
        with original_hold(self, key):
            yield

    def slow_new(*args, **kwargs):
        counts["creates"] += 1
        entered.set()
        assert release.wait(10)
        return original_new(*args, **kwargs)

    monkeypatch.setattr(SessionLocks, "hold", observed_hold)
    monkeypatch.setattr(engine, "new_session", slow_new)
    app = create_app(tmp_path / "concurrent.sqlite3")
    with TestClient(app) as first, TestClient(app) as second:
        first.get("/api/health")
        second.cookies.update(dict(first.cookies))
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(start, first)
            try:
                assert entered.wait(3)
                duplicate = pool.submit(start, second)
                assert second_entered.wait(3)
            finally:
                release.set()
            first_response, second_response = pending.result(timeout=3), duplicate.result(timeout=3)
        assert first_response.status_code == second_response.status_code == 200
        assert first_response.json() == second_response.json()
        assert counts["creates"] == 1
        assert len(first.get("/api/sessions").json()["sessions"]) == 1


def test_live_availability_checked_only_for_new_start(client, monkeypatch):
    monkeypatch.setattr(live, "available", lambda: False)
    assert start(client, mode="live").status_code == 503
    assert client.get("/api/sessions").json() == {"sessions": []}
    monkeypatch.setattr(live, "available", lambda: True)
    created = start(client, mode="live").json()
    monkeypatch.setattr(live, "available", lambda: False)
    assert start(client, mode="live").json() == created
    assert start(client, key="new", mode="live").status_code == 503


def test_legacy_sessions_keep_their_contract(client):
    session = client.post("/api/sessions", json={"scenario_id": "scope", "priority": "deadline"}).json()
    assert session["scenario"] == training.get_scenario("scope")
    assert all(key not in session for key in ("training_config", "context_key", "max_turns", "generation_method"))
    stored = client.app.state.repository.get(session["id"])
    stored["turns"] = 29
    client.app.state.repository.save(stored)
    assert say(client, session).json()["turns"] == 30
    assert say(client, session, key="new").status_code == 409
    child = client.post(f"/api/sessions/{session['id']}/retry").json()
    assert all(key not in child for key in ("training_config", "context_key", "max_turns", "generation_method"))


def test_saved_financial_configured_snapshot_retries_without_conversion(client):
    """A pre-upgrade configured conversation must keep its original numbers."""
    owner_session = client.post("/api/sessions", json={"scenario_id": "scope", "priority": "deadline"}).json()
    owner = client.app.state.repository.get(owner_session["id"])["_owner"]
    config = training.TrainingConfig(**configuration(difficulty="standard"))
    previous = training.build_financial_preview(config)
    saved = engine.new_session("scope", "deadline", "standard", "demo", owner,
                               scenario_snapshot=previous["scenario"], training_config=previous["configuration"],
                               context_key=previous["context_key"], max_turns=previous["max_turns"])
    client.app.state.repository.save(saved)
    child = client.post(f"/api/sessions/{saved['id']}/retry", json={"client_action_id": "old-retry"}).json()
    assert child["scenario"] == saved["scenario"]
    assert child["scenario"]["baseline"]["price"] == 200000
    assert "practice_model" not in child["scenario"]
    assert propose(client, child).json()["proposal"]["terms"]["hours"] == 120
    final = client.post(f"/api/sessions/{child['id']}/finish", json={"outcome": "agreement"}).json()
    assert final["feedback"]["outcome"] == "feasible"
    assert final["feedback"]["metrics"]["feasible"] is True


@pytest.mark.parametrize("topic,goal,option,phrase", [
    ("scope", "deadline", "accept_all", "возможности команды"),
    ("discount", "budget", "discount_all", "встречный шаг"),
])
def test_unconditional_concession_feedback_is_visible_without_financial_judgment(client, topic, goal, option, phrase):
    session = start(client, configuration(topic=topic, goal=goal, difficulty="standard")).json()
    assert propose(client, session, option).json()["proposal"]["client_status"] == "accepted"
    final = client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "agreement"}).json()
    feedback = final["feedback"]
    assert feedback["outcome"] == "agreement"
    assert feedback["metrics"] is None
    assert "само по себе не показывает качество переговоров" in feedback["summary"]
    assert phrase in feedback["next_step"]
    assert "убыт" not in str(feedback) and "марж" not in str(feedback)
    assert any(moment["message_id"] == next(message["id"] for message in final["messages"] if message["kind"] == "proposal") for moment in feedback["moments"])


def test_demo_spoken_proposal_with_actual_reason_is_credited(client):
    session = start(client).json()
    assert session["messages"][0]["text"] == "Деморежим: ответы подготовлены заранее. Пишите своими словами или используйте подсказки."
    text = "Предлагаю выбрать только необходимые к запуску задачи, чтобы сохранить дату и не обещать лишнего. Остальные изменения обсудим отдельно."
    result = say(client, session, text).json()
    stored = client.app.state.repository.get(session["id"])
    assert stored["_dialogue_events"][-1]["intent"] == "propose"
    message = next(item for item in result["messages"] if item.get("client_message_id") == "message-1")
    final = client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "no_agreement"}).json()
    observed = next(item for item in final["feedback"]["behaviors"] if item["id"] == "justified_proposal")
    assert observed["status"] == "observed"
    assert observed["evidence"][0]["message_id"] == message["id"]
    assert "чтобы сохранить дату" in observed["evidence"][0]["quote"]
    assert observed["evidence"][0]["quote"] in text
