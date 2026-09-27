"""Personal practice facts, with cited observations and comparable attempts.

This module never infers a skill score, ranks people, or estimates time spent.
The full owner history supplies counts; only comparable conversation attempts
contribute to the visible observation group. Unknown old assistance is never
silently relabelled independent. All response fields are explicitly allowed.
"""

from datetime import datetime, timezone

from fastapi import Request

from . import live
from .feedback import _transcript, behavior_opportunities
from .mentor import state_for


SKILLS = (
    ("clarified_need", "Выяснение потребности"),
    ("justified_proposal", "Аргументация"),
    ("responded_to_objection", "Ответ на возражение"),
)


def _time(value):
    try:
        if not isinstance(value, str):
            return 0.0
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
    except (ValueError, OverflowError, OSError):
        return 0.0


def _completion_key(session):
    return (_time(session.get("completed_at") or session.get("created_at")), session["id"])


def _activity_key(session):
    stamps = [session.get("created_at"), session.get("completed_at")]
    stamps.extend(message.get("created_at") for message in session.get("messages", []) if isinstance(message, dict))
    return (max((_time(value) for value in stamps), default=0), session["id"])


def _conversation(session):
    return session.get("scenario", {}).get("practice_model") == "conversation"


def _assistance(session):
    try:
        state = state_for(session)
    except (ValueError, TypeError, AttributeError):
        return "unknown", None, None
    if state.get("tracking_started") is not True or state.get("tracked_from_start") is not True or state.get("mode") not in {"guided", "independent"}:
        return "unknown", None, None
    used = state["used"]
    category = "independent" if state["mode"] == "independent" and not used else "guided"
    return category, used, state["mode"]


def _summary(session):
    assistance, used, _ = _assistance(session)
    return {
        "session_id": session["id"],
        "title": session.get("scenario", {}).get("title", "Разговор"),
        "created_at": session.get("created_at"), "completed_at": session.get("completed_at"),
        "status": session["status"], "mode": session.get("mode", "demo"),
        "practice_model": "conversation" if _conversation(session) else "financial",
        "assistance": assistance, "mentor_used": used,
    }


def _evidence(session, candidates, transcript):
    result = []
    seen = set()
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        message_id, quote = candidate.get("message_id"), candidate.get("quote")
        reference = transcript.get(message_id) if isinstance(message_id, str) else None
        if not reference or not isinstance(quote, str) or not quote.strip():
            continue
        _, message = reference
        if message.get("role") != "user" or message.get("kind") == "proposal" or quote not in message["text"]:
            continue
        if (message_id, quote) in seen:
            continue
        seen.add((message_id, quote))
        result.append({
            "session_id": session["id"], "message_id": message_id, "quote": quote,
            "assistance": _assistance(session)[0], "title": session.get("scenario", {}).get("title", "Разговор"),
            "created_at": session.get("created_at"), "completed_at": session.get("completed_at"),
        })
    return result


def _observations(session):
    transcript = _transcript(session)
    feedback = session.get("feedback") or {}
    candidates = feedback.get("behaviors", [])
    behaviors = {item.get("id"): item for item in candidates if isinstance(item, dict)} if isinstance(candidates, list) else {}
    opportunities = behavior_opportunities(session, transcript)
    result = []
    for skill_id, label in SKILLS:
        saved = behaviors.get(skill_id)
        eligible = opportunities[skill_id] and isinstance(saved, dict) and saved.get("status") in {"observed", "not_observed"}
        evidence = _evidence(session, saved.get("evidence"), transcript) if eligible and saved["status"] == "observed" else []
        status = "observed" if evidence else "not_observed" if eligible else "not_practiced"
        result.append({"id": skill_id, "label": label, "status": status, "evidence": evidence})
    return result


def _comparison_key(session):
    context = session.get("context_key")
    assistance, used, mentor_mode = _assistance(session)
    if not isinstance(context, str) or not context or assistance == "unknown":
        return None
    # The same assistance label can hide unused guided mode and actual advice;
    # retain mode + used so those attempts are not compared as equivalent.
    return (context, session.get("mode", "demo"), session.get("reply_mode", "rules"), mentor_mode, used, session.get("_engine_version"), session.get("max_turns", 30), session.get("extra_turns", 0))


def _has_observation(session):
    return any(item["status"] == "observed" for item in _observations(session))


def _point(session):
    return _summary(session) | {"skills": _observations(session)}


def _aggregate_skills(group):
    observations = [_observations(session) for session in group]
    result = []
    for index, (skill_id, label) in enumerate(SKILLS):
        values = [items[index] for items in observations]
        observed = sum(item["status"] == "observed" for item in values)
        eligible = sum(item["status"] != "not_practiced" for item in values)
        evidence = [quote for item in values for quote in item["evidence"]][:3]
        result.append({
            "id": skill_id, "label": label,
            "status": "observed" if observed else "not_observed" if eligible else "not_practiced",
            "observed_count": observed, "eligible_count": eligible,
            "not_practiced_count": len(group) - eligible, "evidence": evidence,
        })
    return result


def _recommendation(conversations, ai_available):
    usable = [item for item in conversations if item.get("mode") != "live" or ai_available]
    active = sorted((item for item in usable if item["status"] == "active"), key=_activity_key, reverse=True)
    if active:
        return {"kind": "continue", "label": "Продолжить разговор", "reason": "У вас есть незавершённая тренировка. Продолжите её, чтобы получить разбор своих реплик.", "session_id": active[0]["id"]}
    completed = sorted((item for item in usable if item["status"] == "completed"), key=_completion_key, reverse=True)
    latest = next((item for item in completed if _has_observation(item)), None)
    if latest:
        # Retry uses the stored case snapshot and remains available even when
        # its catalogue entry was changed or archived after the first attempt.
        reason = (latest.get("feedback") or {}).get("next_step") or "Повторите ту же ситуацию и попробуйте другой способ уточнить интересы или объяснить свою позицию."
        return {"kind": "retry", "label": "Повторить ситуацию", "reason": reason, "session_id": latest["id"]}
    return {"kind": "start", "label": "Начать тренировку", "reason": "Выберите ситуацию и попробуйте разговор. После завершения здесь появятся наблюдения с примерами ваших реплик.", "session_id": None}


def build_progress(sessions, *, ai_available=False):
    """Aggregate only supplied owner-scoped records without changing any data."""
    latest_completed = max((session for session in sessions if session["status"] == "completed"), key=_completion_key, default=None)
    conversations = [session for session in sessions if _conversation(session)]
    completed = sorted((session for session in conversations if session["status"] == "completed"), key=_completion_key, reverse=True)
    current = completed[0] if completed else None
    key = _comparison_key(current) if current else None
    group = [session for session in completed if _comparison_key(session) == key] if key else [current] if current else []
    previous = group[1] if len(group) > 1 else None
    eligible = key is not None and previous is not None and _has_observation(current) and _has_observation(previous)
    if not current:
        reason = "Завершите разговор, чтобы появились наблюдения."
    elif key is None:
        reason = "В этой попытке нет полных данных о контексте или помощи. Сравнение с другими попытками недоступно."
    elif not eligible:
        reason = "Для сравнения нужны две попытки одной ситуации с наблюдениями, одинаковым режимом и одинаковыми условиями помощи."
    else:
        reason = "Одна ситуация, одинаковый режим и условия помощи. Сравниваются наблюдения в репликах, а не уровень навыка."
    assistance = {category: sum(_assistance(session)[0] == category for session in completed) for category in ("guided", "independent", "unknown")}
    # Missing context does not prove a distinct situation. Keep such attempts
    # in total history, but never manufacture unique contexts from their IDs.
    contexts = {session["context_key"] for session in conversations if isinstance(session.get("context_key"), str) and session["context_key"]}
    return {
        "scope": "all_owner_history",
        "summary": {
            "total": len(sessions), "completed": sum(session["status"] == "completed" for session in sessions),
            "active": sum(session["status"] == "active" for session in sessions),
            "conversation_completed": len(completed), "unique_situations": len(contexts),
            "legacy_completed": sum(session["status"] == "completed" and not _conversation(session) for session in sessions),
            "assistance": assistance,
        },
        "recent_practice": [_summary(session) for session in sorted(conversations, key=_activity_key, reverse=True)[:6]],
        "latest_completed": _summary(latest_completed) if latest_completed else None,
        "observation_scope": {
            "title": current.get("scenario", {}).get("title", "Разговор") if current else "Пока нет завершённых разговоров",
            "attempts": len(group), "comparable": key is not None and len(group) > 1,
            "reason": "Наблюдения по одной ситуации с одинаковым режимом и условиями помощи." if key else "Наблюдения только по последней попытке; сравнение недоступно." if current else "Начните с первой тренировки.",
        },
        "skills": _aggregate_skills(group),
        "comparison": {"eligible": eligible, "reason": reason, "previous": _point(previous) if eligible else None, "current": _point(current) if current else None},
        "recommendation": _recommendation(conversations, ai_available),
    }


def install_progress(app, repo):
    @app.get("/api/progress")
    def progress(request: Request):
        return build_progress(repo.list_all(request.state.owner), ai_available=live.available())
