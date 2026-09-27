"""Explicit, idempotent extra turns without changing the saved exercise.

Each block requires the previous limit to be reached. Replaying a successful
request recovers the session but never grants another block. The original
max_turns/context/training duration remain unchanged for honest comparisons.
"""

from copy import deepcopy

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from . import engine


EXTENSION_TURNS = 4


class ExtendBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    client_action_id: str = Field(min_length=1, max_length=100)


def install_session_extension(app, repo, session_locks, owned):
    @app.post("/api/sessions/{session_id}/extend")
    def extend(session_id: str, body: ExtendBody, request: Request):
        with session_locks.hold(session_id):
            session = owned(session_id, request)
            previous = session.get("_client_action_ids", {}).get(body.client_action_id)
            if previous is not None:
                if previous.get("kind") != "extend" or previous.get("payload") != {}:
                    raise engine.RuleError("Этот идентификатор уже использован для другого действия. Повторите исходный запрос или создайте новый идентификатор.")
                return {"session": engine.public(session)}
            engine.require_active(session)
            current_limit = engine.turn_limit(session)
            if session["turns"] < current_limit:
                raise engine.RuleError("Сначала используйте доступные ходы. Продолжить разговор можно после достижения текущего лимита.")
            # A failed save must not leave even a partial counter or action key.
            session = deepcopy(session)
            session["extra_turns"] = engine.extra_turns_for(session) + EXTENSION_TURNS
            session.setdefault("_extension_events", []).append({
                "client_action_id": body.client_action_id, "created_at": engine.now(),
                "turns": session["turns"], "from_limit": current_limit,
                "to_limit": engine.turn_limit(session), "added_turns": EXTENSION_TURNS,
            })
            session.setdefault("_client_action_ids", {})[body.client_action_id] = {"kind": "extend", "payload": {}}
            repo.save(session)
            return {"session": engine.public(session)}
