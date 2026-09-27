"""Gateway preset checks use fake credentials and a mock HTTP transport only."""

from copy import deepcopy
import json

import httpx
import pytest

from backend import engine, live
from backend.dialogue import DialogueAnalysis


GATEWAY_KEY = "fake-gateway-key-not-a-real-secret"
GENERIC_KEY = "fake-generic-key-not-a-real-secret"
TEXT = "Что для вас важнее всего в этом проекте?"
ANALYSIS = {
    "intent": "ask_interest", "evidence": "Что для вас важнее всего",
    "focus": "interest", "uncertain": False,
}


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "vercel")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", GATEWAY_KEY)
    monkeypatch.setenv("LLM_API_KEY", GENERIC_KEY)
    monkeypatch.setenv("LLM_BASE_URL", "https://stale-provider.example/v1")
    monkeypatch.setenv("LLM_MODEL", "test-creator/test-model")
    monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)
    clients = []

    def install(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        monkeypatch.setattr(live.httpx, "post", client.post)

    yield install
    for client in clients:
        client.close()


def session():
    result = engine.new_session("scope", "deadline", "standard", "live", owner="private-owner")
    result["_internal_secret"] = "private-session-data"
    engine.add_message(result, "system", "private-system-notice", "notice")
    return result


def completion(payload):
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def test_gateway_uses_official_endpoint_and_strict_schema(gateway):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=completion(ANALYSIS))

    gateway(handle)
    current = session()
    before = deepcopy(current)
    result = live.analyze(current, TEXT)
    assert current == before
    assert result.model_dump() == ANALYSIS
    assert live.available()
    assert live.settings() == (GATEWAY_KEY, live.VERCEL_BASE_URL, "test-creator/test-model")
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://ai-gateway.vercel.sh/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer " + GATEWAY_KEY
    body = json.loads(request.content)
    assert body["model"] == "test-creator/test-model"
    assert body["temperature"] == 0
    assert body["max_tokens"] == 600
    assert body["messages"][-1] == {"role": "user", "content": TEXT}
    assert body["response_format"]["type"] == "json_schema"
    schema_config = body["response_format"]["json_schema"]
    assert schema_config["strict"] is True
    assert schema_config["name"] == "dialogue_analysis"
    schema = schema_config["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["properties"]) == {"intent", "evidence", "focus", "uncertain"}
    assert all("default" not in field for field in schema["properties"].values())
    assert schema["properties"]["intent"]["enum"] == DialogueAnalysis.model_json_schema()["properties"]["intent"]["enum"]
    # Generating the provider schema must not modify the local Pydantic model.
    assert DialogueAnalysis.model_json_schema()["properties"]["uncertain"]["default"] is False
    sent = json.dumps(body, ensure_ascii=False)
    for private in (GATEWAY_KEY, GENERIC_KEY, current["id"], "private-owner", "private-session-data", "private-system-notice"):
        assert private not in sent


@pytest.mark.parametrize("gateway_key", [None, "", "   "])
def test_gateway_can_use_explicit_generic_key_fallback(gateway, monkeypatch, gateway_key):
    if gateway_key is None:
        monkeypatch.delenv("AI_GATEWAY_API_KEY")
    else:
        monkeypatch.setenv("AI_GATEWAY_API_KEY", gateway_key)
    assert live.settings() == (GENERIC_KEY, live.VERCEL_BASE_URL, "test-creator/test-model")
    assert live.available()


@pytest.mark.parametrize("model", [None, "", "model-without-creator", "/model", "creator/", "creator/model/extra", "creator/model with spaces"])
def test_gateway_requires_explicit_model_slug(gateway, monkeypatch, model):
    if model is None:
        monkeypatch.delenv("LLM_MODEL")
    else:
        monkeypatch.setenv("LLM_MODEL", model)
    gateway(lambda request: pytest.fail("Unconfigured model must not send a request"))
    assert live.available() is False
    with pytest.raises(live.LiveError, match="creator/model"):
        live.analyze(session(), TEXT)


def test_gateway_requires_key_or_oidc(gateway, monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_API_KEY")
    monkeypatch.delenv("LLM_API_KEY")
    gateway(lambda request: pytest.fail("Missing key must not send a request"))
    assert live.available() is False
    with pytest.raises(live.LiveError, match="AI_GATEWAY_API_KEY"):
        live.analyze(session(), TEXT)


@pytest.mark.parametrize("gateway_key, generic_key, expected", [
    (GATEWAY_KEY, GENERIC_KEY, GATEWAY_KEY),
    ("", GENERIC_KEY, GENERIC_KEY),
    ("", "", "fake-short-lived-oidc"),
])
def test_gateway_oidc_fallback_and_key_priority(gateway, monkeypatch, gateway_key, generic_key, expected):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", gateway_key)
    monkeypatch.setenv("LLM_API_KEY", generic_key)
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "fake-short-lived-oidc")

    def handle(request):
        assert str(request.url) == "https://ai-gateway.vercel.sh/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer " + expected
        assert "fake-short-lived-oidc" not in request.content.decode()
        return httpx.Response(200, json=completion(ANALYSIS))

    gateway(handle)
    assert live.available()
    assert live.analyze(session(), TEXT).model_dump() == ANALYSIS


def test_generic_provider_does_not_use_oidc(gateway, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "generic")
    monkeypatch.delenv("LLM_API_KEY")
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "fake-short-lived-oidc")
    gateway(lambda request: pytest.fail("Generic endpoint must not receive OIDC"))
    assert live.available() is False
    with pytest.raises(live.LiveError, match="AI не подключён"):
        live.analyze(session(), TEXT)


@pytest.mark.parametrize("provider", [None, "generic", ""])
def test_generic_configuration_is_unchanged(gateway, monkeypatch, provider):
    if provider is None:
        monkeypatch.delenv("LLM_PROVIDER")
    else:
        monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LLM_MODEL", "generic-model")

    def handle(request):
        assert str(request.url) == "https://stale-provider.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer " + GENERIC_KEY
        assert json.loads(request.content)["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json=completion(ANALYSIS))

    gateway(handle)
    assert live.available()
    assert live.analyze(session(), TEXT).model_dump() == ANALYSIS


def test_unknown_provider_does_not_silently_use_generic(gateway, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "vercle")
    gateway(lambda request: pytest.fail("Unknown provider must not send a request"))
    assert live.available() is False
    with pytest.raises(live.LiveError, match="LLM_PROVIDER"):
        live.analyze(session(), TEXT)


@pytest.mark.parametrize("status, expected", [
    (401, "Ключ AI Gateway не принят"),
    (402, "баланс AI исчерпан"),
    (403, "Free Tier"),
    (429, "лимит частоты"),
    (500, "Сервис AI отклонил запрос"),
])
def test_gateway_errors_are_actionable_sanitized_and_do_not_retry(gateway, status, expected, caplog, capsys):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"retry-after": "30"}, json={"error": {"message": GATEWAY_KEY + " sensitive-upstream-data"}})

    gateway(handle)
    current = session()
    before = deepcopy(current)
    with pytest.raises(live.LiveError, match=expected) as error:
        live.analyze(current, TEXT)
    assert current == before
    assert len(calls) == 1
    assert "Сообщение не сохранено" in str(error.value)
    captured = capsys.readouterr()
    output = str(error.value) + caplog.text + captured.out + captured.err
    assert GATEWAY_KEY not in output
    assert "sensitive-upstream-data" not in output


@pytest.mark.parametrize("payload", [
    {**ANALYSIS, "evidence": "invented evidence"},
    {**ANALYSIS, "client_status": "accepted"},
    {**ANALYSIS, "uncertain": "false"},
])
def test_gateway_output_still_requires_local_semantic_validation(gateway, payload):
    gateway(lambda request: httpx.Response(200, json=completion(payload)))
    current = session()
    before = deepcopy(current)
    with pytest.raises(live.LiveError):
        live.analyze(current, TEXT)
    assert current == before


def test_gateway_transport_failure_is_sanitized_and_has_no_side_effect(gateway, caplog, capsys):
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout(GATEWAY_KEY, request=request)

    gateway(handle)
    current = session()
    before = deepcopy(current)
    with pytest.raises(live.LiveError) as error:
        live.analyze(current, TEXT)
    assert current == before
    assert len(calls) == 1
    assert error.value.__suppress_context__
    captured = capsys.readouterr()
    assert GATEWAY_KEY not in str(error.value) + caplog.text + captured.out + captured.err
