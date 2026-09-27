"""Groq transport uses fake credentials and mock HTTP only."""

from copy import deepcopy
import json

import httpx
import pytest

from backend import engine, live
from backend.dialogue import DialogueAnalysis


KEY = "fake-groq-key-not-a-real-secret"
GENERIC_KEY = "fake-generic-key-not-a-real-secret"
OIDC = "fake-vercel-oidc-never-for-groq"
TEXT = "Что для вас важнее всего?"
ANALYSIS = {"intent": "ask_interest", "focus": "interest", "evidence": TEXT, "uncertain": False}
REPLY_SCHEMA = {
    "type": "object", "properties": {"reply": {"type": "string"}},
    "required": ["reply"], "additionalProperties": False,
}


@pytest.fixture
def groq(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    monkeypatch.setenv("LLM_API_KEY", GENERIC_KEY)
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", OIDC)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "fake-gateway-not-for-groq")
    monkeypatch.setenv("LLM_BASE_URL", "https://stale-endpoint.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "test-groq-model")
    clients = []

    def install(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        monkeypatch.setattr(live.httpx, "post", client.post)

    yield install
    for client in clients:
        client.close()


def completion(payload):
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def test_groq_fixed_endpoint_isolated_credentials_and_token_limit(groq):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=completion(ANALYSIS))

    groq(handle)
    session = engine.new_session("scope", "deadline", "standard", "live")
    before = deepcopy(session)
    assert live.analyze(session, TEXT).model_dump() == ANALYSIS
    assert session == before
    assert live.available()
    assert live.settings() == (KEY, live.GROQ_BASE_URL, "test-groq-model")
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer " + KEY
    body = json.loads(request.content)
    assert body["model"] == "test-groq-model"
    assert body["max_completion_tokens"] == 600
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert "max_tokens" not in body
    assert "service_tier" not in body
    assert "reasoning_effort" not in body
    assert body["messages"][-1] == {"role": "user", "content": TEXT}
    assert request.extensions["timeout"] == {"connect": 5.0, "read": 18.0, "write": 18.0, "pool": 18.0}
    assert all(secret not in request.content.decode() for secret in (KEY, GENERIC_KEY, OIDC))


@pytest.mark.parametrize("dedicated", [None, "", "   "])
def test_groq_can_use_explicit_generic_key(groq, monkeypatch, dedicated):
    if dedicated is None:
        monkeypatch.delenv("GROQ_API_KEY")
    else:
        monkeypatch.setenv("GROQ_API_KEY", dedicated)
    assert live.settings()[0] == GENERIC_KEY
    assert live.available()


def test_groq_never_uses_vercel_credentials(groq, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.delenv("LLM_API_KEY")
    groq(lambda request: pytest.fail("No Groq key: must not send request"))
    assert live.settings()[0] == ""
    assert live.available() is False
    with pytest.raises(live.LiveError, match="GROQ_API_KEY"):
        live.request_json([{"role": "user", "content": "JSON"}])


@pytest.mark.parametrize("model", [None, "", "   ", "model with spaces", "bad\nmodel"])
def test_groq_requires_explicit_valid_model(groq, monkeypatch, model):
    if model is None:
        monkeypatch.delenv("LLM_MODEL")
    else:
        monkeypatch.setenv("LLM_MODEL", model)
    groq(lambda request: pytest.fail("No explicit model: must not send request"))
    assert live.available() is False
    with pytest.raises(live.LiveError, match="LLM_MODEL"):
        live.request_json([])


@pytest.mark.parametrize("provider", ["generic", "vercel"])
def test_groq_key_never_used_by_other_providers(groq, monkeypatch, provider):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.delenv("LLM_API_KEY")
    monkeypatch.delenv("AI_GATEWAY_API_KEY")
    monkeypatch.delenv("VERCEL_OIDC_TOKEN")
    assert live.settings()[0] == ""
    assert live.available() is False


def test_qwen_json_request_uses_current_nonreasoning_mode(groq, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen/qwen3.8-27b")
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=completion({"reply": "Расскажите о вашем подходе."}))

    groq(handle)
    messages = [{"role": "system", "content": "Верни JSON с reply."}, {"role": "user", "content": TEXT}]
    schema_before = deepcopy(REPLY_SCHEMA)
    messages_before = deepcopy(messages)
    result = live.request_json(messages, schema=REPLY_SCHEMA, max_tokens=500, temperature=0.3)
    assert result == {"reply": "Расскажите о вашем подходе."}
    assert REPLY_SCHEMA == schema_before
    assert messages == messages_before
    assert requests[0]["reasoning_format"] == "hidden"
    assert requests[0]["reasoning_effort"] == "none"
    assert requests[0]["max_completion_tokens"] == 500
    assert requests[0]["temperature"] == 0.3
    assert requests[0]["response_format"] == {
        "type": "json_schema", "json_schema": {
            "name": "structured_reply", "strict": True, "schema": REPLY_SCHEMA,
        },
    }


def test_qwen_analyzer_uses_strict_schema_without_mutating_local_contract(groq, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen/qwen3.8-27b")

    def handle(request):
        configured = json.loads(request.content)["response_format"]
        assert configured["type"] == "json_schema"
        assert configured["json_schema"]["strict"] is True
        assert configured["json_schema"]["name"] == "dialogue_analysis"
        schema = configured["json_schema"]["schema"]
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["additionalProperties"] is False
        assert schema["properties"]["intent"]["enum"] == DialogueAnalysis.model_json_schema()["properties"]["intent"]["enum"]
        assert "default" not in schema["properties"]["uncertain"]
        assert "maxLength" not in schema["properties"]["evidence"]
        return httpx.Response(200, json=completion(ANALYSIS))

    groq(handle)
    assert live.analyze(engine.new_session("scope", "deadline", "standard", "live"), TEXT).model_dump() == ANALYSIS
    assert DialogueAnalysis.model_json_schema()["properties"]["evidence"]["maxLength"] == 500


def test_qwen_reply_lengths_stay_local_and_input_schema_is_unchanged(groq, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen/qwen3.8-27b")
    schema = deepcopy(REPLY_SCHEMA)
    schema["properties"]["reply"].update({"minLength": 1, "maxLength": 1200})
    before = deepcopy(schema)

    def handle(request):
        configured = json.loads(request.content)["response_format"]["json_schema"]["schema"]
        assert configured["properties"]["reply"] == {"type": "string"}
        return httpx.Response(200, json=completion({"reply": "Расскажите о вашем подходе."}))

    groq(handle)
    live.request_json([], schema=schema)
    assert schema == before


@pytest.mark.parametrize("model, with_schema", [("test-groq-model", True), ("qwen/qwen3.8-27b", False)])
def test_json_object_is_retained_without_supported_model_and_schema(groq, monkeypatch, model, with_schema):
    monkeypatch.setenv("LLM_MODEL", model)

    def handle(request):
        assert json.loads(request.content)["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json=completion({"reply": "Уточните вашу мысль."}))

    groq(handle)
    live.request_json([], schema=REPLY_SCHEMA if with_schema else None)


def test_shared_helper_accepts_reply_schema_for_vercel(groq, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "vercel")
    monkeypatch.setenv("LLM_MODEL", "test-creator/test-model")

    def handle(request):
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"] == {
            "name": "structured_reply", "strict": True, "schema": REPLY_SCHEMA,
        }
        assert body["max_tokens"] == 600
        return httpx.Response(200, json=completion({"reply": "Уточните вашу мысль."}))

    groq(handle)
    assert live.request_json([], schema=REPLY_SCHEMA) == {"reply": "Уточните вашу мысль."}


@pytest.mark.parametrize("status, expected", [
    (400, "параметры модели"), (401, "Ключ Groq"), (403, "разрешения проекта"),
    (404, "Модель Groq"), (429, "лимит Groq"), (500, "отклонил запрос"),
])
def test_errors_are_actionable_sanitized_and_never_retried(groq, status, expected, caplog, capsys):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, headers={"retry-after": "1"}, json={"error": KEY + " private-upstream-data"})

    groq(handle)
    with pytest.raises(live.LiveError, match=expected) as error:
        live.request_json([])
    assert len(requests) == 1
    assert "Сообщение не сохранено" in str(error.value)
    captured = capsys.readouterr()
    output = str(error.value) + caplog.text + captured.out + captured.err
    assert KEY not in output
    assert "private-upstream-data" not in output


@pytest.mark.parametrize("payload", [
    {"choices": [None]}, {"choices": [{"message": {"content": "[]"}}]},
    {"choices": [{"message": {"content": "null"}}]},
    {"choices": [{"message": {"content": '{"reply":"ok"}'}, "finish_reason": "length"}]},
])
def test_helper_rejects_nonobjects_and_truncation(groq, payload):
    groq(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(live.LiveError):
        live.request_json([])


def test_groq_analysis_remains_locally_validated(groq):
    groq(lambda request: httpx.Response(200, json=completion({**ANALYSIS, "evidence": "invented"})))
    session = engine.new_session("scope", "deadline", "standard", "live")
    before = deepcopy(session)
    with pytest.raises(live.LiveError):
        live.analyze(session, TEXT)
    assert session == before


def test_groq_timeout_is_sanitized_and_does_not_retry(groq, caplog, capsys):
    requests = []

    def handle(request):
        requests.append(request)
        raise httpx.ReadTimeout(KEY + " private-upstream-data", request=request)

    groq(handle)
    with pytest.raises(live.LiveError) as error:
        live.request_json([])
    assert len(requests) == 1
    assert error.value.__suppress_context__
    captured = capsys.readouterr()
    output = str(error.value) + caplog.text + captured.out + captured.err
    assert KEY not in output
    assert "private-upstream-data" not in output


@pytest.mark.parametrize("setting, expected", [
    (None, "rules"), ("", "rules"), ("rules", "rules"), ("generated", "generated"),
    (" generated ", "generated"), ("GENERATED", "rules"), ("typo", "rules"),
])
def test_generation_requires_explicit_mode(monkeypatch, setting, expected):
    if setting is None:
        monkeypatch.delenv("LLM_REPLY_MODE", raising=False)
    else:
        monkeypatch.setenv("LLM_REPLY_MODE", setting)
    assert live.reply_mode() == expected
