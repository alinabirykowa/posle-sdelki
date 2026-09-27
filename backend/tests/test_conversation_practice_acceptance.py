"""Independent acceptance of qualitative practice through the public API.

The legacy /sessions compatibility route is deliberately tested separately.
These checks do not call a model, access production data, or load credentials.
"""

from copy import deepcopy
import json
import re

from fastapi.testclient import TestClient
import pytest

from backend import ai_conversation, live
from backend.app import create_app


CASES = [
    ("scope", "deadline", "prioritize_swap", "extend_deadline"),
    ("scope", "full_scope", "extend_deadline", "prioritize_swap"),
    ("discount", "budget", "reduce_scope", "staged_payment"),
    ("discount", "cashflow", "staged_payment", "reduce_scope"),
]
CONFIG = {
    "industry": "it", "topic": "scope", "goal": "deadline", "difficulty": "hard",
    "tone": "collaborative", "client_role": "project_lead", "duration_minutes": 15,
    "format": "text", "response_seconds": 0,
}
FINANCIAL_FIELDS = {
    "price", "hours", "deadline_days", "daily_capacity", "hourly_cost",
    "minimum_contribution", "required_hours", "available_hours", "overflow_hours",
    "required_days", "delay_days", "direct_cost", "contribution", "baseline_contribution",
}
HUMAN_FIELDS = {
    "text", "title", "description", "briefing", "objective", "opening", "client_interest",
    "reason", "summary", "explanation", "next_step", "quote", "label",
}
QUANTITY = re.compile(r"(?<!\w)\d[\d\s,.]*(?:₽|руб\w*|час\w*|\bч\b|рабоч\w*\s+дн\w*|дней|процент\w*|%|тыс\w*)", re.I)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "available", lambda: False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    with TestClient(create_app(tmp_path / "acceptance.sqlite3")) as browser:
        yield browser


def assert_no_assumed_economics(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FINANCIAL_FIELDS:
                assert child is None, f"Unexpected invented accounting field: {key}"
            if key in HUMAN_FIELDS and isinstance(child, str):
                assert not QUANTITY.search(child), f"Unexpected invented quantity in {key}: {child}"
            assert_no_assumed_economics(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_assumed_economics(child)


def start(client, topic="scope", goal="deadline", key="start", **changes):
    config = CONFIG | {"topic": topic, "goal": goal} | changes
    response = client.post("/api/training/start", json={"configuration": config, "client_action_id": key, "mode": "demo"})
    assert response.status_code == 200, response.text
    session = response.json()
    assert session["scenario"]["practice_model"] == "conversation"
    assert session["scenario"]["baseline"] is None
    assert all(option.get("terms") is None for option in session["scenario"]["options"])
    assert_no_assumed_economics(session)
    return session


def say(client, session, text, key):
    response = client.post(f"/api/sessions/{session['id']}/messages", json={"text": text, "client_message_id": key})
    assert response.status_code == 200, response.text
    result = response.json()
    assert_no_assumed_economics(result)
    return result


def propose(client, session, option, key):
    response = client.post(f"/api/sessions/{session['id']}/proposal", json={"option_id": option, "client_action_id": key})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["proposal"]["terms"] is None
    assert result["proposal"]["description"]
    assert_no_assumed_economics(result)
    return result


def finish(client, session, outcome):
    response = client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": outcome})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "completed"
    assert result["feedback"]["outcome"] == outcome
    assert result["feedback"]["metrics"] is None
    assert_no_assumed_economics(result)
    return result


def assert_evidence_is_from_actual_user_messages(session):
    messages = {message["id"]: message for message in session["messages"]}
    feedback = session["feedback"]
    evidence = list(feedback["moments"])
    evidence.extend(item for behavior in feedback["behaviors"] for item in behavior["evidence"])
    assert evidence
    for item in evidence:
        source = messages[item["message_id"]]
        assert source["role"] == "user"
        assert item["quote"] and item["quote"] in source["text"]


@pytest.mark.parametrize("topic,goal,accepted,rejected", CASES)
def test_four_goals_refusal_revision_and_evidenced_agreement(client, topic, goal, accepted, rejected):
    session = start(client, topic, goal)
    assert client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "agreement"}).status_code == 409
    session = say(client, session, "Что для вас важнее всего в этом проекте?", "interest")
    assert session["discovered_interests"]
    refusal = propose(client, session, rejected, "wrong-approach")
    assert refusal["proposal"]["client_status"] == "rejected"
    assert client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "agreement"}).status_code == 409
    session = say(client, refusal, "Что в моём предложении вам не подходит?", "understand-refusal")
    session = say(client, session, "Уточним состав работ, чтобы сохранить важный для вас результат проекта.", "reason")
    approved = propose(client, session, accepted, "revised-approach")
    assert approved["proposal"]["client_status"] == "accepted"
    result = finish(client, approved, "agreement")
    assert_evidence_is_from_actual_user_messages(result)
    behaviors = {item["id"]: item for item in result["feedback"]["behaviors"]}
    assert behaviors["clarified_need"]["status"] == "observed"
    assert behaviors["justified_proposal"]["status"] == "observed"
    assert behaviors["responded_to_objection"]["status"] == "observed"
    assert any("отказ" in item["title"].lower() for item in result["feedback"]["moments"])
    assert finish(client, result, "agreement") == result


@pytest.mark.parametrize("topic,goal,accepted,rejected", CASES)
def test_hard_mode_needs_a_real_question_not_bare_acceptance(client, topic, goal, accepted, rejected):
    session = start(client, topic, goal)
    before = propose(client, session, accepted, "too-early")
    assert before["proposal"]["client_status"] == "rejected"
    session = say(client, before, "Понятно, договорились.", "ack")
    assert session["proposal"]["client_status"] == "rejected"
    assert not session["discovered_interests"]
    assert client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "agreement"}).status_code == 409
    session = say(client, session, "Какие ограничения нам нужно учесть?", "real-question")
    assert session["discovered_interests"]
    assert session["proposal"]["client_status"] == "rejected"
    assert propose(client, session, accepted, "after-discovery")["proposal"]["client_status"] == "accepted"


@pytest.mark.parametrize("topic,goal,accepted,rejected", CASES)
def test_reasoned_no_agreement_is_supported_without_financial_failure(client, topic, goal, accepted, rejected):
    session = start(client, topic, goal)
    session = say(client, session, "Что для вас важнее всего в этом проекте?", "interest")
    session = say(client, session, "Я не могу обещать новые задачи без согласования, потому что это создаёт риск для срока проекта.", "boundary")
    result = finish(client, session, "no_agreement")
    assert result["proposal"] is None
    assert_evidence_is_from_actual_user_messages(result)
    behaviors = {item["id"]: item for item in result["feedback"]["behaviors"]}
    assert behaviors["justified_proposal"]["status"] == "observed"
    assert "не означает неудачу" in result["feedback"]["summary"]
    assert "infeasible" not in json.dumps(result["feedback"])


@pytest.mark.parametrize("topic,goal,accepted,rejected", CASES)
def test_all_conversation_branches_and_prompts_remain_qualitative(client, topic, goal, accepted, rejected):
    session = start(client, topic, goal)
    for index, text in enumerate([
        "Про сроки", "Про бюджет", "Про оплату", "Про задачи", "Какие риски?", "Что дальше?",
        "Что для вас важнее всего в этом проекте?", "Подведём итог", "Давайте сравним варианты",
        "Почему это важно?", "Мы не можем обещать прежние условия при таком изменении.",
    ]):
        session = say(client, session, text, f"branch-{index}")
        stored = client.app.state.repository.get(session["id"])
        authoritative = session["messages"][-1]["text"]
        context = ai_conversation._context(stored, authoritative)
        assert "baseline" not in context
        assert_no_assumed_economics(context)
        assert not QUANTITY.search(json.dumps(ai_conversation._messages(stored, context), ensure_ascii=False))
        assert not QUANTITY.search(json.dumps(live._messages(stored, "Поясните вашу позицию."), ensure_ascii=False))
    session = propose(client, session, accepted, "proposal")
    session = say(client, session, "Какие условия входят в последнее предложение?", "accepted-summary")
    assert session["proposal"]["client_status"] == "accepted"
    session = propose(client, session, rejected, "superseding-rejection")
    assert session["proposal"]["client_status"] == "rejected"
    assert client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "agreement"}).status_code == 409


def test_new_retry_preserves_qualitative_snapshot_and_old_financial_session_stays_old(client):
    new_session = start(client)
    saved_scenario = deepcopy(new_session["scenario"])
    child = client.post(f"/api/sessions/{new_session['id']}/retry", json={"client_action_id": "new-retry"}).json()
    assert child["scenario"] == saved_scenario
    assert child["scenario"]["practice_model"] == "conversation"
    assert_no_assumed_economics(child)
    legacy = client.post("/api/sessions", json={"scenario_id": "scope", "priority": "deadline", "mode": "demo"}).json()
    assert legacy["scenario"].get("practice_model") != "conversation"
    assert legacy["scenario"]["baseline"]["price"] == 200000
    legacy_retry = client.post(f"/api/sessions/{legacy['id']}/retry", json={"client_action_id": "legacy-retry"}).json()
    assert legacy_retry["scenario"]["baseline"] == legacy["scenario"]["baseline"]
