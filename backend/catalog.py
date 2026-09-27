"""Role-protected editor and a shared catalogue of published training cases."""

import json
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from . import engine, live
from .catalog_store import CatalogStore, admin_case, content_digest, published_case
from .training import TrainingConfig, build_financial_preview, build_preview


class CaseContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    practice_model: Literal["conversation"] = "conversation"
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=400)
    briefing: str = Field(min_length=20, max_length=3000)
    objective: str = Field(min_length=10, max_length=1000)
    client_name: str = Field(min_length=1, max_length=80)
    company: str = Field(min_length=1, max_length=120)
    opening: str = Field(min_length=10, max_length=1000)
    configuration: TrainingConfig


class CasePreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: CaseContent


class CaseCreateBody(CasePreviewBody):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    client_action_id: str = Field(min_length=1, max_length=100)


class RevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)


class CaseEditBody(RevisionBody):
    content: CaseContent


class CaseStartBody(RevisionBody):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: Literal["demo", "live"] = "demo"
    client_action_id: str = Field(min_length=1, max_length=100)


def case_preview(content):
    legacy = isinstance(content, dict) and "practice_model" not in content
    content = content if isinstance(content, CaseContent) else CaseContent.model_validate(content)
    preview = (build_financial_preview if legacy else build_preview)(content.configuration)
    fields = content.model_dump(exclude={"configuration", "practice_model"})
    preview["scenario"].update(fields)
    # Keep the identity of existing published financial contexts stable. New
    # edits explicitly add practice_model and therefore receive a new context.
    canonical = content.model_dump(exclude={"practice_model"}) if legacy else content.model_dump()
    preview["context_key"] = "catalog-v1-" + content_digest(canonical)
    return preview


def catalogue_id(kind, owner, action_id):
    return str(uuid5(NAMESPACE_URL, json.dumps([f"posle/catalog/{kind}/v1", owner, action_id])))


def install_catalog(app, repo, accounts, session_locks):
    store = CatalogStore(repo)
    app.state.catalog = store

    @app.get("/api/catalog")
    def catalogue():
        return {"items": [published_case(item) for item in store.list() if item["status"] == "published"]}

    @app.get("/api/catalog/{case_id}")
    def catalogue_detail(case_id: str):
        item = published_case(store.get(case_id))
        return {"item": item, "preview": case_preview(item["content"])}

    @app.post("/api/catalog/{case_id}/start")
    def catalogue_start(case_id: str, body: CaseStartBody, request: Request):
        accounts.require_user(request)
        owner = request.state.owner
        session_id = catalogue_id("start", owner, body.client_action_id)
        payload = {"catalog_case_id": case_id, "revision": body.revision, "mode": body.mode}
        # Complete DDL before a pinned PostgreSQL session transaction starts.
        store.ensure_schema()
        with session_locks.hold(session_id):
            existing = repo.get(session_id)
            if existing is not None:
                if existing.get("_owner") != owner or existing.get("_start_payload") != payload:
                    raise engine.RuleError("Этот идентификатор запуска уже использован с другими параметрами. Создайте новый идентификатор.", 409)
                # A successful start remains recoverable after unpublication,
                # a new publication, archive, or an AI availability change.
                return engine.public(existing)
            item = published_case(store.get(case_id))
            if item["revision"] != body.revision:
                raise engine.RuleError("Ситуация обновлена. Откройте её заново и проверьте условия перед запуском.", 409)
            if body.mode == "live" and not live.available():
                raise live.LiveError("AI пока не подключён на сервере. Можно начать тренировку в явно обозначенном деморежиме.")
            preview = case_preview(item["content"])
            config = preview["configuration"]
            session = engine.new_session(
                config["topic"], config["goal"], config["difficulty"], body.mode, owner,
                scenario_snapshot=preview["scenario"], training_config=config,
                context_key=preview["context_key"], max_turns=preview["max_turns"], reply_mode=live.reply_mode(),
            )
            session.update({
                "id": session_id, "catalog_case_id": case_id, "catalog_revision": item["revision"],
                "_start_payload": payload,
            })
            repo.save(session)
            return engine.public(session)

    @app.get("/api/admin/cases")
    def admin_cases(request: Request):
        accounts.require_admin(request)
        return {"items": [admin_case(item) for item in store.list()]}

    @app.post("/api/admin/cases/preview")
    def preview_case(body: CasePreviewBody, request: Request):
        accounts.require_admin(request)
        return {"preview": case_preview(body.content)}

    @app.post("/api/admin/cases")
    def create_case(body: CaseCreateBody, request: Request):
        user = accounts.require_admin(request)
        case_id = catalogue_id("create", user["id"], body.client_action_id)
        item = store.create(case_id, body.content.model_dump(), user["id"])
        return {"item": admin_case(item)}

    @app.post("/api/admin/cases/{case_id}")
    def edit_case(case_id: str, body: CaseEditBody, request: Request):
        accounts.require_admin(request)
        return {"item": admin_case(store.mutate(case_id, body.revision, "edit", body.content.model_dump()))}

    @app.post("/api/admin/cases/{case_id}/publish")
    def publish_case(case_id: str, body: RevisionBody, request: Request):
        accounts.require_admin(request)
        current = store.get(case_id)
        if current is None:
            raise engine.RuleError("Ситуация не найдена.", 404)
        content = CaseContent.model_validate(current["content"]).model_dump()
        return {"item": admin_case(store.mutate(case_id, body.revision, "publish", content))}

    @app.post("/api/admin/cases/{case_id}/unpublish")
    def unpublish_case(case_id: str, body: RevisionBody, request: Request):
        accounts.require_admin(request)
        return {"item": admin_case(store.mutate(case_id, body.revision, "unpublish"))}

    @app.post("/api/admin/cases/{case_id}/archive")
    def archive_case(case_id: str, body: RevisionBody, request: Request):
        accounts.require_admin(request)
        return {"item": admin_case(store.mutate(case_id, body.revision, "archive"))}

    return store
