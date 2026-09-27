"""Conversation practice without invented project accounting.

The client reacts to clarified interests and proposed approaches. No fictional
budget, capacity or margin is used to grade the learner. Legacy financial
snapshots remain the responsibility of the original engine path.
"""

from .conversation import last_topic


def active(session):
    return session["scenario"].get("practice_model") == "conversation"


def build_scenario(config, domain, role):
    scope = config["topic"] == "scope"
    interests = {
        "deadline": "Главное — сохранить ключевую дату. Готовы обсудить, какие задачи действительно нужны к запуску, а какие можно исключить или отложить отдельным решением.",
        "full_scope": "Нужен полный результат, а не только часть задач. Готовы обсудить последовательность работ и изменение срока, если вы объясните, как это поможет получить весь результат.",
        "budget": "Ограничение касается общей стоимости проекта. Готовы пересмотреть состав работ, если основной результат останется полезным и самостоятельным.",
        "cashflow": "Вопрос в первом платеже, а не в общей стоимости. Нужен полный результат; готовы обсудить другой порядок оплаты и встречные обязательства.",
    }
    options = [
        {
            "id": "prioritize_swap", "label": "Согласовать приоритеты к запуску",
            "description": "Вместе выделить обязательные задачи к ключевой дате. Остальные задачи исключить из текущего этапа и обсуждать отдельно, без автоматических обещаний.",
            "terms": None,
        },
        {
            "id": "extend_deadline", "label": "Предложить поэтапный план",
            "description": "Сохранить полный результат, согласовать последовательность работ и отдельно уточнить срок с учётом новой задачи.",
            "terms": None,
        },
        {
            "id": "accept_all", "label": "Добавить все новые задачи",
            "description": "Включить все дополнительные задачи и сохранить прежнюю дату.",
            "terms": None,
        },
    ] if scope else [
        {
            "id": "reduce_scope", "label": "Обсудить взаимную уступку",
            "description": "Пересмотреть состав работ в обмен на изменение стоимости, сохранив самостоятельный полезный результат. Точные условия согласовать после уточнения потребности.",
            "terms": None,
        },
        {
            "id": "staged_payment", "label": "Изменить порядок оплаты",
            "description": "Сохранить полный результат и общую стоимость, отдельно согласовать первый платёж и дальнейшие этапы оплаты.",
            "terms": None,
        },
        {
            "id": "discount_all", "label": "Согласиться на скидку",
            "description": "Снизить стоимость при прежнем составе работ без встречного изменения условий со стороны клиента.",
            "terms": None,
        },
    ]
    priorities = [
        {"id": "deadline", "label": "Дата запуска", "description": "Выясните, насколько важна дата и что обязательно успеть к ней."},
        {"id": "full_scope", "label": "Полный результат", "description": "Уточните ожидания по результату и возможность изменить последовательность работ."},
    ] if scope else [
        {"id": "budget", "label": "Общая стоимость", "description": "Уточните ограничение по всему проекту и допустимые встречные уступки."},
        {"id": "cashflow", "label": "Первый платёж", "description": "Разберитесь, связан ли запрос с порядком оплаты."},
    ]
    return {
        "id": config["topic"], "practice_model": "conversation",
        "title": domain["scope_title" if scope else "discount_title"],
        "eyebrow": domain["label"].upper(), "duration": f"Около {config['duration_minutes']} минут",
        "skill": "Выяснять интересы, аргументировать позицию и находить взаимоприемлемый следующий шаг",
        "client_name": "Анна" if scope else "Михаил", "client_role": role["label"], "company": domain["company"],
        "description": (
            f"Клиент хочет добавить {domain['extra']} и сохранить дату. Обсудите приоритеты и границы изменений."
            if scope else f"Клиент просит снизить стоимость на {domain['work']}. Выясните причину и обсудите встречные условия."
        ),
        "briefing": (
            f"Вы — менеджер {domain['provider']}. Проект — {domain['project']}. "
            + (f"Клиент просит добавить {domain['extra']} и сохранить ключевую дату."
               if scope else "Клиент просит снизить стоимость при прежнем результате.")
        ),
        "objective": "Выясните, что важно клиенту, объясните свою позицию и согласуйте следующий шаг.",
        "constraints": (
            ["Новые задачи требуют обсуждения приоритетов и ожиданий обеих сторон.",
             "Не обещайте сохранить все условия, пока не уточнили возможности команды.",
             "Изменения и следующий шаг нужно явно согласовать; молчание клиента не означает согласия."]
            if scope else
            ["Причина просьбы о скидке неизвестна в начале разговора — сначала уточните её.",
             "Уступку можно связать с встречным шагом, сохранив важный для клиента результат.",
             "Условия, которых нет в брифе, нужно обсуждать и уточнять, а не придумывать за клиента."]
        ),
        "client_interest": role["frame"] + " " + interests[config["goal"]],
        "opening": role["frame"] + " " + (
            f"Хотим добавить {domain['extra']}, но дату менять не хотелось бы. Как можем это организовать?"
            if scope else f"Обсудим {domain['work']}: нам хотелось бы снизить стоимость и сохранить результат. Что вы можете предложить?"
        ),
        "baseline": None, "options": options, "priorities": priorities,
    }


def proposal_verdict(session, option_id):
    if session["difficulty"] == "hard" and not session["discovered_interests"]:
        return False, "Пока не вижу, как ваш подход учитывает моё ограничение. Сначала уточните, что для меня важно."
    priority = session["priority"]
    if option_id in {"accept_all", "discount_all"}:
        return True, "Для меня это выгодное предложение. Я принимаю предложенный подход; уточнение деталей и возможностей вашей стороны всё ещё важно."
    if option_id == "prioritize_swap":
        return (True, "Мне подходит совместно выделить главное к ключевой дате и отдельно договориться об остальных задачах.") if priority == "deadline" else (False, "Мне нужен полный результат. Давайте обсудим последовательность работ вместо исключения нужных задач.")
    if option_id == "extend_deadline":
        return (True, "Мне подходит поэтапный план с сохранением полного результата. Срок и следующий шаг уточним вместе.") if priority == "full_scope" else (False, "Ключевая дата для меня важнее полного объёма. Как можно выделить главное к этой дате?")
    if option_id == "reduce_scope":
        return (True, "Мне подходит обсудить меньший состав работ в обмен на изменение общей стоимости, если результат останется самостоятельным.") if priority == "budget" else (False, "Состав работ нужно сохранить. Вопрос в первом платеже, поэтому сокращение результата не решает мою задачу.")
    if option_id == "staged_payment":
        return (True, "Мне подходит пересмотреть первый платёж и этапы оплаты, сохранив полный результат и общую стоимость.") if priority == "cashflow" else (False, "Другой порядок оплаты не меняет общую стоимость. Мне нужно обсудить именно ограничение по всему проекту.")
    raise ValueError("Unknown conversation proposal")


def reply(session, analysis, interest, was_discovered):
    """All branches use the current semantic snapshot, never legacy terms."""
    proposal = session.get("proposal")
    topic = last_topic(session)
    scope = session["scenario"]["id"] == "scope"
    if analysis.uncertain:
        return "Хочу точнее понять ваш подход. Как он связан с моей просьбой и какой следующий шаг вы предлагаете?"
    if analysis.intent == "instruction_override":
        return "Вернёмся к обсуждению задачи. Давайте уточним интересы сторон и возможный следующий шаг."
    if analysis.intent == "off_topic":
        return "Давайте вернёмся к ситуации клиента. Что вы хотите уточнить или предложить по нашей задаче?"
    if analysis.intent == "ask_interest":
        return ("Мой основной приоритет остаётся таким: " if was_discovered else "") + interest + " Как вы предлагаете это учесть?"
    if analysis.intent == "clarify":
        if proposal and (analysis.focus == "terms" or topic in {"summary", "terms", "next_step"}):
            status = "Этот подход мне подходит." if proposal["client_status"] == "accepted" else "Этот подход пока не подходит: " + proposal["reason"]
            return "Обсуждали: " + proposal["description"] + " " + status + " Какие детали ещё нужно уточнить?"
        if topic == "risk":
            return "Важно, чтобы мы одинаково понимали результат и не оставили неоговорённых обещаний. Как вы проверите это перед завершением?"
        if topic in {"reason", "compromise", "next_step"} and was_discovered:
            return interest + " Предложите встречный шаг и объясните, как он учитывает интересы обеих сторон."
        if topic in {"payment", "budget"}:
            return (interest + " Какой подход вы предлагаете?" if was_discovered else "Вы хотите уточнить общую стоимость или порядок оплаты? Сначала давайте разберёмся, что именно ограничивает решение.")
        if topic in {"scope", "deadline"}:
            return (interest + " Какие задачи и ожидания вы предлагаете согласовать?" if was_discovered else "Давайте обсудим, что важнее для результата и насколько можно менять дату или состав задач. Что вы хотите уточнить?")
        return ("Сверим мою позицию: " + interest if was_discovered else "Уточните, что хотите разобрать: причину моей просьбы, ожидаемый результат или допустимые изменения.")
    if analysis.intent == "justify":
        if proposal:
            return ("Логику вашего объяснения понимаю. " + proposal["reason"] + " Давайте уточним следующий шаг.")
        return ("Понимаю, как вы связываете свой подход с задачей. " + (interest if was_discovered else "Мне важно увидеть, какой результат вы предлагаете сохранить.") + " Какую встречную уступку вы ожидаете?")
    if analysis.intent == "object":
        if analysis.focus == "relationship":
            return "Давайте продолжим спокойно. Какое условие или ожидание нам нужно уточнить?"
        return "Понимаю, что у вашей стороны есть границы. " + (proposal["reason"] if proposal and proposal["client_status"] == "rejected" else interest if was_discovered else "Расскажите, что мешает принять мою просьбу.") + " Какую альтернативу вы готовы обсудить?"
    if analysis.intent == "propose":
        return ("Давайте обсудим, как этот подход учитывает моё ограничение. " if was_discovered else "Прежде чем выбирать подход, хочу уточнить, одинаково ли мы понимаем задачу. ") + "Объясните ожидаемый результат и встречный шаг. Чтобы отдельно получить реакцию на конкретный вариант, выберите его в решениях."
    if analysis.intent == "acknowledge":
        if proposal and proposal["client_status"] == "accepted":
            return "Предложенный подход мне подходит. Если мы одинаково понимаем следующий шаг, можно завершить разговор с соглашением."
        return "Спасибо, что учитываете мою позицию. " + ("Как предлагаете совместить приоритеты клиента и возможности команды?" if scope else "Какую встречную уступку или изменение условий готовы обсудить?")
    return "Помогите понять ваш следующий шаг: что хотите уточнить у меня или какой подход предлагаете обсудить?"


def feedback(session, agreed, dialogue):
    strengths = list(dialogue["strengths"])
    improvements = list(dialogue["improvements"])
    unconditional = agreed and session["proposal"]["option_id"] in {"accept_all", "discount_all"}
    if unconditional:
        next_step = (
            "В повторе обсудите, какие задачи нужны к ключевой дате и как проверить возможности команды, прежде чем обещать сохранить все условия."
            if session["proposal"]["option_id"] == "accept_all" else
            "В повторе уточните причину просьбы о скидке и обсудите встречный шаг клиента, прежде чем уступать при прежнем составе работ."
        )
        improvements.append(next_step)
        summary = (
            "Клиент принял предложение добавить все задачи и сохранить дату. В самом предложении не уточнено, как согласовать изменения с возможностями команды. Согласие клиента само по себе не показывает качество переговоров."
            if session["proposal"]["option_id"] == "accept_all" else
            "Клиент принял скидку при прежнем составе работ. В этом предложении нет встречного изменения со стороны клиента. Согласие само по себе не показывает качество переговоров."
        )
    else:
        next_step = improvements[0] if improvements else "Повторите разговор и попробуйте другой способ уточнить интересы и объяснить свой подход."
        summary = (
            "Клиент принял предложенный подход. Разбор ниже опирается на ваши реплики: что вы уточнили, как объяснили позицию и ответили на возражения."
            if agreed else "Соглашение не зафиксировано. Это не означает неудачу: разбор показывает ваши действия и помогает выбрать следующий шаг в похожем разговоре."
        )
    return {
        "title": "Вы согласовали подход" if agreed else "Разговор завершён без соглашения",
        "summary": summary,
        "outcome": "agreement" if agreed else "no_agreement", "metrics": None,
        "moments": dialogue["moments"], "behaviors": dialogue["behaviors"],
        "strengths": strengths, "improvements": improvements,
        "next_step": next_step,
    }
