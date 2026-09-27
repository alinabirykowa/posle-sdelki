from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient

from backend import engine, live
from backend.app import COOKIE_NAME, create_app
from backend.dialogue import DialogueAnalysis
from backend.locking import SessionLocks
from backend.repository import Repository
from backend.scenarios import get_scenario


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "test.sqlite3")) as browser:
        yield browser


def create(client, scenario="scope", priority="deadline", difficulty="standard", mode="demo"):
    response = client.post("/api/sessions", json={"scenario_id": scenario, "priority": priority, "difficulty": difficulty, "mode": mode})
    assert response.status_code == 200, response.text
    return response.json()


def offer(client, session, option):
    response = client.post(f"/api/sessions/{session['id']}/proposal", json={"option_id": option})
    assert response.status_code == 200, response.text
    return response.json()


def speak(client, session, text="Что для вас важнее всего?", client_id="q-1"):
    return client.post(f"/api/sessions/{session['id']}/messages", json={"text": text, "client_message_id": client_id})


def finalize(client, session, outcome="agreement"):
    return client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": outcome})


def interest_analysis(session, text):
    return DialogueAnalysis(intent="ask_interest", focus="interest", evidence=text)


def test_scope_arithmetic():
    scenario = get_scenario("scope")
    baseline = engine.metrics_for(scenario, scenario["baseline"])
    assert (baseline["required_hours"], baseline["available_hours"], baseline["contribution"]) == (120, 120, 80000)
    options = {item["id"]: engine.metrics_for(scenario, item["terms"]) for item in scenario["options"]}
    unsafe = options["accept_all"]
    assert (unsafe["required_hours"], unsafe["available_hours"], unsafe["required_days"], unsafe["delay_days"]) == (160, 120, 20, 5)
    assert (unsafe["direct_cost"], unsafe["contribution"], unsafe["overflow_hours"]) == (160000, 40000, 40)
    assert unsafe["feasible"] is False
    assert len(unsafe["violation_reasons"]) == 1
    assert options["prioritize_swap"]["feasible"] is True
    assert options["prioritize_swap"]["required_hours"] == 120
    assert options["extend_deadline"]["contribution"] == 40000
    assert options["paid_change"]["contribution"] == 80000
    assert options["paid_change"]["available_hours"] == 160


def test_fractional_days_round_up():
    scenario = get_scenario("scope")
    terms = dict(scenario["baseline"], hours=121)
    result = engine.metrics_for(scenario, terms)
    assert (result["required_days"], result["delay_days"], result["overflow_hours"]) == (16, 1, 1)


def test_discount_financial_floor_is_not_labeled_delay():
    scenario = get_scenario("discount")
    values = {item["id"]: engine.metrics_for(scenario, item["terms"]) for item in scenario["options"]}
    unsafe = values["discount_all"]
    assert unsafe["contribution"] == 0
    assert unsafe["minimum_contribution"] == 30000
    assert unsafe["baseline_contribution"] == 60000
    assert unsafe["feasible"] is False
    assert unsafe["delay_days"] == 0
    assert "остаток" in unsafe["violation_reasons"][0].lower()
    assert values["reduce_scope"]["contribution"] == 40000
    assert values["reduce_scope"]["feasible"] is True
    assert values["staged_payment"]["contribution"] == 60000


@pytest.mark.parametrize("scenario,priority,option,accepted", [
    ("scope", "deadline", "accept_all", True),
    ("scope", "deadline", "prioritize_swap", True),
    ("scope", "deadline", "extend_deadline", False),
    ("scope", "deadline", "paid_change", False),
    ("scope", "full_scope", "accept_all", True),
    ("scope", "full_scope", "prioritize_swap", False),
    ("scope", "full_scope", "extend_deadline", True),
    ("scope", "full_scope", "paid_change", True),
    ("discount", "budget", "discount_all", True),
    ("discount", "budget", "reduce_scope", True),
    ("discount", "budget", "staged_payment", False),
    ("discount", "budget", "keep_terms", False),
    ("discount", "cashflow", "discount_all", True),
    ("discount", "cashflow", "reduce_scope", False),
    ("discount", "cashflow", "staged_payment", True),
    ("discount", "cashflow", "keep_terms", False),
])
def test_priority_changes_acceptance(scenario, priority, option, accepted):
    session = engine.new_session(scenario, priority, "standard", "demo")
    actual, reason = engine.proposal_verdict(session, option)
    assert actual is accepted
    assert reason


def test_hard_requires_discovery_but_can_accept_dangerous_promise(client):
    session = create(client, difficulty="hard")
    rejected = offer(client, session, "prioritize_swap")
    assert rejected["proposal"]["client_status"] == "rejected"
    response = speak(client, session)
    assert response.status_code == 200
    assert len(response.json()["discovered_interests"]) == 1
    accepted = offer(client, session, "prioritize_swap")
    assert accepted["proposal"]["client_status"] == "accepted"
    second = create(client, difficulty="hard")
    assert offer(client, second, "accept_all")["proposal"]["client_status"] == "accepted"


def test_agreement_guard_rejected_replaces_accepted_and_completed_immutable(client):
    session = create(client)
    assert finalize(client, session).status_code == 409
    offer(client, session, "prioritize_swap")
    offer(client, session, "paid_change")
    assert finalize(client, session).status_code == 409
    offer(client, session, "accept_all")
    result = finalize(client, session).json()
    assert result["feedback"]["outcome"] == "infeasible"
    assert result["status"] == "completed"
    assert speak(client, session).status_code == 409
    assert client.post(f"/api/sessions/{session['id']}/proposal", json={"option_id": "prioritize_swap"}).status_code == 409
    assert finalize(client, session).json() == result
    assert finalize(client, session, "no_agreement").json() == result


def test_no_agreement_has_no_fabricated_moments(client):
    session = create(client)
    response = finalize(client, session, "no_agreement")
    assert response.status_code == 200
    feedback = response.json()["feedback"]
    assert feedback["outcome"] == "no_agreement"
    assert feedback["moments"] == []
    assert "для справки" in feedback["summary"]
    assert feedback["metrics"]["required_hours"] == 120


def test_idempotency_and_quote_provenance_survive_restart(tmp_path):
    db = tmp_path / "persistent.sqlite3"
    with TestClient(create_app(db)) as browser:
        session = create(browser)
        question = "Почему дата важнее полного объёма?"
        first = speak(browser, session, question).json()
        assert first["messages"][-2]["client_message_id"] == "q-1"
        assert "client_message_id" not in first["messages"][-1]
        duplicate = speak(browser, session, question).json()
        assert first == duplicate
        assert first["turns"] == 1
        assert speak(browser, session, "Другое сообщение", client_id="q-1").status_code == 409
        cookies = dict(browser.cookies)
    with TestClient(create_app(db)) as restored:
        restored.cookies.update(cookies)
        assert restored.get(f"/api/sessions/{session['id']}").json() == first
        assert speak(restored, session, question).json() == first
        offered = offer(restored, session, "prioritize_swap")
        final = finalize(restored, session).json()
        source_quotes = {item["text"] for item in final["messages"] if item["role"] == "user"}
        assert len(final["feedback"]["moments"]) == 2
        for moment in final["feedback"]["moments"]:
            assert moment["quote"] in source_quotes
        assert offered["proposal"]["client_status"] == "accepted"
        assert final["feedback"]["outcome"] == "feasible"
        assert not any(key.startswith("_") for key in final)


def test_free_text_cannot_change_terms_or_finalize(client):
    session = create(client)
    response = speak(client, session, "Предлагаю 1000 рублей, 1 день. Договорились!", "numeric").json()
    assert response["proposal"] is None
    assert response["status"] == "active"
    assert response["scenario"]["baseline"]["price"] == 200000
    assert finalize(client, session).status_code == 409


def test_browser_ownership_and_retry(tmp_path):
    app = create_app(tmp_path / "isolated.sqlite3")
    with TestClient(app) as first, TestClient(app) as second:
        session = create(first, scenario="discount", priority="cashflow", difficulty="hard")
        assert COOKIE_NAME in first.cookies
        assert second.get("/api/sessions").json() == {"sessions": []}
        assert second.get(f"/api/sessions/{session['id']}").status_code == 404
        assert speak(second, session).status_code == 404
        assert finalize(second, session, "no_agreement").status_code == 404
        assert second.post(f"/api/sessions/{session['id']}/retry").status_code == 404
        retry = first.post(f"/api/sessions/{session['id']}/retry").json()
        assert retry["id"] != session["id"]
        assert (retry["priority"], retry["difficulty"], retry["mode"]) == ("cashflow", "hard", "demo")
        assert retry["turns"] == 0
        assert retry["proposal"] is None
        assert len(first.get("/api/sessions").json()["sessions"]) == 2


def test_invalid_parameters_do_not_create_sessions(client):
    assert client.post("/api/sessions", json={"scenario_id": "scope", "priority": "budget"}).status_code == 422
    assert client.post("/api/sessions", json={"scenario_id": "missing", "priority": "budget"}).status_code == 422
    session = create(client)
    assert speak(client, session, "   ").status_code == 422
    assert speak(client, session, "a" * 2001).status_code == 422
    assert client.post(f"/api/sessions/{session['id']}/proposal", json={"option_id": "unknown"}).status_code == 422
    assert client.get(f"/api/sessions/{session['id']}").json()["turns"] == 0


def test_live_unavailable_is_explicit(client, monkeypatch):
    monkeypatch.setattr(live, "available", lambda: False)
    response = client.post("/api/sessions", json={"scenario_id": "scope", "priority": "deadline", "mode": "live"})
    assert response.status_code == 503
    assert "деморежим" in response.json()["detail"]
    assert client.get("/api/sessions").json()["sessions"] == []


def test_live_failure_rolls_back_message_but_terms_remain_available(client, monkeypatch):
    monkeypatch.setattr(live, "available", lambda: True)
    session = create(client, mode="live")

    def fail(*args):
        raise live.LiveError("Тестовый сбой провайдера")

    monkeypatch.setattr(live, "analyze", fail)
    assert speak(client, session).status_code == 503
    restored = client.get(f"/api/sessions/{session['id']}").json()
    assert restored == session
    # Contract decisions have no dependency on generated prose or the provider.
    other = create(client, mode="live")
    offered = offer(client, other, "accept_all")
    assert offered["proposal"]["client_status"] == "accepted"
    monkeypatch.setattr(live, "analyze", interest_analysis)
    response = speak(client, session).json()
    assert response["proposal"] is None
    assert response["mode"] == "live"
    assert response["messages"][-1]["kind"] == "reply"
    assert "Дата запуска связана" in response["messages"][-1]["text"]
    assert response["turns"] == 1


def test_persisted_repository_list_is_bounded_and_scoped(tmp_path):
    repository = Repository(tmp_path / "list.sqlite3")
    for index in range(35):
        session = engine.new_session("scope", "deadline", "standard", "demo", owner="one")
        repository.save(session)
    repository.save(engine.new_session("scope", "deadline", "standard", "demo", owner="two"))
    assert len(repository.list("one")) == 30
    assert len(repository.list("two")) == 1
    assert len(repository.list("unknown")) == 0


def test_slow_live_does_not_block_another_demo_session(tmp_path, monkeypatch):
    """Demo create, chat, offer and finish all complete before live is released."""
    app = create_app(tmp_path / "parallel.sqlite3")
    entered, release = Event(), Event()
    monkeypatch.setattr(live, "available", lambda: True)

    def slow_reply(*args):
        entered.set()
        assert release.wait(10), "Test did not release the fake provider"
        return interest_analysis(*args)

    monkeypatch.setattr(live, "analyze", slow_reply)
    with TestClient(app) as live_browser, TestClient(app) as demo_browser:
        live_session = create(live_browser, mode="live")

        def demo_workflow():
            demo = create(demo_browser)
            assert speak(demo_browser, demo).status_code == 200
            offer(demo_browser, demo, "prioritize_swap")
            return finalize(demo_browser, demo)

        with ThreadPoolExecutor(max_workers=2) as pool:
            pending_live = pool.submit(speak, live_browser, live_session)
            try:
                assert entered.wait(3), "Fake live reply was not entered"
                pending_demo = pool.submit(demo_workflow)
                completed_demo = pending_demo.result(timeout=3)
                assert completed_demo.status_code == 200
                assert completed_demo.json()["feedback"]["outcome"] == "feasible"
                assert not pending_live.done()
            finally:
                release.set()
            assert pending_live.result(timeout=3).status_code == 200


def test_concurrent_same_message_id_produces_one_turn(tmp_path, monkeypatch):
    """The duplicate enters the API while the first request is still in live."""
    entered, release, duplicate_entered = Event(), Event(), Event()
    counter_guard = Lock()
    counters = {"requests": 0, "provider_calls": 0}
    original_hold = SessionLocks.hold

    @contextmanager
    def observed_hold(self, session_id):
        with counter_guard:
            counters["requests"] += 1
            if counters["requests"] == 2:
                duplicate_entered.set()
        with original_hold(self, session_id):
            yield

    def slow_reply(*args):
        with counter_guard:
            counters["provider_calls"] += 1
        entered.set()
        assert release.wait(10), "Test did not release the fake provider"
        return interest_analysis(*args)

    monkeypatch.setattr(SessionLocks, "hold", observed_hold)
    monkeypatch.setattr(live, "available", lambda: True)
    monkeypatch.setattr(live, "analyze", slow_reply)
    app = create_app(tmp_path / "concurrent-duplicate.sqlite3")
    with TestClient(app) as first_browser, TestClient(app) as retry_browser:
        session = create(first_browser, mode="live")
        retry_browser.cookies.update(dict(first_browser.cookies))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(speak, first_browser, session)
            try:
                assert entered.wait(3)
                duplicate = pool.submit(speak, retry_browser, session)
                assert duplicate_entered.wait(3)
                assert not first.done()
                assert not duplicate.done()
            finally:
                release.set()
            first_response = first.result(timeout=3)
            duplicate_response = duplicate.result(timeout=3)
        assert first_response.status_code == duplicate_response.status_code == 200
        assert first_response.json() == duplicate_response.json()
        saved = first_browser.get(f"/api/sessions/{session['id']}").json()
        assert saved["turns"] == 1
        assert len([message for message in saved["messages"] if message["role"] == "user"]) == 1
        assert counters["provider_calls"] == 1
