"""Generated dialogue preserves transactions, retries, and server-owned deals."""

from copy import deepcopy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import ai_conversation, live
from backend.app import create_app
from backend.dialogue import DialogueAnalysis


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "available", lambda: True)
    monkeypatch.setenv("LLM_REPLY_MODE", "generated")
    monkeypatch.setattr(live, "analyze", lambda session, text: DialogueAnalysis(
        intent="ask_interest", evidence=text, focus="interest", uncertain=False,
    ))
    with TestClient(create_app(tmp_path / "generated.sqlite3")) as browser:
        yield browser


def start(client, mode="live"):
    response = client.post("/api/sessions", json={
        "scenario_id": "scope", "priority": "deadline", "difficulty": "hard", "mode": mode,
    })
    assert response.status_code == 200
    return response.json()


def say(client, session, key="one"):
    return client.post(f"/api/sessions/{session['id']}/messages", json={
        "text": "Что для вас важнее всего?", "client_message_id": key,
    })


def test_generated_reply_saved_once_with_engine_analysis(client, monkeypatch):
    calls = []

    def generate(session, facts):
        calls.append(deepcopy(session))
        assert session["discovered_interests"]
        assert "Дата запуска" in facts
        return "Для меня решающей остаётся дата запуска. Какие задачи вы предлагаете оставить?"

    monkeypatch.setattr(ai_conversation, "generate_reply", generate)
    session = start(client)
    assert session["reply_mode"] == "generated"
    assert "AI-собеседник" in session["messages"][0]["text"]
    response = say(client, session)
    assert response.status_code == 200
    result = response.json()
    assert result["turns"] == 1
    assert result["proposal"] is None
    assert result["messages"][-1]["text"].startswith("Для меня решающей")
    assert say(client, session).json() == result
    assert len(calls) == 1
    assert client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "agreement"}).status_code == 409


def test_generation_failure_rolls_back_discovery_and_message_id(client, monkeypatch):
    session = start(client)

    def fail(session, facts):
        raise live.LiveError("Не удалось сформулировать ответ. Изменения не сохранены.")

    monkeypatch.setattr(ai_conversation, "generate_reply", fail)
    assert say(client, session).status_code == 503
    assert client.get(f"/api/sessions/{session['id']}").json() == session
    stored = client.app.state.repository.get(session["id"])
    assert stored["_client_message_ids"] == {}
    assert stored["_dialogue_events"] == []
    monkeypatch.setattr(ai_conversation, "generate_reply", lambda s, f: "Для меня важен срок. Как вы предлагаете его сохранить?")
    assert say(client, session).status_code == 200


def test_demo_and_legacy_live_do_not_call_generator(client, monkeypatch):
    monkeypatch.setattr(ai_conversation, "generate_reply", lambda *args: pytest.fail("Must not generate"))
    demo = start(client, mode="demo")
    assert demo["reply_mode"] == "rules"
    assert say(client, demo).status_code == 200
    legacy = start(client)
    stored = client.app.state.repository.get(legacy["id"])
    del stored["reply_mode"]
    client.app.state.repository.save(stored)
    assert say(client, legacy).status_code == 200


def test_retry_retains_reply_mode_despite_global_change(client, monkeypatch):
    generated = start(client)
    monkeypatch.setenv("LLM_REPLY_MODE", "rules")
    child = client.post(f"/api/sessions/{generated['id']}/retry", json={"client_action_id": "retry-one"}).json()
    assert child["reply_mode"] == "generated"
    assert child["retry_of"] == generated["id"]
    rules = start(client)
    monkeypatch.setenv("LLM_REPLY_MODE", "generated")
    child = client.post(f"/api/sessions/{rules['id']}/retry").json()
    assert child["reply_mode"] == "rules"


def test_proposal_and_finish_never_call_generator(client, monkeypatch):
    monkeypatch.setattr(ai_conversation, "generate_reply", lambda *args: pytest.fail("Must not generate"))
    session = start(client)
    rejected = client.post(f"/api/sessions/{session['id']}/proposal", json={"option_id": "paid_change"}).json()
    assert rejected["proposal"]["client_status"] == "rejected"
    assert client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "agreement"}).status_code == 409
    assert client.post(f"/api/sessions/{session['id']}/finish", json={"outcome": "no_agreement"}).status_code == 200


def test_capability_is_advertised_without_enabling_demo(client):
    health = client.get("/api/health").json()
    assert health["live_reply_mode"] == "generated"
    assert health["default_mode"] == "demo"
    assert client.get("/api/scenarios").json()["live_reply_mode"] == "generated"


def test_real_groq_transport_handles_both_steps_and_duplicate(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_only_not_a_real_credential")
    monkeypatch.setenv("LLM_MODEL", "qwen/qwen3.8-27b")
    monkeypatch.setenv("LLM_REPLY_MODE", "generated")
    requests = []
    text = "Что для вас важнее всего?"

    def transport(request):
        requests.append(json.loads(request.content))
        payload = (
            {"intent": "ask_interest", "evidence": text, "focus": "interest", "uncertain": False}
            if len(requests) == 1 else
            {"reply": "Мне важна дата запуска. Какие задачи вы предлагаете оставить к этому сроку?"}
        )
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(payload, ensure_ascii=False),
        }}]})

    with httpx.Client(transport=httpx.MockTransport(transport)) as provider:
        monkeypatch.setattr(live.httpx, "post", provider.post)
        with TestClient(create_app(tmp_path / "transport.sqlite3")) as browser:
            session = start(browser)
            response = say(browser, session)
            assert response.status_code == 200
            result = response.json()
            assert result["messages"][-1]["text"].startswith("Мне важна дата запуска")
            assert result["proposal"] is None
            assert result["discovered_interests"]
            assert say(browser, session).json() == result
            assert len(requests) == 2
            assert all(item["model"] == "qwen/qwen3.8-27b" for item in requests)
