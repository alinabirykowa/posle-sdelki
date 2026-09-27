"""Авторитетный движок: LLM не вычисляет деньги и не подтверждает условия."""

import math
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from .scenarios import get_scenario
from .dialogue import classify_demo, owns_interest_evidence, validate_analysis
from .feedback import build_dialogue_feedback
from .responses import message_reply
from .training import style_reply
from .coaching import conversation_choices
from . import conversation_practice
from .mentor import initial_state as initial_mentor_state, state_for as mentor_state_for


class RuleError(Exception):
    def __init__(self, detail, status=409):
        super().__init__(detail)
        self.detail, self.status = detail, status


def now():
    return datetime.now(timezone.utc).isoformat()


def add_message(session, role, text, kind="message"):
    message = {"id": str(uuid4()), "role": role, "text": text, "created_at": now(), "kind": kind}
    session["messages"].append(message)
    return message


def public(session):
    # Refresh starters for existing attempts too, without rewriting history.
    view = deepcopy(session)
    view["extra_turns"] = extra_turns_for(view)
    view["turn_limit"] = turn_limit(view)
    update_suggestions(view)
    view["mentor_state"] = mentor_state_for(view)
    if view["mentor_state"]["mode"] == "independent":
        view["reply_choices"] = []
        view["suggestions"] = []
        view["conversation_hint"] = ""
    return {key: value for key, value in view.items() if not key.startswith("_")}


def new_session(scenario_id, priority, difficulty, mode, owner="", *, scenario_snapshot=None, training_config=None, context_key=None, max_turns=None, reply_mode="rules"):
    try:
        scenario = deepcopy(scenario_snapshot) if scenario_snapshot is not None else get_scenario(scenario_id)
    except ValueError as error:
        raise RuleError(str(error), 422) from None
    if priority not in {item["id"] for item in scenario["priorities"]}:
        raise RuleError("Этот приоритет не подходит выбранному сценарию.", 422)
    session = {
        "id": str(uuid4()), "scenario": scenario, "priority": priority, "difficulty": difficulty,
        "mode": mode, "reply_mode": "generated" if mode == "live" and reply_mode == "generated" else "rules",
        "status": "active", "created_at": now(), "messages": [], "proposal": None,
        "feedback": None, "discovered_interests": [], "suggestions": [], "turns": 0,
        "_client_message_ids": {}, "_owner": owner,
        "_dialogue_events": [], "_proposal_events": [], "_engine_version": 2,
        "mentor_state": initial_mentor_state(), "_mentor_events": [],
        "extra_turns": 0,
    }
    if training_config is not None:
        session.update({
            "training_config": deepcopy(training_config), "context_key": context_key,
            "max_turns": max_turns, "generation_method": "template",
        })
    mode_text = "Деморежим: собеседник отвечает по подготовленным правилам, внешний AI не подключён." if mode == "demo" else "AI-режим: модель анализирует смысл ваших реплик. Ответы клиента и условия формируются по правилам учебного кейса."
    if session["reply_mode"] == "generated":
        mode_text = "AI-собеседник: модель анализирует ваши реплики и формулирует ответы клиента с учётом разговора. Контекст учебного кейса и переписка передаются AI-провайдеру. Модель может ошибаться; действующие условия показаны в карточке проекта."
    if conversation_practice.active(session):
        mode_text = mode_text.replace("действующие условия показаны в карточке проекта", "контекст показан в описании ситуации")
        notice = (
            "Деморежим: ответы подготовлены заранее. Пишите своими словами или используйте подсказки."
            if mode == "demo" else mode_text + " Обсуждайте подход своими словами; варианты решения позволяют отдельно получить реакцию клиента. Итог разговора вы подтверждаете при завершении."
        )
        add_message(session, "system", notice, "notice")
    else:
        add_message(session, "system", mode_text + " Договорённости фиксируются только через карточку предложения и кнопку завершения.", "notice")
    opening = scenario.get("opening") or (
        "Нам нужно добавить ещё несколько задач к сайту — примерно 40 часов. Хотелось бы сохранить дату запуска и цену. Сможете взять?"
        if scenario_id == "scope" else
        "Проект нравится, но хотелось бы уложиться в 120 тысяч вместо 180. Давайте оставим весь объём и просто снизим цену?"
    )
    if difficulty == "hard":
        opening += " Прежде чем обсуждать ваш вариант, хочу убедиться, что вы поняли, что для нас важно."
    add_message(session, "assistant", opening, "opening")
    update_suggestions(session)
    return session


def require_active(session):
    if session["status"] != "active":
        raise RuleError("Тренировка уже завершена. Начните повторную попытку.")


def extra_turns_for(session):
    value = session.get("extra_turns", 0)
    return value if type(value) is int and value >= 0 else 0


def turn_limit(session):
    """Keep the saved training limit intact; explicit extensions are separate."""
    base = session.get("max_turns", 30)
    if type(base) is not int or base < 1:
        base = 30
    return base + extra_turns_for(session)


def require_turn(session):
    require_active(session)
    limit = turn_limit(session)
    if session["turns"] >= limit:
        raise RuleError(f"Достигнут лимит в {limit} ходов. Посмотрите разбор или продолжите разговор ещё на 4 хода.")


def update_suggestions(session):
    if session["status"] == "completed":
        session["suggestions"] = []
    elif not session["discovered_interests"]:
        session["suggestions"] = ["Что для вас важнее всего в этом проекте?", "Почему именно это условие для вас важно?", "Какие ограничения нам нужно учесть?"]
    else:
        session["suggestions"] = ["Правильно ли я понял ваш приоритет?", "Давайте обсудим возможный компромисс.", "Какие задачи можно исключить из объёма?"]
    session["reply_choices"], session["conversation_hint"] = conversation_choices(session)


INTERESTS = {
    ("scope", "deadline"): "Дата запуска связана с рекламной кампанией. Важны 20 часов новых задач; 20 часов прежних можно убрать. Оставшиеся новые задачи сейчас не обязательны.",
    ("scope", "full_scope"): "Нужны все исходные и новые задачи. Перенос на 5 рабочих дней допустим; бюджет можно увеличить до 240 000 ₽, если полный объём будет явно зафиксирован.",
    ("discount", "budget"): "Весь бюджет — максимум 120 000 ₽. Самостоятельный сокращённый пакет на 80 часов подходит; остальные задачи можно исключить.",
    ("discount", "cashflow"): "Нужны все 120 часов работ. Общая цена 180 000 ₽ допустима, но при старте можно заплатить не больше 60 000 ₽. Остаток сможем оплатить после сдачи.",
}


def message_is_duplicate(session, text, client_message_id):
    """Check before a provider call, including retries of completed sessions."""
    existing = session["_client_message_ids"].get(client_message_id)
    if existing is not None:
        if existing != text:
            raise RuleError("Этот идентификатор уже использован для другой реплики.")
        return True
    require_turn(session)
    return False


def process_message(session, text, client_message_id, *, analysis=None):
    if message_is_duplicate(session, text, client_message_id):
        return None
    was_discovered = bool(session["discovered_interests"])
    source = "ai" if analysis is not None else "demo_rules"
    analysis = (
        validate_analysis(analysis.model_dump(), text) if analysis is not None
        else classify_demo(text, session["scenario"]["id"], was_discovered)
    )
    if analysis.intent == "ask_interest" and not owns_interest_evidence(text, analysis.evidence):
        # A quoted or disowned question must not unlock the client's priority,
        # even when a provider returns an otherwise valid semantic result.
        analysis = analysis.model_copy(update={"uncertain": True})
    message = add_message(session, "user", text)
    # The browser can reconcile a lost response after reloading without relying
    # on text equality (the same words may be intentionally sent twice).
    message["client_message_id"] = client_message_id
    session["_client_message_ids"][client_message_id] = text
    session["turns"] += 1
    session.setdefault("_dialogue_events", []).append({
        "message_id": message["id"], "source": source, **analysis.model_dump(),
    })
    interest = session["scenario"].get("client_interest") or (
        "Мне важно уточнить ожидаемый результат и ограничения обеих сторон."
        if conversation_practice.active(session) else INTERESTS[(session["scenario"]["id"], session["priority"])]
    )
    if analysis.intent == "ask_interest" and not analysis.uncertain:
        if interest not in session["discovered_interests"]:
            session["discovered_interests"].append(interest)
            session["_discovery_message_id"] = message["id"]
    update_suggestions(session)
    return style_reply(session.get("training_config"), message_reply(session, analysis, interest, was_discovered), session["turns"])


def proposal_verdict(session, option_id):
    if conversation_practice.active(session):
        return conversation_practice.proposal_verdict(session, option_id)
    scenario_id, priority = session["scenario"]["id"], session["priority"]
    unsafe = "accept_all" if scenario_id == "scope" else "discount_all"
    if option_id == unsafe:
        provider = "вашей команды" if session.get("training_config") else "студии"
        return True, f"Клиент принимает выгодные для него условия. Проверьте, можете ли вы исполнить своё обещание и соблюсти ограничения {provider}."
    if session["difficulty"] == "hard" and not session["discovered_interests"]:
        return False, "Клиент пока не готов согласовать вариант: сначала выясните его приоритет и ограничения вопросом."
    if scenario_id == "scope":
        if option_id == "prioritize_swap":
            return (True, "Для даты запуска подходит замена: 100 часов исходных и 20 часов новых задач. Всё остальное исключаем без обязательства сделать позже.") if priority == "deadline" else (False, "Нужен полный набор исходных и новых задач. Исключение работ не подходит.")
        if option_id in ("extend_deadline", "paid_change"):
            return (True, "Полный объём сохранён, перенос на 20 рабочих дней допустим. Указанная цена укладывается в предел 240 000 ₽.") if priority == "full_scope" else (False, "Дата запуска фиксирована: перенос до 20 рабочих дней не подходит, даже при сохранении всех работ.")
    if scenario_id == "discount":
        if option_id == "reduce_scope":
            return (True, "Цена 120 000 ₽ укладывается в весь бюджет. Принимаю самостоятельный пакет на 80 часов без обещания оставшихся работ.") if priority == "budget" else (False, "Мне нужны все 120 часов работ. Проблема в размере первого платежа, а не в общей цене.")
        if option_id == "staged_payment":
            return (True, "Аванс 54 000 ₽ укладывается в доступные 60 000 ₽. Полный объём и цена 180 000 ₽ подходят.") if priority == "cashflow" else (False, "Рассрочка не уменьшает общую сумму: бюджет всего проекта ограничен 120 000 ₽.")
        if option_id == "keep_terms":
            return False, "Исходные условия не решают ограничение: " + ("общая цена выше бюджета 120 000 ₽." if priority == "budget" else "аванс 90 000 ₽ выше доступных 60 000 ₽.")
    raise RuleError("В этом сценарии нет такого предложения.", 422)


def submit_proposal(session, option_id):
    require_turn(session)
    option = next((item for item in session["scenario"]["options"] if item["id"] == option_id), None)
    if option is None:
        raise RuleError("В этом сценарии нет такого предложения.", 422)
    accepted, reason = proposal_verdict(session, option_id)
    if session.get("training_config"):
        reason = reason.replace("даты запуска", "срока сдачи").replace("Дата запуска", "Дата сдачи")
    # Preserve the one verdict older sessions retained before replacing it.
    if "_proposal_events" not in session:
        session["_proposal_events"] = []
        if session.get("proposal") and session.get("_proposal_message_id"):
            session["_proposal_events"].append({
                **deepcopy(session["proposal"]), "message_id": session["_proposal_message_id"],
            })
    terms = option.get("terms")
    if conversation_practice.active(session):
        text = f"Предлагаю: {option['label']}. {option['description']}"
    else:
        price = f"{terms['price']:,}".replace(",", " ")
        text = f"Предлагаю: {option['label']}. Цена — {price} ₽; объём — {terms['hours']} ч; срок — {terms['deadline_days']} рабочих дней. {terms['scope']}. Оплата: {terms['payment']}."
    message = add_message(session, "user", text, "proposal")
    session["_proposal_message_id"] = message["id"]
    session["proposal"] = {"option_id": option_id, "label": option["label"], "terms": deepcopy(terms), "client_status": "accepted" if accepted else "rejected", "reason": reason}
    if conversation_practice.active(session):
        session["proposal"]["description"] = option["description"]
    session.setdefault("_proposal_events", []).append({
        "message_id": message["id"], "option_id": option_id,
        "client_status": "accepted" if accepted else "rejected",
        "reason": reason, "terms": deepcopy(terms),
        **({"description": option["description"]} if conversation_practice.active(session) else {}),
    })
    session["turns"] += 1
    update_suggestions(session)
    return style_reply(session.get("training_config"), ("Предложение принято. " if accepted else "Предложение отклонено. ") + reason, session["turns"])


def metrics_for(scenario, terms):
    available_hours = terms["deadline_days"] * terms["daily_capacity"]
    required_days = math.ceil(terms["hours"] / terms["daily_capacity"])
    direct_cost = terms["hours"] * terms["hourly_cost"]
    contribution = terms["price"] - direct_cost
    minimum = scenario.get("minimum_contribution", 0)
    delay = max(0, required_days - terms["deadline_days"])
    reasons = []
    if delay:
        reasons.append(f"Для {terms['hours']} ч нужно {required_days} рабочих дней при мощности {terms['daily_capacity']} ч/день. Обещано {terms['deadline_days']} дней: нехватка {max(0, terms['hours'] - available_hours)} ч.")
    if contribution < minimum:
        reasons.append(f"Остаток после прямых затрат {contribution:,} ₽ ниже допустимого лимита {minimum:,} ₽.".replace(",", " "))
    baseline = scenario["baseline"]
    return {
        "required_hours": terms["hours"], "available_hours": available_hours,
        "overflow_hours": max(0, terms["hours"] - available_hours), "required_days": required_days,
        "delay_days": delay, "direct_cost": direct_cost, "contribution": contribution,
        "baseline_contribution": baseline["price"] - baseline["hours"] * baseline["hourly_cost"],
        "minimum_contribution": minimum, "violation_reasons": reasons, "feasible": not reasons,
    }


def finish(session, outcome):
    if session["status"] == "completed":
        return session
    proposal = session["proposal"]
    if outcome == "agreement" and (not proposal or proposal["client_status"] != "accepted"):
        raise RuleError("Сначала отправьте предложение и получите согласие клиента. Или завершите разговор без соглашения.")
    agreed = outcome == "agreement"
    if conversation_practice.active(session):
        session["feedback"] = conversation_practice.feedback(session, agreed, build_dialogue_feedback(session))
        session["status"] = "completed"
        session["completed_at"] = now()
        session["_finish_outcome"] = outcome
        add_message(session, "system", "Разговор завершён с соглашением. Доступен разбор общения." if agreed else "Разговор завершён без соглашения. Доступен разбор общения.", "finish")
        update_suggestions(session)
        return session
    metrics = metrics_for(session["scenario"], proposal["terms"] if agreed else session["scenario"]["baseline"])
    dialogue = build_dialogue_feedback(session)
    strengths = dialogue["strengths"]
    improvements = dialogue["improvements"]
    if not agreed:
        title = "Разговор завершён без сделки"
        summary = "Новых обязательств нет. Отказ может быть правильным решением, если подходящего пакета нет. Результат исполнения не рассчитан; исходные условия сохранены только для справки."
        result = "no_agreement"
        next_step = "Повторите ситуацию, уточните ограничение клиента и проверьте один альтернативный пакет."
    elif metrics["feasible"]:
        title = "Договорённость можно выполнить"
        summary = "Клиент согласовал пакет, который проходит заданные ограничения срока и экономики. Это проверка учебной модели, а не гарантия исполнения реального проекта."
        result = "feasible"
        next_step = "Повторите разговор при тех же условиях: попробуйте другой переговорный подход или иной допустимый пакет."
        strengths.append("Зафиксированный пакет укладывается в ограничения сценария.")
    else:
        title = "Клиент согласился. Условия не проходят проверку"
        summary = " ".join(metrics["violation_reasons"]) + " Согласие клиента само по себе не делает обещание выполнимым."
        result = "infeasible"
        next_step = "Повторите разговор: выясните приоритет и измените связанный пакет объёма, срока, цены или оплаты."
        improvements.extend(metrics["violation_reasons"])
    if agreed and metrics["feasible"] and improvements:
        next_step = improvements[0]
    session["feedback"] = {
        "title": title, "summary": summary, "outcome": result, "metrics": metrics,
        "moments": dialogue["moments"], "behaviors": dialogue["behaviors"],
        "next_step": next_step, "strengths": strengths, "improvements": improvements,
    }
    session["status"] = "completed"
    session["completed_at"] = now()
    session["_finish_outcome"] = outcome
    add_message(session, "system", "Соглашение зафиксировано. Доступен разбор последствий." if agreed else "Разговор завершён без соглашения. Новых обязательств нет.", "finish")
    update_suggestions(session)
    return session
