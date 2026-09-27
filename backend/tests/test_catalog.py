"""Catalogue publication, role boundaries and recoverable session starts."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend import engine, live
from backend.catalog import CaseContent, case_preview, install_catalog
from backend.catalog_store import CatalogStore, admin_case, published_case
from backend.locking import SessionLocks
from backend.repository import Repository
from backend.training import TrainingConfig, build_preview


CONFIG = {
    "industry": "it", "topic": "scope", "difficulty": "standard",
    "tone": "collaborative", "client_role": "project_lead", "goal": "deadline",
    "duration_minutes": 10, "format": "text", "response_seconds": 0,
}
CONTENT = {
    "practice_model": "conversation",
    "title": "Договориться о запуске CRM",
    "description": "Клиент добавляет новые задачи перед запуском CRM.",
    "briefing": "Вы отвечаете за запуск CRM. До сдачи осталось 15 рабочих дней. Обсудите объём с заказчиком.",
    "objective": "Согласовать выполнимые изменения и сохранить дату запуска.",
    "client_name": "Мария", "company": "Компания клиента",
    "opening": "Можем добавить новые отчёты и сохранить дату запуска?",
    "configuration": CONFIG,
}


class TestAccounts:
    """Test-only identity source. Production uses the actual account service."""

    __test__ = False

    def require_user(self, request):
        actor = request.headers.get("x-test-actor")
        if not actor:
            raise HTTPException(401, "Войдите в аккаунт.")
        request.state.owner = f"account:{actor}"
        return {"id": actor, "name": actor, "role": "admin" if actor == "editor" else "user"}

    def require_admin(self, request):
        user = self.require_user(request)
        if user["role"] != "admin":
            raise HTTPException(403, "Недостаточно прав.")
        return user


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "available", lambda: False)
    app = FastAPI()
    repo = Repository(tmp_path / "catalog.sqlite3")
    app.state.repository = repo

    @app.exception_handler(engine.RuleError)
    async def rule_error(request, error):
        return JSONResponse({"detail": error.detail}, status_code=error.status)

    @app.exception_handler(live.LiveError)
    async def live_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    install_catalog(app, repo, TestAccounts(), SessionLocks())
    with TestClient(app) as browser:
        yield browser


def create(client, content=None, action="create-1"):
    response = client.post("/api/admin/cases", headers={"x-test-actor": "editor"}, json={
        "client_action_id": action, "content": content or CONTENT,
    })
    assert response.status_code == 200, response.text
    return response.json()["item"]


def mutate(client, item, action, **body):
    return client.post(f"/api/admin/cases/{item['id']}" + (f"/{action}" if action else ""),
                       headers={"x-test-actor": "editor"}, json={"revision": item["revision"], **body})


def publish(client, item):
    response = mutate(client, item, "publish")
    assert response.status_code == 200, response.text
    return response.json()["item"]


def start(client, item, actor="learner", action="start-1", mode="demo"):
    headers = {"x-test-actor": actor} if actor else {}
    return client.post(f"/api/catalog/{item['id']}/start", headers=headers, json={
        "revision": item.get("published_revision") or item["revision"],
        "client_action_id": action, "mode": mode,
    })


def test_admin_role_required_for_every_mutation_and_preview(client):
    item = create(client)
    for actor, expected in [(None, 401), ("learner", 403)]:
        headers = {"x-test-actor": actor} if actor else {}
        assert client.get("/api/admin/cases", headers=headers).status_code == expected
        for path, body in [
            ("/api/admin/cases", {"content": CONTENT, "client_action_id": "unauthorized"}),
            ("/api/admin/cases/preview", {"content": CONTENT}),
            (f"/api/admin/cases/{item['id']}", {"content": CONTENT, "revision": 1}),
            *[(f"/api/admin/cases/{item['id']}/{action}", {"revision": 1}) for action in ("publish", "unpublish", "archive")],
        ]:
            assert client.post(path, json=body, headers=headers).status_code == expected
    assert client.app.state.catalog.get(item["id"])["revision"] == 1


def test_drafts_private_and_only_published_content_is_exposed(client):
    item = create(client)
    assert item["status"] == "draft"
    assert item["has_unpublished_changes"] is True
    assert client.get("/api/catalog").json() == {"items": []}
    assert client.get(f"/api/catalog/{item['id']}").status_code == 404
    assert start(client, item).status_code == 404
    item = publish(client, item)
    public_before = client.get(f"/api/catalog/{item['id']}").json()
    assert public_before["item"]["revision"] == 2
    assert public_before["preview"]["scenario"]["client_name"] == "Мария"
    assert "_created_by" not in str(public_before)
    assert "published_content" not in public_before["item"]
    changed = deepcopy(CONTENT) | {"title": "Секретный новый черновик"}
    item = mutate(client, item, "", content=changed).json()["item"]
    assert item["status"] == "published"
    assert item["has_unpublished_changes"] is True
    assert client.get(f"/api/catalog/{item['id']}").json() == public_before
    assert client.get("/api/catalog").json()["items"] == [public_before["item"]]
    item = publish(client, item)
    assert item["revision"] == 4
    assert item["has_unpublished_changes"] is False
    assert client.get(f"/api/catalog/{item['id']}").json()["item"]["content"]["title"] == changed["title"]


def test_new_published_preview_uses_semantic_options_and_no_cost_model(client):
    preview = client.post("/api/admin/cases/preview", headers={"x-test-actor": "editor"}, json={"content": CONTENT}).json()["preview"]
    baseline = build_preview(TrainingConfig(**CONFIG))
    for field in ("id", "baseline", "options", "constraints", "client_interest", "priorities"):
        assert preview["scenario"][field] == baseline["scenario"][field]
    assert preview["scenario"]["title"] == CONTENT["title"]
    assert preview["scenario"]["id"] == "scope"
    assert preview["scenario"]["practice_model"] == "conversation"
    assert preview["scenario"]["baseline"] is None
    assert preview["max_turns"] == 16
    changed = deepcopy(CONTENT) | {"opening": "Новая реплика клиента, которая меняет контекст разговора."}
    assert case_preview(changed)["context_key"] != preview["context_key"]
    assert case_preview(CONTENT)["context_key"] == preview["context_key"]


def test_stale_editor_and_stale_publication_cannot_overwrite(client):
    item = create(client)
    updated = mutate(client, item, "", content=CONTENT | {"title": "Новая версия ситуации"}).json()["item"]
    for action, body in [("", {"content": CONTENT}), ("publish", {}), ("unpublish", {}), ("archive", {})]:
        assert mutate(client, item, action, **body).status_code == 409
    assert client.app.state.catalog.get(item["id"])["content"] == updated["content"]
    published = publish(client, updated)
    assert start(client, item).status_code == 409
    assert start(client, published).status_code == 200


def test_create_dedup_remains_safe_after_edits_and_restart(client):
    first = create(client)
    assert create(client) == first
    changed = mutate(client, first, "", content=CONTENT | {"title": "Изменённая ситуация"}).json()["item"]
    assert create(client)["revision"] == changed["revision"]
    response = client.post("/api/admin/cases", headers={"x-test-actor": "editor"}, json={
        "client_action_id": "create-1", "content": CONTENT | {"title": "Другая ситуация"},
    })
    assert response.status_code == 409
    restarted = CatalogStore(Repository(client.app.state.repository.path))
    assert admin_case(restarted.get(first["id"])) == changed
    assert len(restarted.list()) == 1


def test_unpublish_and_archive_hide_case_but_existing_start_is_recoverable(client):
    item = publish(client, create(client))
    assert start(client, item, actor=None).status_code == 401
    initial = start(client, item)
    assert initial.status_code == 200
    session = initial.json()
    assert session["catalog_case_id"] == item["id"]
    assert session["catalog_revision"] == item["published_revision"]
    assert session["scenario"]["id"] == "scope"
    assert session["messages"][-1]["text"] == CONTENT["opening"]
    assert "_owner" not in session
    draft = mutate(client, item, "unpublish").json()["item"]
    assert client.get("/api/catalog").json()["items"] == []
    assert start(client, item).json() == session
    assert start(client, item, action="new-start").status_code == 404
    archived = mutate(client, draft, "archive").json()["item"]
    assert archived["status"] == "archived"
    assert start(client, item).json() == session
    assert client.get(f"/api/catalog/{item['id']}").status_code == 404
    edited = mutate(client, archived, "", content=CONTENT | {"title": "Восстановленная ситуация"}).json()["item"]
    assert edited["status"] == "archived"
    assert client.get("/api/catalog").json()["items"] == []
    restored = publish(client, edited)
    assert restored["status"] == "published"
    assert client.get(f"/api/catalog/{item['id']}").json()["item"]["content"]["title"] == "Восстановленная ситуация"


def test_start_idempotence_payload_conflict_and_account_isolation(client):
    item = publish(client, create(client))
    first = start(client, item).json()
    assert start(client, item).json() == first
    other = start(client, item, actor="other-user").json()
    assert other["id"] != first["id"]
    repo = client.app.state.repository
    assert repo.get(first["id"])["_owner"] == "account:learner"
    assert [value["id"] for value in repo.list("account:other-user")] == [other["id"]]
    assert start(client, item, mode="live").status_code == 409
    second_case = publish(client, create(client, action="create-2"))
    assert start(client, second_case).status_code == 409
    assert start(client, item, action="live-new", mode="live").status_code == 503
    assert len(repo.list("account:learner")) == 1


def test_running_conversation_stays_frozen_after_republication(client):
    item = publish(client, create(client))
    first = start(client, item).json()
    changed = deepcopy(CONTENT)
    changed.update({"title": "Другая ситуация со скидкой", "opening": "Давайте обсудим скидку и условия оплаты."})
    changed["configuration"].update(topic="discount", goal="budget")
    draft = mutate(client, item, "", content=changed).json()["item"]
    current = publish(client, draft)
    assert start(client, item).json() == first
    assert start(client, item, action="new-stale").status_code == 409
    second = start(client, current, action="new-current").json()
    assert second["scenario"]["id"] == "discount"
    assert second["context_key"] != first["context_key"]
    saved = client.app.state.repository.get(first["id"])
    reply = engine.process_message(saved, "Что для вас важнее всего?", "message-1")
    assert saved["scenario"] == first["scenario"]
    assert saved["scenario"]["client_interest"] in reply


def test_legacy_catalog_is_frozen_until_explicit_republication(client):
    content = {key: value for key, value in CONTENT.items() if key != "practice_model"}
    store = client.app.state.catalog
    legacy = store.create("pre-upgrade-case", content, "editor")
    legacy = store.mutate(legacy["id"], legacy["revision"], "publish")
    before = client.get(f"/api/catalog/{legacy['id']}").json()
    assert before["preview"]["scenario"]["baseline"]["price"] == 200000
    assert "practice_model" not in before["preview"]["scenario"]
    old = start(client, legacy).json()
    assert old["scenario"] == before["preview"]["scenario"]
    current = publish(client, legacy)
    assert current["content"]["practice_model"] == "conversation"
    after = client.get(f"/api/catalog/{legacy['id']}").json()
    assert after["preview"]["scenario"]["practice_model"] == "conversation"
    assert after["preview"]["scenario"]["baseline"] is None
    assert after["preview"]["context_key"] != before["preview"]["context_key"]
    assert start(client, legacy).json() == old
    assert client.app.state.repository.get(old["id"])["scenario"] == old["scenario"]


@pytest.mark.parametrize("patch", [
    {"title": "  "}, {"description": "short"}, {"briefing": "short"}, {"objective": "short"},
    {"client_name": ""}, {"opening": ""}, {"baseline": {"price": 1}},
    {"configuration": CONFIG | {"topic": "discount", "goal": "deadline"}},
    {"configuration": CONFIG | {"duration_minutes": True}},
])
def test_invalid_content_is_not_persisted(client, patch):
    response = client.post("/api/admin/cases", headers={"x-test-actor": "editor"}, json={
        "client_action_id": "invalid", "content": CONTENT | patch,
    })
    assert response.status_code == 422
    assert client.app.state.catalog.list() == []


def test_revision_does_not_accept_boolean_or_float(client):
    item = create(client)
    for revision in (True, 1.0, "1", 0):
        response = client.post(f"/api/admin/cases/{item['id']}/publish", headers={"x-test-actor": "editor"}, json={"revision": revision})
        assert response.status_code == 422


def test_sqlite_concurrent_edit_wins_once_across_store_instances(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    stores = [CatalogStore(Repository(path)), CatalogStore(Repository(path))]
    stores[0].create("case-id", CONTENT, "editor")
    barrier = Barrier(2)

    def edit(index):
        barrier.wait(timeout=5)
        try:
            return stores[index].mutate("case-id", 1, "edit", CONTENT | {"title": f"Правка номер {index}"})
        except engine.RuleError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(edit, range(2)))
    assert len([result for result in results if result == 409]) == 1
    winner = next(result for result in results if isinstance(result, dict))
    assert stores[0].get("case-id") == winner
    assert winner["revision"] == 2


def test_sqlite_concurrent_create_deduplicates_across_store_instances(tmp_path):
    path = tmp_path / "create.sqlite3"
    stores = [CatalogStore(Repository(path)), CatalogStore(Repository(path))]
    barrier = Barrier(2)

    def create_case(index):
        barrier.wait(timeout=5)
        return stores[index].create("stable-id", CONTENT, "editor")

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(create_case, range(2)))
    assert results[0] == results[1]
    assert len(stores[0].list()) == 1


def test_schema_is_lazy(tmp_path):
    repo = Repository(tmp_path / "lazy.sqlite3")
    store = CatalogStore(repo)
    with repo.connect() as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'catalog_cases'").fetchone() is None
    assert store.list() == []


def test_real_app_login_publish_student_practice_retry_and_owner_isolation(tmp_path, monkeypatch):
    """Exercise real cookie auth and root endpoint wiring, not the test stub."""
    from backend.app import create_app

    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.setattr(live, "available", lambda: False)
    app = create_app(tmp_path / "real-app.sqlite3")
    password = "catalog-test-only-password-27"
    app.state.accounts.store.create_user("manager", "Редактор", password, role="admin")
    with TestClient(app) as admin, TestClient(app) as student, TestClient(app) as stranger:
        assert admin.post("/api/auth/login", json={"username": "manager", "password": password}).status_code == 200
        for browser, username in ((student, "student"), (stranger, "stranger")):
            assert browser.post("/api/auth/register", json={"username": username, "display_name": username, "password": password}).status_code == 201
        assert student.get("/api/admin/cases").status_code == 403
        assert student.post("/api/admin/cases", json={"client_action_id": "forbidden", "content": CONTENT}).status_code == 403
        created = admin.post("/api/admin/cases", json={"client_action_id": "create", "content": CONTENT}).json()["item"]
        assert student.get("/api/catalog").json()["items"] == []
        item = admin.post(f"/api/admin/cases/{created['id']}/publish", json={"revision": created["revision"]}).json()["item"]
        assert len(student.get("/api/catalog").json()["items"]) == 1
        response = student.post(f"/api/catalog/{item['id']}/start", json={
            "revision": item["published_revision"], "client_action_id": "practice", "mode": "demo",
        })
        assert response.status_code == 200, response.text
        session = response.json()
        assert stranger.get(f"/api/sessions/{session['id']}").status_code == 404
        assert admin.get(f"/api/sessions/{session['id']}").status_code == 404
        assert student.post(f"/api/sessions/{session['id']}/messages", json={
            "text": "Что для вас важнее всего?", "client_message_id": "say-one",
        }).status_code == 200
        assert admin.post(f"/api/admin/cases/{item['id']}/archive", json={"revision": item["revision"]}).status_code == 200
        retry = student.post(f"/api/sessions/{session['id']}/retry", json={"client_action_id": "retry-one"})
        assert retry.status_code == 200, retry.text
        child = retry.json()
        assert child["catalog_case_id"] == session["catalog_case_id"]
        assert child["catalog_revision"] == session["catalog_revision"]
        assert child["scenario"] == session["scenario"]
        assert child["context_key"] == session["context_key"]
        assert stranger.get("/api/sessions").json()["sessions"] == []
        assert student.post("/api/auth/logout", json={}).status_code == 200
        assert student.get(f"/api/sessions/{session['id']}").status_code == 404
        assert student.post("/api/auth/login", json={"username": "student", "password": password}).status_code == 200
        assert len(student.get("/api/sessions").json()["sessions"]) == 2


# Reuse the existing explicit, isolated opt-in database fixture. It creates a
# unique schema and never touches the production/default PostgreSQL tables.
from backend.tests.test_postgres_integration import postgres_factory  # noqa: E402, F401


def test_postgres_catalog_roundtrip_publication_and_conflict(postgres_factory):
    first = CatalogStore(postgres_factory())
    created = first.create("catalog-pg", CONTENT, "editor")
    published = first.mutate(created["id"], 1, "publish")
    restarted = CatalogStore(postgres_factory())
    assert published_case(restarted.get(created["id"]))["content"] == CONTENT
    edited = restarted.mutate(created["id"], published["revision"], "edit", CONTENT | {"title": "Черновик в PostgreSQL"})
    assert published_case(first.get(created["id"]))["content"] == CONTENT
    with pytest.raises(engine.RuleError):
        first.mutate(created["id"], published["revision"], "publish")
    assert first.get(created["id"])["revision"] == edited["revision"]
