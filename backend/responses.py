"""Client responses composed from validated acts and authoritative scenario facts.

Provider prose never enters the displayed conversation. This keeps one version
of terms and acceptance, while live semantic analysis can recognize paraphrases.
"""

from .conversation import argument_reply, fallback_reply, last_topic, proposal_reason, topic_reply
from . import conversation_practice


def message_reply(session, analysis, interest, was_discovered):
    if conversation_practice.active(session):
        return conversation_practice.reply(session, analysis, interest, was_discovered)
    if analysis.uncertain:
        return fallback_reply(session)

    intent = analysis.intent
    topic = last_topic(session)
    proposal = session.get("proposal")
    rejection = proposal_reason(session, interest, was_discovered)
    if intent == "ask_interest":
        if was_discovered:
            detail = topic_reply(session, topic, interest, was_discovered)
            return detail or "Мой приоритет остаётся таким: " + interest + " Как вы предлагаете это учесть?"
        return interest + " Что из этого вы готовы учесть и какую уступку ожидаете от меня?"

    if intent == "instruction_override":
        return "Давайте вернёмся к переговорам о проекте. Обсудим интересы и условия; договорённость нужно отдельно подтвердить."
    if intent == "off_topic":
        return "Предлагаю сосредоточиться на проекте. Какой вопрос об объёме, сроках или оплате вы хотите обсудить?"

    if intent == "clarify":
        if topic in {"reason", "risk", "next_step", "compromise"}:
            detail = topic_reply(session, topic, interest, was_discovered)
            if detail:
                return detail
        if analysis.focus == "terms" and proposal:
            terms = proposal["terms"]
            price = f"{terms['price']:,}".replace(",", " ")
            status = (
                "Клиент принял этот пакет; сделка ещё ждёт вашего подтверждения."
                if proposal["client_status"] == "accepted"
                else "Клиент отклонил этот пакет. " + rejection
            )
            return (
                f"В последнем предложении: {price} ₽, {terms['hours']} часов и {terms['deadline_days']} рабочих дней. "
                f"Состав: {terms['scope']}. Оплата: {terms['payment']}. " + status
            )
        detail = topic_reply(session, topic, interest, was_discovered)
        if detail:
            return detail
        if was_discovered and analysis.focus in {"interest", "constraint"}:
            return "Сверим моё ограничение: " + interest + " Можно обсудить, чем каждая сторона готова поступиться."
        terms = session["scenario"]["baseline"]
        price = f"{terms['price']:,}".replace(",", " ")
        return (
            f"Исходно обсуждаем {price} ₽, {terms['hours']} часов и {terms['deadline_days']} рабочих дней. "
            "Уточните, какое условие или причину моей просьбы хотите разобрать."
        )

    if intent == "justify":
        if proposal:
            if proposal["client_status"] == "accepted":
                return ("Ваше обоснование понятно. По последнему пакету моё согласие остаётся: " + proposal["reason"]
                        + " Проверьте выполнимость со своей стороны; затем можно подтвердить договорённость в условиях.")
            return ("Довод о ресурсах команды понятен. Последний пакет отклонён: " + rejection
                    + " Какую встречную уступку вы готовы обсудить?")
        return argument_reply(session, topic, interest, was_discovered)

    if intent == "object":
        if analysis.focus == "relationship":
            return "Давайте продолжим разговор спокойно и по существу. Какое условие проекта вы хотите обсудить?"
        if proposal and proposal["client_status"] == "rejected":
            return "Я тоже пока не могу согласовать этот пакет: " + rejection + " Давайте обсудим, какие условия можно изменить."
        if was_discovered:
            detail = topic_reply(session, "compromise", interest, was_discovered)
            return "Понимаю, что у вашей команды есть границы. " + detail
        return ("Понимаю, что прежние условия при таком изменении для вас не подходят. "
                "Что именно мешает: объём, срок или оплата? Какой встречный вариант вы готовы обсудить?")

    if intent == "propose":
        detail = topic_reply(session, topic, interest, was_discovered)
        return ((detail + " " if detail else "Давайте сопоставим этот подход с ограничениями обеих сторон. ")
                + "Точный пакет оформите в карточке условий. Реплика сама по себе не меняет цену, объём или срок и не подтверждает сделку.")

    if intent == "acknowledge":
        if proposal and proposal["client_status"] == "accepted":
            return "По последнему пакету согласие уже дано. Если вы готовы взять эти обязательства, подтвердите договорённость в условиях."
        if was_discovered:
            return ("Спасибо, что учитываете мою позицию. Теперь расскажите о границах вашей команды: "
                    "что вы можете сохранить и какую уступку попросите взамен?")
        return ("Давайте разберёмся вместе. Можно начать с цели проекта, отдельно обсудить сроки или деньги, "
                "либо сразу объяснить, что ограничивает вашу команду.")

    return fallback_reply(session)
