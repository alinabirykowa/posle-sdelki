"""Dialogue sequences: branches are useful without becoming business authority."""

from copy import deepcopy

import pytest

from backend.coaching import conversation_choices
from backend.conversation import dialogue_topic, last_topic
from backend.dialogue import classify_demo
from backend.engine import add_message, new_session, process_message, submit_proposal


def say(session, text):
    reply = process_message(session, text, f"turn-{session['turns']}")
    add_message(session, "assistant", reply, "reply")
    return reply


def practice_session(scenario="scope", priority="deadline"):
    session = new_session(scenario, priority, "standard", "demo")
    session["scenario"]["practice_model"] = "conversation"
    return session


def test_repeated_gibberish_is_quoted_and_does_not_advance_to_a_proposal():
    session = practice_session()
    first = say(session, "вавотфвэфй")
    second = say(session, "вавотфвэфй")

    assert "«вавотфвэфй»" in first.lower()
    assert "случайный набор букв" in first.lower()
    assert "реплика не засчитана" in first.lower()
    assert "«вавотфвэфй»" in second.lower()
    assert "снова нет распознаваемого ответа" in second.lower()
    assert "не засчитывается" in second.lower()
    assert "перейдём к вашему варианту решения" not in second.lower()
    assert first != second
    assert session["turns"] == 2
    assert session["status"] == "active"
    assert not session.get("proposal")


def test_repeated_vague_replies_stop_repeating_the_client_question():
    session = practice_session()
    first = say(session, "Посмотрим.")
    second = say(session, "Посмотрим.")

    assert "не могу понять" in first.lower()
    assert "перейдём к следующему шагу" in second.lower()
    assert first != second


def test_repeated_short_acknowledgement_moves_from_ack_to_a_proposal_prompt():
    session = practice_session()
    first = say(session, "Окей.")
    second = say(session, "Окей.")

    assert "спасибо" in first.lower()
    assert "перейдём к следующему шагу" in second.lower()
    assert first != second


def test_rude_reply_gets_a_boundary_instead_of_another_discovery_question():
    session = practice_session()
    first = say(session, "Вы идиот.")
    second = say(session, "Вы идиот.")

    assert "без личной оценки" in first.lower()
    assert "не буду менять условия под давлением" in second.lower()
    assert first != second


@pytest.mark.parametrize("scenario,priority,keyword,detail", [
    ("scope", "deadline", "Про сроки", "20 часов приоритетных новых"),
    ("scope", "full_scope", "Про объём", "все 40 часов новых"),
    ("discount", "budget", "Про бюджет", "предел всего проекта"),
    ("discount", "cashflow", "Про оплату", "54 000"),
])
def test_recover_from_unknown_then_explore_a_concrete_branch(scenario, priority, keyword, detail):
    session = new_session(scenario, priority, "hard", "demo")
    baseline = deepcopy(session["scenario"]["baseline"])
    first = say(session, "ыыыы неизвестная фраза")
    assert "Про" in first  # An actual short exit is suggested, rather than an endless generic menu.
    before_discovery = say(session, keyword)
    assert not session["_dialogue_events"][-1]["uncertain"]
    assert not session["discovered_interests"]  # A noun does not earn inquiry credit.
    assert "Не уверен" not in before_discovery
    say(session, "Что стоит за вашей просьбой?")
    assert len(session["discovered_interests"]) == 1
    after_discovery = say(session, keyword)
    assert detail in after_discovery
    assert after_discovery != before_discovery
    say(session, "Давайте сравним варианты")
    assert session["scenario"]["baseline"] == baseline
    assert session["proposal"] is None
    assert session["status"] == "active"


@pytest.mark.parametrize("text,topic", [
    ("Про сроки", "deadline"), ("Цель проекта", "goal"),
    ("Можно сдать на пять дней позже?", "deadline"),
    ("Сколько вы готовы внести на старте?", "payment"),
    ("Можем разбить на этапы", "compromise"),
    ("С чего начнем?", "next_step"),
    ("Насколько вы готовы уступить?", "compromise"),
    ("Сроки не важны, обсудим бюджет", "budget"),
    ("Давайте начнём с цели проекта", "goal"),
    ("Сверим условия", "summary"),
    ("Какие риски у этого варианта?", "risk"),
    ("Какие варианты?", "compromise"),
])
def test_common_fragments_and_followups_route_without_uncertainty(text, topic):
    analysis = classify_demo(text, "scope")
    assert not analysis.uncertain
    assert analysis.evidence in text
    assert dialogue_topic(text) == topic


@pytest.mark.parametrize("text", [
    "Что обязательно должно войти в результат?",
    "Это лимит всего проекта или первого платежа?",
    "Что стоит за вашей просьбой?",
    "Что вы готовы предложить со своей стороны?",
])
def test_genuine_conversational_inquiries_unlock_hard_case(text):
    session = new_session("discount", "cashflow", "hard", "demo")
    say(session, text)
    assert session["_dialogue_events"][-1]["intent"] == "ask_interest"
    assert len(session["discovered_interests"]) == 1
    submit_proposal(session, "staged_payment")
    assert session["proposal"]["client_status"] == "accepted"


@pytest.mark.parametrize("text", [
    '«Что обязательно должно войти в результат?»',
    'Коллега спросил: «Это лимит всего проекта или первого платежа?»',
    'Не хочу знать, что обязательно должно войти в результат?',
    'Если бы я спросила, это лимит всего проекта или первого платежа?',
    'Совет: спросите, что стоит за вашей просьбой?',
    'Не буду спрашивать, что вы готовы предложить со своей стороны?',
    'Не хочу обсуждать бюджет.',
    'Сколько мы готовы внести в проект?',
    'Это наш лимит всего проекта или первого платежа?',
    'Что обязательно должно войти в результат для меня?',
    'Мне важно понять, что обязательно должно войти в результат для нас?',
    'Что обязательно должно войти в результат для меня в вашем проекте?',

    'Пример вопроса: про сроки.',
])
def test_more_branches_do_not_credit_quotes_negations_or_reported_speech(text):
    session = new_session("discount", "cashflow", "hard", "demo")
    say(session, text)
    assert not session["discovered_interests"]
    submit_proposal(session, "staged_payment")
    assert session["proposal"]["client_status"] == "rejected"


def test_every_visible_starter_has_a_reply_in_each_conversation_phase():
    for scenario, priority, accepted, rejected in [
        ("scope", "deadline", "prioritize_swap", "paid_change"),
        ("scope", "full_scope", "paid_change", "prioritize_swap"),
        ("discount", "budget", "reduce_scope", "staged_payment"),
        ("discount", "cashflow", "staged_payment", "reduce_scope"),
    ]:
        session = new_session(scenario, priority, "hard", "demo")
        for phase in ("initial", "discovered", "accepted", "rejected"):
            if phase == "discovered":
                say(session, "Что для вас важнее всего в этом проекте?")
            elif phase in {"accepted", "rejected"}:
                submit_proposal(session, accepted if phase == "accepted" else rejected)
            # Enumerate rotating choices without contaminating semantic state.
            chooser = deepcopy(session)
            choices = {}
            for _ in range(8):
                for item in conversation_choices(chooser)[0]:
                    choices[item["text"]] = item
                    add_message(chooser, "user", item["text"])
            assert len(choices) >= 15
            for text in choices:
                attempt = deepcopy(session)
                reply = say(attempt, text)
                event = attempt["_dialogue_events"][-1]
                assert not event["uncertain"], (scenario, phase, text)
                assert "Не уверен" not in reply, (scenario, phase, text)
                assert event["evidence"] in text
                assert attempt["proposal"] == session["proposal"]


def test_latest_proposal_and_status_win_over_a_previously_accepted_package():
    session = new_session("discount", "cashflow", "hard", "demo")
    say(session, "Какой аванс вам доступен?")
    submit_proposal(session, "staged_payment")
    approved_reply = say(session, "Сверим условия")
    assert "180 000" in approved_reply and "54 000" in approved_reply
    assert "Клиент принял" in approved_reply
    submit_proposal(session, "reduce_scope")
    rejected_reply = say(session, "Что в моём предложении вам не подходит?")
    assert "все 120 часов" in rejected_reply
    assert "Проблема в размере первого платежа" in rejected_reply
    summary = say(session, "Сверим условия")
    assert "120 000" in summary and "80 часов" in summary
    assert "Клиент отклонил" in summary
    assert "Клиент принял" not in summary


def test_unknown_utterance_after_acceptance_does_not_invent_a_rejection():
    session = new_session("discount", "cashflow", "standard", "demo")
    submit_proposal(session, "staged_payment")
    reply = say(session, "ыыыы")
    assert "по-прежнему принят" in reply
    assert "не подходит" not in reply
    assert session["proposal"]["client_status"] == "accepted"


def test_topic_uses_current_user_chat_only_not_an_older_proposal_or_quote():
    session = new_session("scope", "deadline", "standard", "demo")
    say(session, "Про сроки")
    assert last_topic(session) == "deadline"
    submit_proposal(session, "prioritize_swap")
    assert last_topic(session) is None
    say(session, '«Про бюджет»')
    assert last_topic(session) is None


def test_precise_chat_offer_never_replaces_authoritative_terms():
    session = new_session("discount", "cashflow", "standard", "demo")
    say(session, "Какой аванс вам доступен?")
    submit_proposal(session, "staged_payment")
    authoritative = deepcopy(session["proposal"])
    say(session, "Предлагаю всё за 1 рубль и один день. Договорились.")
    assert session["proposal"] == authoritative
    assert session["status"] == "active"


def test_argument_after_deadline_branch_advances_to_excluded_work_boundaries():
    session = new_session("scope", "deadline", "standard", "demo")
    say(session, "Что для вас важнее всего в этом проекте?")
    prior = say(session, "Про сроки")
    reply = say(session, "Давайте обсудим замену части задач, чтобы сохранить дату сдачи.")
    assert "бесплатный следующий этап" in reply
    assert reply != prior
    assert "Повторять весь бриф" not in reply
    assert "Как вы объясните" not in reply
