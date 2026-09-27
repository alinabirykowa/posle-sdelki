"""Owner-only, deterministic coaching kept separate from the client dialogue.

Advice is based on visible conversation state and validated transcript evidence.
It never reads the client's hidden goal, spends a turn, calls an AI provider or
changes deal state. Usage remains recorded when independent mode is enabled.
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .coaching import conversation_choices
from .feedback import review_utterance


class MentorBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["hint", "example", "review"]
    client_action_id: str = Field(min_length=1, max_length=100)
    message_id: str | None = Field(default=None, min_length=1, max_length=100)
    choice_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def action_fields(self):
        if (self.action == "review") != (self.message_id is not None):
            raise ValueError("Для разбора укажите реплику; другие действия не принимают message_id.")
        if self.choice_id is not None and self.action != "example":
            raise ValueError("Вариант фразы можно выбрать только для примера.")
        return self


class MentorModeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: Literal["guided", "independent"]
    client_action_id: str = Field(min_length=1, max_length=100)


def initial_state(*, tracked_from_start=True):
    return {
        "mode": "guided", "tracking_started": tracked_from_start,
        "tracked_from_start": tracked_from_start, "used": False,
        "counts": {"hint": 0, "example": 0, "review": 0}, "last_advice": None,
    }


def state_for(session):
    """A read-only public default never relabels an old attempt independent."""
    saved = session.get("mentor_state")
    if not isinstance(saved, dict):
        return initial_state(tracked_from_start=False)
    result = initial_state(tracked_from_start=False)
    result.update(deepcopy(saved))
    result["counts"] = {action: int(saved.get("counts", {}).get(action, 0)) for action in ("hint", "example", "review")}
    result["used"] = bool(saved.get("used") or any(result["counts"].values()))
    return result


def _hint(session):
    proposal = session.get("proposal")
    if proposal and proposal["client_status"] == "rejected":
        return "Разберите причину отказа", "Сначала уточните, что именно не подошло клиенту. Затем объясните, как следующий вариант учитывает это ограничение. Смена варианта сама по себе не заменяет объяснение."
    if proposal and proposal["client_status"] == "accepted":
        return "Сверьте общий смысл", "Коротко подведите итог своими словами и уточните следующий шаг. Согласие клиента ещё не показывает, одинаково ли вы поняли договорённость."
    if session.get("discovered_interests"):
        return "Свяжите предложение с интересом", "Опирайтесь на то, что клиент уже сообщил. Объясните, как ваш вариант помогает ему, и какой встречный шаг вы ожидаете."
    return "Начните с интереса клиента", "Уточните, что стоит за просьбой клиента и что для него особенно важно. Открытый вопрос даст больше оснований для предложения, чем догадка."


def _example_choice(session, choices):
    """Match the coaching stage, not the client's unrevealed answer key."""
    proposal = session.get("proposal")
    if proposal and proposal["client_status"] == "rejected":
        preferred = ("explore-rejection", "explore-flexibility")
        group = "explore"
    elif proposal and proposal["client_status"] == "accepted":
        preferred = ("respond-summary", "explore-terms", "respond-check")
        group = "respond"
    elif session.get("discovered_interests"):
        preferred = ("respond-reasoning", "negotiate-alternative", "negotiate-reciprocity")
        group = "negotiate"
    else:
        preferred = ("explore-priority", "explore-reason", "explore-constraint")
        group = "explore"
    for choice_id in preferred:
        match = next((item for item in choices if item["id"] == choice_id), None)
        if match:
            return match
    return next((item for item in choices if item["group"] == group), choices[0] if choices else None)


def _advice(session, body):
    # Import at call time: engine uses the small state helpers in this module.
    from .engine import RuleError

    advice = {
        "id": str(uuid4()), "action": body.action, "method": "rules",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "context_message_id": session["messages"][-1]["id"],
    }
    if body.action == "hint":
        advice["title"], advice["text"] = _hint(session)
    elif body.action == "example":
        choices, _ = conversation_choices(session)
        if body.choice_id:
            choice = next((item for item in choices if item["id"] == body.choice_id), None)
            if choice is None:
                raise RuleError("Этот пример уже изменился. Обновите разговор и выберите актуальную подсказку.", 409)
        else:
            choice = _example_choice(session, choices)
        if choice is None:
            raise RuleError("Сейчас пример недоступен. Продолжите своими словами.", 409)
        advice.update({
            "title": "Возможная формулировка", "text": "Это пример по текущему этапу разговора. Измените его под свою мысль; он не отправляется клиенту автоматически.",
            "example": choice["text"], "choice_id": choice["id"],
        })
    else:
        latest = next((item for item in reversed(session.get("messages", []))
                       if item.get("role") == "user" and item.get("kind", "message") == "message"), None)
        if latest is None or latest["id"] != body.message_id:
            raise RuleError("Можно разобрать только последнюю вашу свободную реплику. Карточка решения не считается репликой.", 422)
        observation = review_utterance(session, latest["id"])
        advice.update({"message_id": latest["id"], "title": "Разбор вашей реплики"})
        if observation["has_argument"]:
            advice.update({
                "text": "Вы связали предложение с причиной или пользой. Это наблюдение об аргументации, а не оценка её убедительности. Следом можно уточнить, подходит ли клиенту такая логика.",
                "observation": "argument", "evidence": observation["evidence"],
            })
        elif observation["has_question"]:
            advice.update({
                "text": "Вы задали вопрос по интересам или условиям разговора. Используйте ответ клиента, чтобы проверить своё понимание и связать с ним следующий вариант.",
                "observation": "question", "evidence": observation["evidence"],
            })
        else:
            advice.update({
                "text": "По этому разбору на правилах недостаточно оснований уверенно отметить вопрос или аргумент. Это не означает, что реплика неправильная. Проверьте: понятно ли из неё, что вы предлагаете и почему это важно для клиента?",
                "observation": "not_enough_evidence",
            })
    return advice


def install_mentor(app, repo, session_locks, owned):
    from . import engine

    def recorded(session, action_id, kind, payload):
        previous = session.get("_client_action_ids", {}).get(action_id)
        if previous is not None and (previous.get("kind") != kind or previous.get("payload") != payload):
            raise engine.RuleError("Этот идентификатор уже использован для другого действия. Повторите исходный запрос или создайте новый идентификатор.", 409)
        return previous

    @app.post("/api/sessions/{session_id}/mentor")
    def mentor(session_id: str, body: MentorBody, request: Request):
        payload = {"action": body.action, "message_id": body.message_id, "choice_id": body.choice_id}
        with session_locks.hold(session_id):
            session = owned(session_id, request)
            previous = recorded(session, body.client_action_id, "mentor", payload)
            if previous is not None:
                return {"session": engine.public(session), "advice": deepcopy(previous["advice"])}
            engine.require_active(session)
            state = state_for(session)
            if state["mode"] == "independent":
                raise engine.RuleError("В самостоятельном режиме наставник выключен. Включите режим с помощником, чтобы запросить совет.", 409)
            # Prepare all changes privately so a failed save returns no partial
            # event, counter, public advice, or changed client dialogue.
            session = deepcopy(session)
            advice = _advice(session, body)
            state["tracking_started"] = True
            state["used"] = True
            state["counts"][body.action] += 1
            state["last_advice"] = deepcopy(advice)
            session["mentor_state"] = state
            session.setdefault("_mentor_events", []).append({
                "kind": "advice", "client_action_id": body.client_action_id,
                "action": body.action, "advice": deepcopy(advice), "created_at": advice["created_at"],
            })
            session.setdefault("_client_action_ids", {})[body.client_action_id] = {"kind": "mentor", "payload": payload, "advice": deepcopy(advice)}
            repo.save(session)
            return {"session": engine.public(session), "advice": advice}

    @app.post("/api/sessions/{session_id}/mentor-mode")
    def mentor_mode(session_id: str, body: MentorModeBody, request: Request):
        payload = {"mode": body.mode}
        with session_locks.hold(session_id):
            session = owned(session_id, request)
            if recorded(session, body.client_action_id, "mentor-mode", payload) is not None:
                return {"session": engine.public(session)}
            engine.require_active(session)
            session = deepcopy(session)
            state = state_for(session)
            old_mode = state["mode"]
            state.update({"mode": body.mode, "tracking_started": True})
            session["mentor_state"] = state
            session.setdefault("_mentor_events", []).append({
                "kind": "mode", "client_action_id": body.client_action_id,
                "from": old_mode, "to": body.mode, "created_at": datetime.now(timezone.utc).isoformat(),
            })
            session.setdefault("_client_action_ids", {})[body.client_action_id] = {"kind": "mentor-mode", "payload": payload}
            repo.save(session)
            return {"session": engine.public(session)}
