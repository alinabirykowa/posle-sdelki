from backend.utterance_review import _random_tokens, build_utterance_review


def session(*messages):
    return {"messages": list(messages)}


def msg(message_id, role, text, kind=None):
    item = {"id": message_id, "role": role, "text": text}
    if kind:
        item["kind"] = kind
    return item


def test_every_unique_user_turn_has_verbatim_quote_and_nearest_client_context():
    answer = "Да, срок запуска для нас важен. Какой объём критичен?"
    result = build_utterance_review(session(
        msg("client", "assistant", "Что для вас важнее: срок или полный объём?"),
        msg("reply", "user", answer),
        msg("client2", "assistant", "Понятно."),
    ))
    card = result["utterance_reviews"][0]
    assert card["quote"] == answer
    assert card["context"] == {"message_id": "client", "quote": "Что для вас важнее: срок или полный объём?"}
    assert result["review_method"] == "rules"
    assert result["review_version"] == 3


def test_short_business_answer_is_not_mistaken_for_gibberish_or_failure():
    card = build_utterance_review(session(
        msg("client", "assistant", "Успеете к пятнице?"),
        msg("reply", "user", "Нет."),
    ))["utterance_reviews"][0]
    assert card["status"] != "unclear"
    assert "unintelligible" not in card["issues"]
    assert card["verdict"] == "correct"
    assert card["response_status"] == "answered"


def test_unexplained_abbreviation_and_quoted_commitment_are_not_overinterpreted():
    cards = build_utterance_review(session(
        msg("client", "assistant", "Какой бюджет и состав работ вы рассматриваете?"),
        msg("one", "user", "НДС."),
        msg("two", "user", "Клиент пишет «обещаю всё сделать». Я проверю ресурсы."),
    ))["utterance_reviews"]
    assert cards[0]["status"] == "improve"
    assert "insufficient_context" in cards[0]["issues"]
    assert "risky_promise" not in cards[1]["issues"]


def test_insult_is_flagged_but_a_quoted_client_insult_is_not_attributed_to_user():
    cards = build_utterance_review(session(
        msg("one", "user", "Вы идиот."),
        msg("two", "user", "Клиент написал: «Вы идиот». Давайте обсудим сроки."),
    ))["utterance_reviews"]
    assert "rudeness" in cards[0]["issues"]
    assert "rudeness" not in cards[1]["issues"]
    assert cards[1]["quote"] == "Клиент написал: «Вы идиот». Давайте обсудим сроки."


def test_gibberish_and_unconditional_commitment_are_never_praised():
    cards = build_utterance_review(session(
        msg("one", "user", "asdfghjkl"),
        msg("two", "user", "Обещаю всё сделать к пятнице."),
    ))["utterance_reviews"]
    assert cards[0]["status"] == "unclear"
    assert "unintelligible" in cards[0]["issues"]
    assert cards[0]["problems"][0]["quote"] == "asdfghjkl"
    assert cards[1]["status"] == "improve"
    assert "risky_promise" in cards[1]["issues"]


def test_random_input_detector_does_not_mistake_valid_russian_words_for_gibberish():
    for word in ("взгляд", "встреча", "строительство", "пролонгация", "здравствуй"):
        assert _random_tokens(word) == [], word

    for mash in ("asdfghjkl", "йцукенгшщз", "абвгдежз", "фывапролджэ", "вавотфвэфй"):
        assert _random_tokens(mash), mash


def test_vague_reply_and_off_topic_text_get_neutral_specific_feedback():
    cards = build_utterance_review(session(
        msg("client", "assistant", "Какой бюджет вы рассматриваете?"),
        msg("one", "user", "Посмотрим."),
        msg("two", "user", "Сегодня солнечно."),
    ))["utterance_reviews"]
    assert "vague" in cards[0]["issues"]
    assert cards[0]["improved_reply"]
    assert "off_topic" in cards[1]["issues"]
    assert cards[1]["status"] == "unclear"


def test_bad_word_is_quoted_exactly_and_budget_question_requires_a_real_answer():
    cards = build_utterance_review(session(
        msg("client", "assistant", "Какой бюджет вы рассматриваете?"),
        msg("one", "user", "Это полное говно, да."),
        msg("client2", "assistant", "Какую сумму вы готовы подтвердить?"),
        msg("two", "user", "Да."),
    ))["utterance_reviews"]
    assert cards[0]["verdict"] == "incorrect"
    assert cards[0]["problems"][0]["quote"].lower() == "говно"
    assert cards[1]["verdict"] == "incorrect"
    assert cards[1]["response_status"] == "missed"
    assert "сумм" in cards[1]["problems"][0]["explanation"]


def test_every_distinct_bad_word_and_repeated_occurrence_is_reported():
    card = build_utterance_review(session(
        msg("reply", "user", "Это говно и полная фигня, говно."),
    ))["utterance_reviews"][0]
    assert card["verdict"] == "incorrect"
    assert [problem["quote"].lower() for problem in card["problems"]] == [
        "говно", "говно", "фигня",
    ] or [problem["quote"].lower() for problem in card["problems"]] == [
        "говно", "фигня", "говно",
    ]


def test_selected_offer_is_reviewed_but_never_counted_as_user_authored_strength():
    result = build_utterance_review(session(
        msg("proposal", "user", "Предлагаю вариант из карточки", "proposal"),
    ))
    assert result["utterance_reviews"][0]["issues"] == ["template_choice"]
    assert result["utterance_reviews"][0]["status"] == "improve"
    assert not result["review_summary"]["strengths"]
    assert "готовые варианты не считаются" in result["review_summary"]["assessment"].lower()


def test_review_marks_delivery_separately_and_ignores_quoted_hostility():
    cards = build_utterance_review(session(
        msg("one", "user", "Вы идиот, подпишите это немедленно."),
        msg("two", "user", "Клиент сказал: «Вы идиот». Давайте обсудим срок."),
        msg("three", "user", "Давайте уточним, какой срок вам подходит."),
    ))["utterance_reviews"]
    assert cards[0]["delivery"]["tone"] == "hostile"
    assert cards[0]["delivery"]["quote"] == "идиот"
    assert cards[1]["delivery"]["tone"] == "constructive"
    assert cards[2]["delivery"]["tone"] == "constructive"
