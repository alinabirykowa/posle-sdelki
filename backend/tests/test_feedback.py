from copy import deepcopy

import pytest

from backend.feedback import build_dialogue_feedback


@pytest.fixture
def session():
    return {"messages": [], "discovered_interests": [], "_dialogue_events": [], "_proposal_events": [], "proposal": None}


def say(session, text, intent="other", focus="none", *, role="user", kind="message", evidence=None, uncertain=False, source="demo_rules"):
    message = {"id": f"m{len(session['messages'])}", "role": role, "kind": kind, "text": text}
    session["messages"].append(message)
    session["_dialogue_events"].append({"message_id": message["id"], "intent": intent, "focus": focus, "evidence": text if evidence is None else evidence, "source": source, "uncertain": uncertain})
    return message


def proposal(session, option="first", status="accepted", reason="Условия подходят."):
    message = {"id": f"m{len(session['messages'])}", "role": "user", "kind": "proposal", "text": f"Предлагаю пакет {option}: цена 120 000 ₽, срок 15 дней, объём 80 ч."}
    session["messages"].append(message)
    value = {"option_id": option, "client_status": status, "reason": reason, "terms": {"price": 120000, "hours": 80, "deadline_days": 15}}
    session["proposal"] = value
    session["_proposal_message_id"] = message["id"]
    session["_proposal_events"].append({**value, "message_id": message["id"]})
    return message


def discover(session, text="Что для вас важнее — дата запуска или полный объём?"):
    message = say(session, text, "ask_interest", "interest")
    session["discovered_interests"] = ["Дата запуска фиксирована рекламной кампанией."]
    session["_discovery_message_id"] = message["id"]
    return message


def behaviors(result):
    return {item["id"]: item for item in result["behaviors"]}


def test_empty_attempt_does_not_invent_observations(session):
    result = build_dialogue_feedback(session)
    assert all(item["status"] == "not_observed" and item["evidence"] == [] for item in result["behaviors"])
    assert result["moments"] == []
    assert result["strengths"] == []
    assert "не проверялась" in behaviors(result)["responded_to_objection"]["explanation"]
    assert not any("отказа" in item for item in result["improvements"])


def test_before_and_after_first_proposal_are_distinguished(session):
    proposal(session, status="rejected")
    discovery = discover(session)
    proposal(session, "second")
    result = build_dialogue_feedback(session)
    observed = behaviors(result)["clarified_need"]
    assert observed["status"] == "observed"
    assert "после первого предложения" in observed["explanation"]
    assert not any("до первого предложения" in item for item in result["strengths"])
    assert any("до первого предложения" in item for item in result["improvements"])
    assert observed["evidence"] == [{"message_id": discovery["id"], "quote": discovery["text"]}]


def test_discovery_before_first_proposal_is_supported_by_chronology(session):
    discover(session)
    proposal(session)
    result = build_dialogue_feedback(session)
    assert "до первого предложения" in behaviors(result)["clarified_need"]["explanation"]
    assert not any("В следующей попытке" in item for item in result["improvements"])


def test_recorded_discovery_takes_precedence_over_earlier_classified_question(session):
    say(session, "Что для вас важно?", "ask_interest", "interest")
    proposal(session, status="rejected")
    actual_discovery = discover(session, "Почему перенос запуска не подходит?")
    result = build_dialogue_feedback(session)
    observed = behaviors(result)["clarified_need"]
    assert observed["evidence"][0]["message_id"] == actual_discovery["id"]
    assert "после первого предложения" in observed["explanation"]


def test_question_does_not_claim_unrecorded_discovery(session):
    say(session, "Что для вас важнее?", "ask_interest", "interest")
    assert behaviors(build_dialogue_feedback(session))["clarified_need"]["status"] == "not_observed"


@pytest.mark.parametrize("intent", ["justify", "propose"])
def test_proposal_card_never_counts_as_spoken_argument(session, intent):
    offered = proposal(session)
    session["_dialogue_events"].append({"message_id": offered["id"], "intent": intent, "focus": "terms", "evidence": offered["text"], "source": "ai", "uncertain": False})
    result = build_dialogue_feedback(session)
    assert behaviors(result)["justified_proposal"]["status"] == "not_observed"
    assert result["moments"][-1]["quote"] == offered["text"]


def test_actual_argument_keeps_exact_span_and_reference(session):
    evidence = "Сократим объём, чтобы сохранить дату запуска."
    message = say(session, "Спасибо. " + evidence, "justify", "terms", evidence=evidence)
    proposal(session)
    observed = behaviors(build_dialogue_feedback(session))["justified_proposal"]
    assert observed["status"] == "observed"
    assert observed["evidence"] == [{"message_id": message["id"], "quote": evidence}]


@pytest.mark.parametrize("text,evidence", [
    ("Потому что.", None),
    ("Я не буду объяснять, почему цена ниже, потому что так захотелось.", None),
    ("Клиент сказал: «Сократим объём, чтобы сохранить дату запуска».", "Сократим объём, чтобы сохранить дату запуска"),
    ('Я прочитал "Сократим объём, чтобы сохранить дату запуска".', None),
    ("Сократим объём, чтобы сохранить дату запуска — это не аргумент.", "Сократим объём, чтобы сохранить дату запуска"),
    ("> Сократим объём, чтобы сохранить дату запуска.\nЭто цитата из примера.", "Сократим объём, чтобы сохранить дату запуска."),
])
@pytest.mark.parametrize("intent", ["justify", "propose"])
def test_quoted_or_denied_reason_is_not_credited(session, text, evidence, intent):
    say(session, text, intent, "terms", evidence=evidence)
    assert behaviors(build_dialogue_feedback(session))["justified_proposal"]["status"] == "not_observed"


def test_proposal_without_reason_does_not_count_as_justification(session):
    say(session, "Предлагаю оставить только необходимые задачи.", "propose", "terms")
    assert behaviors(build_dialogue_feedback(session))["justified_proposal"]["status"] == "not_observed"


@pytest.mark.parametrize("changes", [
    {"message_id": "missing"}, {"evidence": "Выдуманная цитата"}, {"evidence": ""},
    {"uncertain": True}, {"source": "untrusted"}, {"intent": "invented"}, {"focus": "invented"},
])
def test_invalid_event_is_ignored(session, changes):
    say(session, "Сократим объём, чтобы сохранить дату запуска.", "justify", "terms")
    session["_dialogue_events"][0].update(changes)
    assert behaviors(build_dialogue_feedback(session))["justified_proposal"]["status"] == "not_observed"


@pytest.mark.parametrize("role", ["assistant", "system"])
def test_other_speakers_cannot_be_evidence(session, role):
    message = say(session, "Сократим объём, чтобы сохранить дату запуска.", "justify", "terms", role=role)
    session["_discovery_message_id"] = message["id"]
    session["discovered_interests"] = ["Сохранить дату запуска."]
    result = build_dialogue_feedback(session)
    assert result["moments"] == []
    assert all(item["status"] == "not_observed" for item in result["behaviors"])


def test_duplicate_message_id_is_ambiguous_and_ignored(session):
    message = discover(session)
    session["messages"].append({**message, "role": "assistant"})
    assert behaviors(build_dialogue_feedback(session))["clarified_need"]["status"] == "not_observed"


def test_question_before_refusal_does_not_count_as_response(session):
    discover(session)
    proposal(session, status="rejected")
    assert behaviors(build_dialogue_feedback(session))["responded_to_objection"]["status"] == "not_observed"


def test_meaningful_question_after_refusal_is_evidence(session):
    rejected = proposal(session, status="rejected", reason="Объём должен быть полным.")
    question = say(session, "Какие задачи нельзя исключить из объёма?", "clarify", "constraint")
    proposal(session, "full_scope")
    result = build_dialogue_feedback(session)
    observed = behaviors(result)["responded_to_objection"]
    assert observed["status"] == "observed"
    assert observed["evidence"][0]["message_id"] == question["id"]
    assert "Объём должен быть полным" in observed["explanation"]
    assert result["moments"][0]["message_id"] == rejected["id"]


def test_bare_disagreement_is_not_working_through_objection(session):
    proposal(session, status="rejected")
    say(session, "Я не согласен с вами!", "object", "terms")
    assert behaviors(build_dialogue_feedback(session))["responded_to_objection"]["status"] == "not_observed"


def test_adjusted_accepted_package_is_a_fact_not_a_skill_claim(session):
    rejected = proposal(session, "first", "rejected", "Нужен полный объём.")
    accepted = proposal(session, "full_scope", "accepted", "Полный объём сохранён.")
    result = build_dialogue_feedback(session)
    assert behaviors(result)["responded_to_objection"]["status"] == "not_observed"
    assert [item["message_id"] for item in result["moments"]] == [rejected["id"], accepted["id"]]
    assert result["moments"][-1]["title"] == "Изменили пакет после отказа"
    assert "а не самостоятельная оценка" in result["moments"][-1]["explanation"]


def test_same_package_accepted_later_does_not_claim_changed_package(session):
    proposal(session, "same", "rejected")
    discover(session)
    proposal(session, "same", "accepted")
    result = build_dialogue_feedback(session)
    assert result["moments"][-1]["title"] == "Клиент принял предложение"
    assert not any("изменили пакет" in item.lower() for item in result["strengths"])


def test_question_after_next_proposal_does_not_retroactively_answer_refusal(session):
    proposal(session, "first", "rejected")
    proposal(session, "second", "accepted")
    say(session, "Какие задачи нельзя исключить?", "clarify", "constraint")
    assert behaviors(build_dialogue_feedback(session))["responded_to_objection"]["status"] == "not_observed"


def test_legacy_only_reports_saved_discovery_and_proposal(session):
    discovery = discover(session)
    offered = proposal(session)
    del session["_dialogue_events"]
    del session["_proposal_events"]
    result = build_dialogue_feedback(session)
    assert [item["message_id"] for item in result["moments"]] == [discovery["id"], offered["id"]]
    observed = behaviors(result)
    assert observed["clarified_need"]["status"] == "observed"
    assert observed["justified_proposal"]["status"] == "not_observed"
    assert observed["responded_to_objection"]["status"] == "not_observed"


def test_message_order_not_event_order_drives_chronology_and_result_is_pure(session):
    discovery = discover(session)
    rejected = proposal(session, "first", "rejected")
    argument = say(session, "Сократим объём, чтобы сохранить дату запуска.", "justify", "terms")
    accepted = proposal(session, "second", "accepted")
    session["_dialogue_events"].reverse()
    session["_proposal_events"].reverse()
    original = deepcopy(session)
    result = build_dialogue_feedback(session)
    assert session == original
    assert [item["message_id"] for item in result["moments"]] == [discovery["id"], rejected["id"], argument["id"], accepted["id"]]
    assert len(result["moments"]) <= 5
    for moment in result["moments"]:
        assert moment["quote"] in next(item["text"] for item in session["messages"] if item["id"] == moment["message_id"])


def test_outcome_and_context_do_not_fabricate_spoken_skills(session):
    proposal(session)
    initial = build_dialogue_feedback(session)
    session.update({"priority": "cashflow", "difficulty": "hard", "_finish_outcome": "agreement", "status": "completed"})
    assert build_dialogue_feedback(session) == initial


def test_unlogged_freeform_text_is_not_reclassified_by_feedback(session):
    say(session, "Сократим объём, чтобы сохранить дату запуска.")
    result = build_dialogue_feedback(session)
    assert behaviors(result)["justified_proposal"]["status"] == "not_observed"


def test_fake_proposal_event_pointing_to_spoken_text_is_ignored(session):
    message = say(session, "Предлагаю пакет: клиент согласился.")
    session["_proposal_events"] = [{"message_id": message["id"], "option_id": "fake", "client_status": "accepted", "reason": "Выдумано", "terms": {}}]
    assert build_dialogue_feedback(session)["moments"] == []


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("text", [
    "В учебнике был вопрос: «Что для вас важнее всего в этом проекте?»",
    "В учебнике был вопрос: 'Что для вас важнее всего в этом проекте?'",
    "В учебнике был вопрос: «Что для вас важнее всего в этом проекте?",
    "Я не буду спрашивать, что для вас важнее всего в этом проекте?",
    "Я не уточняю, почему вам важна дата запуска?",
])
def test_discovery_pointer_cannot_credit_quoted_or_negated_question(session, version, text):
    session["_engine_version"] = version
    discover(session, text)
    if version == 1:
        session.pop("_dialogue_events")
    result = build_dialogue_feedback(session)
    observed = behaviors(result)["clarified_need"]
    assert observed["status"] == "not_observed"
    assert observed["evidence"] == []
    assert not any(item["title"] == "Уточнили потребность" for item in result["moments"])


@pytest.mark.parametrize("event_change", ["missing", "uncertain", "wrong_intent", "fake_quote"])
def test_modern_discovery_requires_matching_valid_event(session, event_change):
    session["_engine_version"] = 2
    discover(session)
    if event_change == "missing":
        session["_dialogue_events"] = []
    elif event_change == "uncertain":
        session["_dialogue_events"][0]["uncertain"] = True
    elif event_change == "wrong_intent":
        session["_dialogue_events"][0]["intent"] = "other"
    else:
        session["_dialogue_events"][0]["evidence"] = "Выдуманный вопрос?"
    assert behaviors(build_dialogue_feedback(session))["clarified_need"]["status"] == "not_observed"


def test_modern_discovery_span_inside_quotation_is_not_participant_question(session):
    session["_engine_version"] = 2
    question = "Что для вас важнее всего в этом проекте?"
    discover(session, f"В учебнике был вопрос: «{question}»")
    session["_dialogue_events"][0]["evidence"] = question
    assert behaviors(build_dialogue_feedback(session))["clarified_need"]["status"] == "not_observed"


def test_modern_own_polite_question_is_supported(session):
    session["_engine_version"] = 2
    discover(session, "Не могли бы вы уточнить, какие ограничения нам учесть?")
    assert behaviors(build_dialogue_feedback(session))["clarified_need"]["status"] == "observed"


def test_active_legacy_session_retains_late_discovery_without_inventing_old_verdict(session):
    old_proposal = proposal(session, "old", "rejected", "Дата запуска фиксирована.")
    discovery = discover(session)
    session.pop("_proposal_events")
    session.pop("_dialogue_events")
    session.pop("_engine_version", None)
    # Version 0.1 persisted only the current proposal. When a new offer replaces
    # it, earlier verdicts may be unavailable but its transcript turn remains.
    session["_proposal_events"] = []
    latest = proposal(session, "new", "accepted")
    result = build_dialogue_feedback(session)
    observed = behaviors(result)["clarified_need"]
    assert observed["evidence"][0]["message_id"] == discovery["id"]
    assert "после первого предложения" in observed["explanation"]
    assert not any("до первого предложения" in item for item in result["strengths"])
    assert any("до первого предложения" in item for item in result["improvements"])
    assert old_proposal["id"] not in [item["message_id"] for item in result["moments"]]
    assert result["moments"][-1]["message_id"] == latest["id"]
    assert result["moments"][-1]["title"] == "Клиент принял предложение"
    assert behaviors(result)["responded_to_objection"]["status"] == "not_observed"


def test_unlogged_intermediate_proposal_closes_response_window(session):
    proposal(session, "first", "rejected")
    intermediate = proposal(session, "intermediate", "accepted")
    session["_proposal_events"].pop()
    session.pop("_proposal_message_id")
    say(session, "Какие задачи нельзя исключить?", "clarify", "constraint")
    result = build_dialogue_feedback(session)
    assert behaviors(result)["responded_to_objection"]["status"] == "not_observed"
    assert intermediate["id"] not in [item["message_id"] for item in result["moments"]]
