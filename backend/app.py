"""FastAPI HTTP-слой. Запуск из корня: python -m uvicorn backend.app:app."""

import os
import re
import secrets
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from . import ai_conversation, engine, live
from .locking import SessionLocks
from .storage import StorageError, create_repository
from .scenarios import all_scenarios
from .training import PreviewBody, StartBody, build_preview, start_session_id
from .accounts import AUTH_COOKIE, check_same_origin, install_accounts
from .catalog import install_catalog
from .mentor import install_mentor
from .progress import install_progress
from .session_extension import install_session_extension

ROOT = Path(__file__).resolve().parents[1]
COOKIE_NAME = "posle_session_owner"


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scenario_id: str = Field(min_length=1, max_length=30)
    priority: str = Field(min_length=1, max_length=30)
    difficulty: Literal["standard", "hard"] = "standard"
    mode: Literal["demo", "live"] = "demo"


class MessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=2000)
    client_message_id: str = Field(min_length=1, max_length=100)


class ProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    option_id: str = Field(min_length=1, max_length=50)
    client_action_id: str | None = Field(default=None, min_length=1, max_length=100)


class RetryBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    client_action_id: str | None = Field(default=None, min_length=1, max_length=100)


class FinishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["agreement", "no_agreement"]


def create_app(db_path=None):
    app = FastAPI(title="После сделки", version="0.2.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    repo = create_repository(db_path)
    # Cloud workers must share the lock and transaction in PostgreSQL.
    session_locks = repo if hasattr(repo, "hold") else SessionLocks()
    app.state.repository = repo
    accounts = install_accounts(app, repo)
    app.state.accounts = accounts
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
        allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def anonymous_owner(request: Request, call_next):
        owner = request.cookies.get(COOKIE_NAME, "")
        new_owner = not re.fullmatch(r"[A-Za-z0-9_-]{43}", owner)
        if new_owner:
            owner = secrets.token_urlsafe(32)
        request.state.user = None
        if request.url.path.startswith("/api"):
            try:
                check_same_origin(request)
                raw_auth = request.cookies.get(AUTH_COOKIE)
                if raw_auth:
                    request.state.user = await run_in_threadpool(accounts.user_for_token, raw_auth)
            except HTTPException as error:
                return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers={"Cache-Control": "no-store"})
            except StorageError as error:
                return JSONResponse({"detail": str(error)}, status_code=503, headers={"Cache-Control": "no-store"})
        request.state.owner = "account:" + request.state.user["id"] if request.state.user else owner
        response = await call_next(request)
        if new_owner:
            response.set_cookie(COOKIE_NAME, owner, max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax", secure=os.environ.get("COOKIE_SECURE") == "1" or os.environ.get("VERCEL") == "1", path="/")
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "no-cache"
        return response

    @app.exception_handler(engine.RuleError)
    async def rule_error(request, error):
        return JSONResponse({"detail": error.detail}, status_code=error.status)

    @app.exception_handler(live.LiveError)
    async def live_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(StorageError)
    async def storage_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if request.url.path.startswith("/api/auth"):
            return JSONResponse({"detail": "Проверьте обязательные поля и допустимую длину текста. Пароль — от 10 до 128 символов; логин — от 3 до 80 латинских букв, цифр или символов . _ @ + -."}, status_code=422)
        if request.url.path.startswith(("/api/admin", "/api/catalog")):
            return JSONResponse({"detail": "Проверьте обязательные поля, длину текста и параметры ситуации. Сохраните актуальную версию перед публикацией."}, status_code=422)
        return JSONResponse({"detail": "Проверьте параметры запроса. Реплика должна содержать от 1 до 2000 символов; сценарий, режим и действие должны быть допустимыми."}, status_code=422)

    def owned(session_id, request):
        session = repo.get(session_id)
        if session is None or session.get("_owner") != request.state.owner:
            raise HTTPException(404, "Тренировка не найдена или недоступна этому пользователю.")
        return session

    def save_reply(session, engine_reply, kind):
        # Agreement/state changes are made only by the engine, never the prose.
        engine.add_message(session, "assistant", engine_reply, kind)
        repo.save(session)
        return engine.public(session)

    def recorded_action(session, action_id, kind, payload):
        if action_id is None:
            return None
        action = session.get("_client_action_ids", {}).get(action_id)
        if action is not None and (action.get("kind") != kind or action.get("payload") != payload):
            raise engine.RuleError("Этот идентификатор уже использован для другого действия. Повторите исходный запрос или создайте новый идентификатор.", 409)
        return action

    @app.get("/api/health")
    def health():
        return {"status": "ok", "live_available": live.available(), "live_reply_mode": live.reply_mode(), "default_mode": "demo"}

    @app.get("/api/scenarios")
    def scenarios():
        return {"scenarios": all_scenarios(), "live_available": live.available(), "live_reply_mode": live.reply_mode()}

    @app.post("/api/sessions")
    def create_session(body: CreateBody, request: Request):
        if body.mode == "live" and not live.available():
            raise live.LiveError("AI пока не подключён на сервере. Можно начать тренировку в явно обозначенном деморежиме.")
        session = engine.new_session(body.scenario_id, body.priority, body.difficulty, body.mode, request.state.owner, reply_mode=live.reply_mode())
        repo.save(session)
        return engine.public(session)

    @app.post("/api/training/preview")
    def training_preview(body: PreviewBody):
        return build_preview(body.configuration)

    @app.post("/api/training/start")
    def training_start(body: StartBody, request: Request):
        session_id = start_session_id(request.state.owner, body.client_action_id)
        payload = {"configuration": body.configuration.model_dump(), "mode": body.mode}
        if body.route_stage is not None:
            payload["route_stage"] = body.route_stage
        # The stable ID scopes deduplication to the browser owner, and the cloud
        # repository uses one transaction for this lock, read and insertion.
        with session_locks.hold(session_id):
            existing = repo.get(session_id)
            if existing is not None:
                if existing.get("_owner") != request.state.owner or existing.get("_start_payload") != payload:
                    raise engine.RuleError("Этот идентификатор запуска уже использован с другими параметрами. Создайте новый идентификатор.", 409)
                return engine.public(existing)
            if body.mode == "live" and not live.available():
                raise live.LiveError("AI пока не подключён на сервере. Можно начать тренировку в явно обозначенном деморежиме.")
            preview = build_preview(body.configuration)
            session = engine.new_session(
                body.configuration.topic, body.configuration.goal, body.configuration.difficulty,
                body.mode, request.state.owner, scenario_snapshot=preview["scenario"],
                training_config=preview["configuration"], context_key=preview["context_key"],
                max_turns=preview["max_turns"],
                reply_mode=live.reply_mode(),
                route_stage=body.route_stage,
            )
            session["id"] = session_id
            session["_start_payload"] = payload
            repo.save(session)
            return engine.public(session)

    @app.get("/api/sessions")
    def sessions(request: Request):
        return {"sessions": [engine.public(session) for session in repo.list(request.state.owner)]}

    @app.get("/api/sessions/{session_id}")
    def session_detail(session_id: str, request: Request):
        return engine.public(owned(session_id, request))

    @app.post("/api/sessions/{session_id}/messages")
    def message(session_id: str, body: MessageBody, request: Request):
        with session_locks.hold(session_id):
            session = owned(session_id, request)
            if engine.message_is_duplicate(session, body.text, body.client_message_id):
                return engine.public(session)
            # All changes remain private until both AI steps have succeeded.
            # A retry after an upstream failure can use the same message ID.
            session = deepcopy(session)
            analysis = live.analyze(session, body.text) if session["mode"] == "live" else None
            response = engine.process_message(session, body.text, body.client_message_id, analysis=analysis)
            if (session["mode"] == "live" and session.get("reply_mode") == "generated"
                    and not session.pop("_skip_generated_reply", False)):
                response = ai_conversation.generate_reply(session, response)
            return save_reply(session, response, "reply")

    @app.post("/api/sessions/{session_id}/proposal")
    def proposal(session_id: str, body: ProposalBody, request: Request):
        with session_locks.hold(session_id):
            session = owned(session_id, request)
            payload = {"option_id": body.option_id}
            if recorded_action(session, body.client_action_id, "proposal", payload) is not None:
                return engine.public(session)
            response = engine.submit_proposal(session, body.option_id)
            if body.client_action_id is not None:
                session.setdefault("_client_action_ids", {})[body.client_action_id] = {"kind": "proposal", "payload": payload}
                for message in session["messages"]:
                    if message["id"] == session["_proposal_message_id"]:
                        message["client_action_id"] = body.client_action_id
                        break
            return save_reply(session, response, "proposal_response")

    @app.post("/api/sessions/{session_id}/finish")
    def finish(session_id: str, body: FinishBody, request: Request):
        with session_locks.hold(session_id):
            session = owned(session_id, request)
            engine.finish(session, body.outcome)
            repo.save(session)
            return engine.public(session)

    @app.post("/api/sessions/{session_id}/retry")
    def retry(session_id: str, request: Request, body: RetryBody | None = None):
        with session_locks.hold(session_id):
            previous = owned(session_id, request)
            action_id = body.client_action_id if body is not None else None
            action = recorded_action(previous, action_id, "retry", {})
            if action is not None:
                return engine.public(owned(action["child_id"], request))
            if previous["mode"] == "live" and not live.available():
                raise live.LiveError("AI-соединение сейчас не настроено. Чтобы сменить режим, создайте отдельную тренировку в деморежиме.")
            snapshot = {}
            if previous.get("training_config"):
                snapshot = {
                    "scenario_snapshot": previous["scenario"], "training_config": previous["training_config"],
                    "context_key": previous["context_key"], "max_turns": previous["max_turns"],
                }
            session = engine.new_session(previous["scenario"]["id"], previous["priority"], previous["difficulty"], previous["mode"], request.state.owner, reply_mode=previous.get("reply_mode", "rules"), route_stage=previous.get("route_stage"), **snapshot)
            for key in ("catalog_case_id", "catalog_revision"):
                if key in previous:
                    session[key] = previous[key]
            session["retry_of"] = previous["id"]
            if action_id is not None:
                previous.setdefault("_client_action_ids", {})[action_id] = {"kind": "retry", "payload": {}, "child_id": session["id"]}
                repo.save_many([previous, session])
            else:
                repo.save(session)
            return engine.public(session)

    install_catalog(app, repo, accounts, session_locks)
    install_mentor(app, repo, session_locks, owned)
    install_progress(app, repo)
    install_session_extension(app, repo, session_locks, owned)

    # Build before starting the server. Vite dev uses its own proxy instead.
    dist = ROOT / "frontend" / "dist"
    if dist.is_dir() and (dist / "index.html").is_file():
        index_path = (dist / "index.html").resolve()
        index_content = index_path.read_bytes()
        # Deployment archives normalize mtimes; equal-sized HTML builds must
        # still have different validators when their asset references change.
        index_headers = {"ETag": f'"{sha256(index_content).hexdigest()}"'}
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def frontend(path: str):
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "Такого API-метода нет.")
            requested = (dist / path).resolve()
            if requested != index_path and requested.is_relative_to(dist.resolve()) and requested.is_file():
                return FileResponse(requested)
            return HTMLResponse(index_content, headers=index_headers)

    return app


app = create_app()
