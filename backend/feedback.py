"""Evidence-based dialogue feedback; never infer a skill from the deal outcome.

The engine owns ``_dialogue_events`` and ``_proposal_events``. This module checks
their references against the saved transcript before quoting anything. It does
not calculate a score, reclassify conversation with a model, or mutate a session.
"""

import re


_INTENTS = {
    "ask_interest", "clarify", "justify", "object", "propose", "acknowledge",
    "off_topic", "instruction_override", "other",
}
_FOCUSES = {"interest", "constraint", "terms", "relationship", "none"}
_QUOTED = re.compile(
    r'```[\s\S]*?(?:```|$)|(?m:^\s*>[^\n]*)|«[^»]*(?:»|$)|„[^“]*(?:“|$)|'
    r'“[^”]*(?:”|$)|‘[^’]*(?:’|$)|"[^"]*(?:"|$)|\x27[^\x27]*(?:\x27|$)|`[^`]*(?:`|$)'
)
_TERMS = re.compile(r"цен|срок|объ[её]м|бюджет|аванс|плат[её]ж|оплат|задач|работ|запуск|пакет|услови|час|стоимост|дедлайн", re.I)
_REASON = re.compile(r"потому что|поскольку|так как|чтобы|позвол|сохран|сниз|уменьш|обеспеч|за сч[её]т|иначе|да[её]т|даст|удерж|успе|освобод|смож|не прид[её]тся", re.I)
_DENIED_REASON = re.compile(
    r"(?:не\s+(?:буду|стану|могу|хочу)\s+(?:вам\s+)?(?:объяснять|обосновывать|аргументировать))"
    r"|(?:не\s+(?:объясняю|обосновываю|аргументирую))"
    r"|(?:это\s+не\s+(?:аргумент|обоснование|объяснение))", re.I,
)
_DENIED_QUESTION = re.compile(
    r"\bне\s+(?:буду|стану|хочу|собираюсь)\s+(?:(?:вам|вас)\s+)?(?:спрашивать|выяснять|уточнять|узнавать|задавать)"
    r"|\bне\s+(?:спрашиваю|выясняю|уточняю|интересуюсь|задаю\s+вопрос)"
    r"|\bэто\s+не\s+вопрос|\bменя\s+не\s+интересует|\bмне\s+не\s*важно", re.I,
)
_QUESTION_CUE = re.compile(
    r"\?|\b(?:расскажите|уточните|объясните|поясните|подскажите|помогите понять|хочу понять|хотел[аи]? бы понять|позвольте узнать)\b"
    r"|^(?:(?:а|и|но|скажите|пожалуйста|тогда)\s*[, :]?\s*)*(?:что|чего|чем|как\w*|почему|зачем|насколько|сколько|когда|в ч[её]м|есть ли)\b", re.I,
)


def _transcript(session):
    """Ignore ambiguous IDs rather than quote the wrong speaker or occurrence."""
    result, duplicates = {}, set()
    for position, message in enumerate(session.get("messages", [])):
        if not isinstance(message, dict):
            continue
        message_id = message.get("id")
        if not isinstance(message_id, str) or not isinstance(message.get("text"), str):
            continue
        if message_id in result:
            duplicates.add(message_id)
        result[message_id] = (position, message)
    return {key: value for key, value in result.items() if key not in duplicates}


def _user_reference(transcript, message_id, proposal=False):
    if not isinstance(message_id, str) or message_id not in transcript:
        return None
    position, message = transcript[message_id]
    if message.get("role") != "user":
        return None
    is_proposal = message.get("kind") == "proposal"
    if is_proposal != proposal:
        return None
    return position, message


def _dialogue_events(session, transcript):
    result, seen = [], set()
    for event in session.get("_dialogue_events", []):
        if not isinstance(event, dict):
            continue
        reference = _user_reference(transcript, event.get("message_id"))
        if not reference or event.get("uncertain") is not False:
            continue
        if event.get("source") not in {"demo_rules", "ai"}:
            continue
        if event.get("intent") not in _INTENTS or event.get("focus") not in _FOCUSES:
            continue
        position, message = reference
        evidence = event.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip() or evidence not in message["text"]:
            continue
        # One authoritative interpretation per turn; duplicate records do not add credit.
        if message["id"] in seen:
            continue
        seen.add(message["id"])
        result.append({**event, "position": position, "message": message})
    return sorted(result, key=lambda item: item["position"])


def _proposal_events(session, transcript):
    candidates = list(session.get("_proposal_events", []))
    proposal = session.get("proposal")
    if isinstance(proposal, dict) and session.get("_proposal_message_id"):
        candidates.append({**proposal, "message_id": session["_proposal_message_id"]})
    result, seen = [], set()
    for event in candidates:
        if not isinstance(event, dict):
            continue
        reference = _user_reference(transcript, event.get("message_id"), proposal=True)
        if not reference or event.get("client_status") not in {"accepted", "rejected"}:
            continue
        semantic = session.get("scenario", {}).get("practice_model") == "conversation"
        valid_content = (
            isinstance(event.get("description"), str) and bool(event["description"].strip())
            if semantic else isinstance(event.get("terms"), dict)
        )
        if not isinstance(event.get("option_id"), str) or not valid_content:
            continue
        if not isinstance(event.get("reason"), str):
            continue
        position, message = reference
        if message["id"] in seen:
            continue
        seen.add(message["id"])
        result.append({**event, "position": position, "message": message})
    return sorted(result, key=lambda item: item["position"])


def behavior_opportunities(session, transcript=None):
    """Whether saved turns gave each behavior an observable practice window."""
    transcript = _transcript(session) if transcript is None else transcript
    free_positions = [position for position, message in transcript.values() if message.get("role") == "user" and message.get("kind") != "proposal"]
    proposal_positions = sorted(position for position, message in transcript.values() if message.get("role") == "user" and message.get("kind") == "proposal")
    refusal_reply = False
    for event in _proposal_events(session, transcript):
        if event["client_status"] != "rejected":
            continue
        next_proposal = next((position for position in proposal_positions if position > event["position"]), float("inf"))
        if any(event["position"] < position < next_proposal for position in free_positions):
            refusal_reply = True
            break
    return {
        "clarified_need": bool(free_positions),
        "justified_proposal": bool(free_positions),
        "responded_to_objection": refusal_reply,
    }


def _evidence(event):
    return {"message_id": event["message"]["id"], "quote": event.get("evidence", event["message"]["text"])}


def _own_evidence(event):
    """Remove quotation spans using the full message, not the classifier's span.

    An extracted span can omit the surrounding quotation marks. Checking only
    that substring would incorrectly credit a quoted third-party argument.
    """
    text, evidence = event["message"]["text"], event["evidence"]
    quotation_spans = [(item.start(), item.end()) for item in _QUOTED.finditer(text)]
    start, candidates = text.find(evidence), []
    while start != -1:
        characters = list(evidence)
        for quote_start, quote_end in quotation_spans:
            for index in range(max(start, quote_start), min(start + len(evidence), quote_end)):
                characters[index - start] = " "
        candidates.append("".join(characters).strip())
        start = text.find(evidence, start + 1)
    return max(candidates, key=len, default="")


def _justifies(event, proposals):
    # One spoken sentence can both propose an approach and explain its value.
    # Credit the explanation only after the same evidence/quotation/negation
    # checks as a dedicated justification. Proposal cards never reach here.
    if event.get("delivery_tone") == "hostile":
        return False
    if event["intent"] not in {"justify", "propose"} or event["focus"] not in {"terms", "constraint", "interest"}:
        return False
    # Quoting a client's argument or saying "I will not explain" is not the
    # participant's justification, even if a classifier supplied that label.
    unquoted = _own_evidence(event)
    if len(unquoted.split()) < 4 or _DENIED_REASON.search(_QUOTED.sub(" ", event["message"]["text"])):
        return False
    if not _REASON.search(unquoted):
        return False
    return bool(_TERMS.search(unquoted) or any(item["position"] < event["position"] for item in proposals))


def _asks_own_question(event):
    if event.get("delivery_tone") == "hostile":
        return False
    unquoted = _own_evidence(event)
    if len(unquoted.split()) < 2 or _DENIED_QUESTION.search(_QUOTED.sub(" ", event["message"]["text"])):
        return False
    return bool(_QUESTION_CUE.search(unquoted))


def _moment(event, title, explanation):
    return {"title": title, **_evidence(event), "explanation": explanation}


def review_utterance(session, message_id):
    """Narrow evidence for a coach, using the same guards as final feedback."""
    transcript = _transcript(session)
    event = next((item for item in _dialogue_events(session, transcript) if item["message_id"] == message_id), None)
    if event is None:
        return {"has_argument": False, "has_question": False, "evidence": None}
    argument = _justifies(event, _proposal_events(session, transcript))
    question = event["intent"] in {"ask_interest", "clarify"} and event["focus"] in {"interest", "constraint", "terms"} and _asks_own_question(event)
    return {"has_argument": argument, "has_question": question, "evidence": _evidence(event) if argument or question else None}


def build_dialogue_feedback(session):
    """Return moments, behaviors, strengths and improvements from saved evidence.

    ``not_observed`` means that this attempt contains insufficient evidence, not
    that the participant lacks the skill. Legacy sessions can only demonstrate
    a saved discovery question and the last saved proposal.
    """
    transcript = _transcript(session)
    opportunities = behavior_opportunities(session, transcript)
    dialogue = _dialogue_events(session, transcript)
    proposals = _proposal_events(session, transcript)
    # Even an old proposal whose verdict was not persisted still establishes
    # when the participant first offered terms. Never invent its acceptance.
    proposal_turns = sorted(
        ({"position": position, "message": message} for position, message in transcript.values()
         if message.get("role") == "user" and message.get("kind") == "proposal"),
        key=lambda item: item["position"],
    )
    interests = [item for item in session.get("discovered_interests", []) if isinstance(item, str) and item.strip()]
    discovery = None
    legacy = _user_reference(transcript, session.get("_discovery_message_id"))
    if legacy and interests:
        position, message = legacy
        matching = next((event for event in dialogue if event["message_id"] == message["id"]), None)
        if matching:
            if matching["intent"] in {"ask_interest", "clarify"} and matching["focus"] in {"interest", "constraint"} and _asks_own_question(matching):
                discovery = matching
        else:
            version = session.get("_engine_version", 1)
            modern = isinstance(version, (int, float)) and version >= 2
            recorded = any(isinstance(event, dict) and event.get("message_id") == message["id"] for event in session.get("_dialogue_events", []))
            candidate = {"position": position, "message": message, "evidence": message["text"]}
            if not modern and not recorded and _asks_own_question(candidate):
                discovery = candidate
    # The saved discovery turn is authoritative when available. A previous
    # classified question may have failed to reveal the client's actual need.
    if interests and discovery is None and not session.get("_discovery_message_id"):
        for event in dialogue:
            if event["intent"] in {"ask_interest", "clarify"} and event["focus"] in {"interest", "constraint"} and _asks_own_question(event):
                discovery = event
                break
    justified = next((item for item in dialogue if _justifies(item, proposal_turns)), None)
    rejected = [item for item in proposals if item["client_status"] == "rejected"]
    response, response_rejection = None, None
    for refusal in rejected:
        # An utterance after a later proposal cannot explain the response to the
        # earlier refusal. Evaluate each refusal's immediate negotiation window.
        next_position = next((item["position"] for item in proposal_turns if item["position"] > refusal["position"]), float("inf"))
        for event in dialogue:
            if not refusal["position"] < event["position"] < next_position:
                continue
            question = event["intent"] in {"ask_interest", "clarify"} and event["focus"] in {"interest", "constraint", "terms"} and _asks_own_question(event)
            if question or _justifies(event, proposal_turns):
                response, response_rejection = event, refusal
                break
        if response:
            break
    first_proposal = proposal_turns[0] if proposal_turns else None
    last_proposal = proposals[-1] if proposals else None
    late_discovery = bool(discovery and first_proposal and discovery["position"] > first_proposal["position"])
    discovery_explanation = "В этой попытке нет подтверждённого вопроса, раскрывшего потребность клиента. Это не оценка ваших способностей."
    if discovery:
        timing = "после первого предложения" if late_discovery else ("до первого предложения" if first_proposal else "в ходе разговора")
        discovery_explanation = f"Вы уточнили потребность {timing}. Зафиксированное ограничение клиента: {interests[0]}"
    justified_explanation = (
        "В собственной реплике вы связали условия с причиной или пользой. Это свидетельство аргументации, а не доказательство её убедительности."
        if justified else
        "Не найдено подтверждённого объяснения, почему предложенные условия подходят клиенту. Отправка карточки сама по себе не считается аргументацией."
    )
    response_explanation = (
        "После отказа и до следующего предложения вы вернулись к его причине через уточнение или аргумент по условиям. Причина отказа: " + response_rejection["reason"]
        if response else
        ("После отказа не зафиксирован содержательный ответ по условиям. Смена карточки учитывается отдельно и не доказывает навык работы с возражением."
         if opportunities["responded_to_objection"] else
         "После отказа не было свободной реплики до следующего предложения или завершения. Работа с возражением в этой попытке не проверялась."
         if rejected else "Нет сохранённого отказа по предложению, на котором можно проверить ответ участника: работа с возражением в этой попытке не проверялась.")
    )
    behaviors = [
        {"id": "clarified_need", "label": "Выяснение потребности", "status": "observed" if discovery else "not_observed", "evidence": [_evidence(discovery)] if discovery else [], "explanation": discovery_explanation},
        {"id": "justified_proposal", "label": "Аргументация предложения", "status": "observed" if justified else "not_observed", "evidence": [_evidence(justified)] if justified else [], "explanation": justified_explanation},
        {"id": "responded_to_objection", "label": "Ответ на возражение", "status": "observed" if response else "not_observed", "evidence": [_evidence(response)] if response else [], "explanation": response_explanation},
    ]
    for behavior in behaviors:
        behavior["eligible"] = opportunities[behavior["id"]]
    strengths, improvements, candidates = [], [], []
    if discovery:
        strengths.append("Вы уточнили потребность клиента " + ("после первого предложения." if late_discovery else ("до первого предложения." if first_proposal else "в ходе разговора.")))
        candidates.append((2, discovery, _moment(discovery, "Уточнили потребность", discovery_explanation)))
        if late_discovery:
            improvements.append("В следующей попытке уточните потребность до первого предложения, чтобы выбирать пакет с учётом ограничения клиента.")
    else:
        improvements.append("До выбора пакета уточните, какой результат и ограничения важны клиенту.")
    if justified:
        strengths.append("Вы объяснили связь условий с причиной или пользой для клиента.")
        candidates.append((4, justified, _moment(justified, "Объяснили предложение", justified_explanation)))
    else:
        improvements.append("Объясните своими словами, почему предлагаемые условия решают задачу клиента; одной карточки условий недостаточно для такого вывода.")
    if response:
        strengths.append("После отказа вы уточнили ограничение или привели аргумент по условиям.")
        candidates.append((3, response, _moment(response, "Вернулись к причине отказа", response_explanation)))
    elif opportunities["responded_to_objection"]:
        improvements.append("После отказа уточните причину или объясните, как новый вариант учитывает ограничение клиента.")
    if last_proposal:
        strengths.append("Вы сформулировали конкретный подход к решению." if session.get("scenario", {}).get("practice_model") == "conversation" else "Вы зафиксировали конкретный пакет цены, объёма и срока.")
        previous_refusal = next((item for item in reversed(rejected) if item["position"] < last_proposal["position"] and item["option_id"] != last_proposal["option_id"]), None)
        adjusted = last_proposal["client_status"] == "accepted" and previous_refusal is not None
        title = "Изменили пакет после отказа" if adjusted else ("Клиент принял предложение" if last_proposal["client_status"] == "accepted" else "Клиент отклонил предложение")
        explanation = last_proposal["reason"]
        if adjusted:
            explanation = "После отклонённого пакета вы отправили другой, и клиент его принял. Это факт изменения условий, а не самостоятельная оценка переговорного навыка. " + explanation
            strengths.append("После отказа вы изменили пакет; клиент принял новый вариант.")
            candidates.append((1, previous_refusal, _moment(previous_refusal, "Получили отказ", previous_refusal["reason"])))
        candidates.append((0, last_proposal, _moment(last_proposal, title, explanation)))
    # Retain the final proposal and its relevant refusal, then supporting spoken
    # evidence; render chronologically with at most one quote per message.
    chosen, seen = [], set()
    for _, event, moment in sorted(candidates, key=lambda item: item[0]):
        if event["message"]["id"] not in seen:
            chosen.append((event["position"], moment))
            seen.add(event["message"]["id"])
        if len(chosen) == 5:
            break
    return {"moments": [item[1] for item in sorted(chosen, key=lambda item: item[0])], "behaviors": behaviors, "strengths": strengths, "improvements": improvements}
