"""Editable conversation starters; never a verdict or a hidden answer key."""


def choice(key, group, label, text):
    return {"id": key, "group": group, "label": label, "text": text}


def conversation_choices(session):
    if session["status"] == "completed":
        return [], ""
    discovered = bool(session.get("discovered_interests"))
    proposal = session.get("proposal")
    scope = session["scenario"]["id"] == "scope"
    semantic = session["scenario"].get("practice_model") == "conversation"
    status = proposal.get("client_status") if proposal else None
    used = {m["text"].strip() for m in session["messages"] if m["role"] == "user"}
    # Hidden priorities do not select a suggested answer. Branches follow only
    # what has happened in the visible conversation and its scenario family.
    explore = [
        ("priority", "Понять приоритет", "Что для вас важнее всего в этом проекте?"),
        ("reason", "Разобраться в причине", "Что стоит за вашей просьбой?"),
        ("constraint", "Узнать ограничения", "Какие ограничения нам нужно учесть?"),
        ("deadline", "Обсудить срок", "Насколько для вас критична дата сдачи проекта?"),
        ("scope", "Уточнить объём", "Какие задачи обязательно должны войти в результат, а от каких можно отказаться?"),
        ("budget", "Разобрать бюджет", "Что вас ограничивает: общая сумма проекта или первый платёж?"),
        ("flexibility", "Найти пространство для уступок", "Какие условия для вас можно изменить?"),
    ]
    respond = [
        ("empathy", "Признать позицию клиента", "Понимаю вашу позицию. Мне важно найти выполнимое решение."),
        ("boundary", "Обозначить границу", "Мы не можем обещать прежние условия при таком изменении. Давайте обсудим, что можно изменить."),
        ("reasoning", "Объяснить свою позицию", (
            "Дополнительные задачи требуют времени команды, поэтому нужно пересмотреть объём или срок."
            if scope else ("Давайте свяжем уступку со встречным шагом, чтобы сохранить важный для вас результат." if semantic else "При сохранении всего объёма затраты команды не снижаются, поэтому скидку нужно связать с изменением условий.")
        )),
        ("check", "Проверить понимание", "Правильно ли я понимаю ваше главное ограничение?"),
        ("summary", "Подвести итог", "Подведём итог нашего разговора: какие условия мы уже обсудили?"),
    ]
    negotiate = [
        ("compare", "Сравнить подходы", "Давайте сравним варианты: что можно изменить в объёме, сроке и цене?"),
        ("alternative", "Обсудить альтернативу", (
            "Давайте обсудим замену части задач, чтобы сохранить дату сдачи."
            if scope else "Давайте обсудим меньший объём работ, чтобы снизить общую цену."
        )),
        ("exchange", "Предложить встречный шаг", (
            ("Можно сохранить полный результат, если вместе согласовать последовательность работ и уточнить срок. Давайте обсудим этот вариант." if semantic else "Можно сохранить все задачи, если отдельно согласовать новый срок и доплату. Давайте обсудим этот вариант.")
            if scope else "Можно сохранить полный объём и цену, если уменьшить первый платёж. Давайте обсудим этот вариант."
        )),
        ("reciprocity", "Обсудить уступку клиента", "Что вы готовы предложить со своей стороны?"),
        ("risk", "Проверить риски", "Какие риски у этого варианта?"),
    ]
    if status == "rejected":
        explore = [
            ("rejection", "Разобрать отказ", "Что в моём предложении вам не подходит?"),
            ("flexibility", "Уточнить допустимые изменения", "Какие условия для вас можно изменить?"),
            *explore,
        ]
        respond = [respond[3], respond[0], respond[2], respond[1], respond[4]]
        hint = "Клиент отклонил пакет. Можно разобрать причину, объяснить свою позицию или обсудить другой вариант."
    elif status == "accepted":
        explore = [
            ("terms", "Сверить договорённость", "Какие условия входят в последнее предложение?"),
            ("included", "Уточнить состав работ", "Какие работы входят в согласованный пакет?"),
            (("next-step", "Уточнить следующий шаг", "Какой следующий шаг нам нужно согласовать?") if semantic and scope else ("payment", "Проверить оплату", "Какой порядок оплаты у этого пакета?")),
            *explore,
        ]
        respond = [respond[4], respond[2], respond[0], respond[3], respond[1]]
        negotiate = [negotiate[4], negotiate[0], negotiate[3], *negotiate[1:3]]
        hint = "Клиент согласен с пакетом. Можно сверить детали или продолжить обсуждение; завершение — в условиях проекта."
    elif discovered:
        explore = [explore[3], explore[4] if scope else explore[5], explore[6], *explore[:3]]
        respond = [respond[3], respond[2], respond[4], *respond[:2]]
        hint = "Ограничение клиента уже известно. Можно углубиться в детали, объяснить свою позицию или обсудить компромисс."
    else:
        hint = "Выберите направление разговора или напишите свой ответ. Здесь нет одной обязательной реплики."

    result = []
    for group, pool in (("explore", explore), ("respond", respond), ("negotiate", negotiate)):
        # Prefer unused starters, keeping used ones reachable when the pool is
        # exhausted. IDs are stable and unique within this response.
        unique = list({entry[0]: entry for entry in pool}.values())
        ordered = [x for x in unique if x[2] not in used] + [x for x in unique if x[2] in used]
        result.extend(choice(f"{group}-{key}", group, label, text) for key, label, text in ordered[:3])
    if semantic:
        hint = hint.replace("Клиент отклонил пакет", "Клиент отклонил подход").replace("Клиент согласен с пакетом", "Клиент согласен с подходом").replace("завершение — в условиях проекта", "итог разговора подтверждается отдельно")
    return result, hint
