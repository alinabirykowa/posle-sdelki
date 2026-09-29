"""Conservative delivery signals that make wording consequential in practice.

This is a small, explainable ruleset for explicit hostility and constructive
negotiation moves. It does not infer personality, intent, or business facts.
"""

import re


_QUOTED = re.compile(
    r"```[\s\S]*?(?:```|$)|(?m:^\s*>[^\n]*)|«[^»]*(?:»|$)|"
    r"„[^“]*(?:“|$)|“[^”]*(?:”|$)|‘[^’]*(?:’|$)|"
    r'"[^"]*(?:"|$)|\x27[^\x27]*(?:\x27|$)|`[^`]*(?:`|$)'
)
_HOSTILE = re.compile(
    r"\b(?:идиот\w*|дебил\w*|дурак\w*|туп(?:ой|ая|ое|ые|ица)|"
    r"мудак\w*|урод\w*|сволоч\w*|коз[её]л\w*|ничтож\w*|"
    r"говн\w*|хуй\w*|пизд\w*|еба\w*|бля(?:дь|ть)?|сука\w*|"
    r"fuck\w*|shit\w*|заткнись|закрой рот|пош[её]л\s+ты|"
    r"вы ничего не понимаете|вы полный ноль|что за бред)\b|"
    r"\b(?:немедленно|сейчас же)\s+(?:сделайте|согласуйте|подпишите)\b|"
    r"\bвы\s+(?:обязаны|должны)\s+(?:согласиться|сделать|подписать)\b",
    re.I,
)
_CONSTRUCTIVE = re.compile(
    r"\b(?:понимаю,? что|учитывая ваш|правильно ли я понял|верно ли я понял|"
    r"давайте (?:уточним|обсудим|согласуем|сверим|найд[её]м)|"
    r"предлагаю обсудить|можем согласовать|какой вариант вам подходит|"
    r"готов обсудить|готова обсудить|готовы обсудить|"
    r"если мы сохраним|чтобы учесть ваш|что для вас важнее)\b",
    re.I,
)


def _mask_quotes(text: str) -> str:
    chars = list(text)
    for match in _QUOTED.finditer(text):
        for index in range(match.start(), match.end()):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def assess_delivery(text: str) -> dict:
    """Return a quoted, inspectable wording signal; unknown wording stays neutral."""
    unquoted = _mask_quotes(text)
    hostile = _HOSTILE.search(unquoted)
    if hostile:
        quote = text[hostile.start():hostile.end()]
        return {
            "tone": "hostile",
            "quote": quote,
            "label": "Резкая формулировка",
            "explanation": (
                "Эта формулировка звучит как личная атака или давление. "
                "Собеседник может закрыться и не обсуждать условия до восстановления делового тона."
            ),
        }
    constructive = _CONSTRUCTIVE.search(unquoted)
    if constructive:
        quote = text[constructive.start():constructive.end()]
        return {
            "tone": "constructive",
            "quote": quote,
            "label": "Конструктивный ход",
            "explanation": (
                "Вы явно учитываете позицию собеседника или приглашаете вместе проверить условия. "
                "Такой ход помогает продолжить предметный диалог."
            ),
        }
    return {
        "tone": "neutral",
        "quote": "",
        "label": "Тон не оценён",
        "explanation": (
            "В этой реплике не найден однозначный маркер давления или совместного поиска решения. "
            "Это не ошибка и не оценка личности."
        ),
    }


def advance_client_stance(session: dict, tone: str) -> bool:
    """Update a recoverable boundary; return whether the client remains guarded."""
    if tone == "hostile":
        session["_client_guarded"] = True
        session["_guard_recovery"] = 0
    elif tone == "constructive" and session.get("_client_guarded"):
        recovery = int(session.get("_guard_recovery", 0)) + 1
        session["_guard_recovery"] = recovery
        if recovery >= 2:
            session["_client_guarded"] = False
            session["_guard_recovery"] = 0
    return bool(session.get("_client_guarded"))


def client_reaction(reply: str, tone: str, *, guarded: bool) -> str:
    """Let delivery change the social response without changing deal terms."""
    if tone == "hostile":
        return (
            "Мне сложно продолжать обсуждение в таком тоне. Я пока не буду раскрывать дополнительные детали "
            "и согласовывать вариант. Переформулируйте, пожалуйста, несогласие через конкретное условие."
        )
    if tone == "constructive" and guarded:
        return (
            "Я вижу, что вы вернулись к предметному обсуждению. Давайте сначала восстановим понимание условий. "
            + reply
        )
    return reply
