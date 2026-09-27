"""Choice groups must lead to usable dialogue without authorising a deal."""

from copy import deepcopy
from uuid import uuid4

import pytest

from backend import engine
from backend.dialogue import classify_demo


CASES = [("scope", "deadline"), ("scope", "full_scope"),
         ("discount", "budget"), ("discount", "cashflow")]


def say(session, text):
    reply = engine.process_message(session, text, str(uuid4()))
    engine.add_message(session, "assistant", reply)
    return reply


@pytest.mark.parametrize("scenario,priority", CASES)
def test_visible_choices_are_recognized_and_do_not_make_agreements(scenario, priority):
    base = engine.new_session(scenario, priority, "hard", "demo")
    for discovered in (False, True):
        if discovered:
            say(base, "Что для вас важнее всего в этом проекте?")
        choices = engine.public(base)["reply_choices"]
        assert {item["group"] for item in choices} == {"explore", "respond", "negotiate"}
        assert len(choices) == len({item["id"] for item in choices}) == 9
        for choice in choices:
            session = deepcopy(base)
            analysis = classify_demo(choice["text"], scenario, discovered)
            assert not analysis.uncertain, choice
            reply = say(session, choice["text"])
            assert reply and "Не уверен" not in reply, choice
            assert session["proposal"] is None
            assert session["status"] == "active"
            assert session["scenario"] == base["scenario"]


def test_unrevealed_priority_does_not_select_a_correct_answer():
    for scenario, first, second in (("scope", "deadline", "full_scope"), ("discount", "budget", "cashflow")):
        a = engine.new_session(scenario, first, "hard", "demo")
        b = engine.new_session(scenario, second, "hard", "demo")
        assert a["reply_choices"] == b["reply_choices"]


def test_reading_existing_session_adds_choices_without_rewriting_transcript():
    old = engine.new_session("discount", "budget", "standard", "demo")
    old.pop("reply_choices")
    old.pop("conversation_hint")
    original = deepcopy(old)
    view = engine.public(old)
    assert len(view["reply_choices"]) == 9
    assert old == original
    assert view["messages"] == old["messages"]
    assert not any(key.startswith("_") for key in view)


def test_suggestions_follow_latest_proposal_not_previous_agreement():
    session = engine.new_session("discount", "cashflow", "standard", "demo")
    say(session, "Что для вас важнее всего в этом проекте?")
    engine.submit_proposal(session, "staged_payment")
    accepted = engine.public(session)
    assert "согласен" in accepted["conversation_hint"]
    engine.submit_proposal(session, "reduce_scope")
    rejected = engine.public(session)
    assert "отклонил" in rejected["conversation_hint"]
    assert rejected["reply_choices"][0]["id"] == "explore-rejection"
    with pytest.raises(engine.RuleError):
        engine.finish(session, "agreement")


def test_sent_starter_is_replaced_and_completed_session_has_no_more_choices():
    session = engine.new_session("scope", "deadline", "standard", "demo")
    starter = next(c for c in session["reply_choices"] if c["id"] == "respond-empathy")
    say(session, starter["text"])
    assert starter["text"] not in [c["text"] for c in engine.public(session)["reply_choices"]]
    engine.finish(session, "no_agreement")
    view = engine.public(session)
    assert view["reply_choices"] == view["suggestions"] == []
    assert view["conversation_hint"] == ""
