"""HTTP boundary tests: no real provider, no real credentials."""

from copy import deepcopy
import json

import httpx
import pytest

from backend import engine, live
from backend.dialogue import DialogueAnalysis


TEST_KEY = "fake-test-key-not-a-real-secret"
CURRENT_TEXT = "Расскажите, что для вас важнее всего в этом проекте?"
VALID_ANALYSIS = {
    "intent": "ask_interest", "evidence": "что для вас важнее всего",
    "focus": "interest", "uncertain": False,
}


@pytest.fixture
def provider_transport(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", TEST_KEY)
    monkeypatch.setenv("LLM_BASE_URL", "https://unit-provider.example/v1/")
    monkeypatch.setenv("LLM_MODEL", "fake-test-model")
    clients = []

    def install(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        # Preserve the production analyzer, replacing only the HTTP boundary.
        monkeypatch.setattr(live.httpx, "post", client.post)

    yield install
    for client in clients:
        client.close()


def sample_session():
    session = engine.new_session("scope", "deadline", "standard", "live", owner="private-owner-cookie")
    engine.add_message(session, "user", "Здравствуйте!", "message")
    engine.add_message(session, "assistant", "Здравствуйте. Готова обсудить условия.", "message")
    engine.add_message(session, "system", "private-system-state", "notice")
    session["_internal_secret"] = "private-session-state"
    return session


def completion(payload):
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def assert_sanitized(error, caplog, capsys):
    captured = capsys.readouterr()
    assert TEST_KEY not in str(error.value) + caplog.text + captured.out + captured.err


@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_http_errors_are_sanitized(provider_transport, status, caplog, capsys):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer " + TEST_KEY
        return httpx.Response(status, json={"error": {"message": "Upstream included " + TEST_KEY}})

    provider_transport(handler)
    with pytest.raises(live.LiveError) as error:
        live.analyze(sample_session(), CURRENT_TEXT)
    assert "отклонил запрос" in str(error.value)
    assert_sanitized(error, caplog, capsys)


def test_provider_timeout_is_sanitized(provider_transport, caplog, capsys):
    def handler(request):
        raise httpx.ReadTimeout("Upstream timeout included " + TEST_KEY, request=request)

    provider_transport(handler)
    with pytest.raises(live.LiveError) as error:
        live.analyze(sample_session(), CURRENT_TEXT)
    assert "Изменения не сохранены" in str(error.value)
    assert error.value.__suppress_context__ is True
    assert_sanitized(error, caplog, capsys)


@pytest.mark.parametrize("payload", [
    b"not JSON: " + TEST_KEY.encode(),
    {},
    {"choices": []},
    {"choices": [{"message": {"content": ""}}]},
    {"choices": [{"message": {"content": " \n\t "}}]},
    {"choices": [{"message": {"content": None}}]},
    {"choices": [{"message": {"content": {"unexpected": TEST_KEY}}}]},
    {"choices": [{"message": {"content": "Вот ответ: " + TEST_KEY}}]},
    {"choices": [{"message": {"content": "я" * 4001}}]},
])
def test_malformed_or_empty_provider_content_is_rejected(provider_transport, payload, caplog, capsys):
    def handler(request):
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    provider_transport(handler)
    with pytest.raises(live.LiveError) as error:
        live.analyze(sample_session(), CURRENT_TEXT)
    assert_sanitized(error, caplog, capsys)


@pytest.mark.parametrize("payload", [
    {**VALID_ANALYSIS, "evidence": "Придуманная цитата " + TEST_KEY},
    {**VALID_ANALYSIS, "terms": {"price": 1, "hours": 999}},
    {**VALID_ANALYSIS, "client_status": "accepted"},
    {**VALID_ANALYSIS, "intent": "accepted"},
    {**VALID_ANALYSIS, "focus": "secret"},
    {**VALID_ANALYSIS, "evidence": ""},
    {**VALID_ANALYSIS, "extra": TEST_KEY},
    {},
    [],
    None,
])
def test_invalid_semantic_analysis_is_rejected(provider_transport, payload, caplog, capsys):
    provider_transport(lambda request: httpx.Response(200, json=completion(payload)))
    session = sample_session()
    before = deepcopy(session)
    with pytest.raises(live.LiveError) as error:
        live.analyze(session, CURRENT_TEXT)
    assert session == before
    assert_sanitized(error, caplog, capsys)


def test_success_returns_validated_analysis_and_minimal_request(provider_transport):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=completion(VALID_ANALYSIS))

    provider_transport(handler)
    session = sample_session()
    before = deepcopy(session)
    result = live.analyze(session, CURRENT_TEXT)
    assert isinstance(result, DialogueAnalysis)
    assert result.model_dump() == VALID_ANALYSIS
    assert session == before
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://unit-provider.example/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer " + TEST_KEY
    body = json.loads(request.content)
    assert body["model"] == "fake-test-model"
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][-1] == {"role": "user", "content": CURRENT_TEXT}
    assert [item["content"] for item in body["messages"]].count(CURRENT_TEXT) == 1
    assert [item["role"] for item in body["messages"]].count("system") == 1
    assert all(set(item) == {"role", "content"} for item in body["messages"])
    assert any(item["content"] == "Здравствуйте!" for item in body["messages"])
    assert any(item["content"] == "Здравствуйте. Готова обсудить условия." for item in body["messages"])
    sent = json.dumps(body, ensure_ascii=False)
    for private_value in (TEST_KEY, "private-owner-cookie", "private-system-state", "private-session-state", session["id"]):
        assert private_value not in sent
    for private_key in ("_owner", "_client_message_ids", "_internal_secret", "discovered_interests", "options", "baseline", "priority"):
        assert private_key not in sent
    assert session["scenario"]["briefing"] in body["messages"][0]["content"]
    assert body["temperature"] == 0
    assert request.extensions["timeout"] == {"connect": 8.0, "read": 25.0, "write": 25.0, "pool": 25.0}


def test_current_text_is_not_duplicated_when_already_appended(provider_transport):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=completion(VALID_ANALYSIS))

    provider_transport(handler)
    session = sample_session()
    engine.add_message(session, "user", CURRENT_TEXT)
    live.analyze(session, CURRENT_TEXT)
    assert [item["content"] for item in requests[0]["messages"]].count(CURRENT_TEXT) == 1


def test_history_is_bounded(provider_transport):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=completion(VALID_ANALYSIS))

    provider_transport(handler)
    session = sample_session()
    for index in range(30):
        engine.add_message(session, "assistant" if index % 2 else "user", f"Предыдущая реплика {index}")
    live.analyze(session, CURRENT_TEXT)
    messages = requests[0]["messages"]
    assert len(messages) == 14  # one instruction, 12 history turns, current text
    assert messages[1]["content"] == "Предыдущая реплика 18"


def test_missing_configuration_does_not_contact_provider(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    def must_not_call(*args, **kwargs):
        pytest.fail("No HTTP request should occur without explicit configuration")

    monkeypatch.setattr(live.httpx, "post", must_not_call)
    assert live.available() is False
    with pytest.raises(live.LiveError, match="AI не подключён"):
        live.analyze(sample_session(), CURRENT_TEXT)
