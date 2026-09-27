"""Conservative, transparent demo rules and the shared model-analysis contract.

The demo classifier recognises a small set of Russian negotiation patterns. It
does not measure negotiation skill or claim to understand arbitrary language.
Semantic results never authorise a deal or change its numerical terms.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Intent = Literal[
    "ask_interest", "clarify", "justify", "object", "propose", "acknowledge",
    "off_topic", "instruction_override", "other",
]
Focus = Literal["interest", "constraint", "terms", "relationship", "none"]


class DialogueAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    intent: Intent
    evidence: str = Field(max_length=500)
    focus: Focus
    uncertain: bool = False

    @model_validator(mode="after")
    def check_semantic_shape(self):
        if self.intent != "other" and not self.evidence.strip():
            raise ValueError("Для распознанного намерения нужна непустая цитата.")
        if self.intent == "ask_interest" and self.focus not in {"interest", "constraint"}:
            raise ValueError("Вопрос об интересе должен касаться интереса или ограничения.")
        return self


def validate_analysis(payload: dict, text: str) -> DialogueAnalysis:
    """Reject malformed output and evidence not quoted from this user message."""
    result = DialogueAnalysis.model_validate(payload)
    if result.evidence not in text:
        raise ValueError("Цитата должна дословно присутствовать в текущей реплике.")
    return result


def _normalise(text: str) -> str:
    return text.lower().replace("ё", "е")


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None


_GENERAL_TOPIC = (
    r"\b(?:проект\w*|задач\w*|работ\w*|срок\w*|дедлайн\w*|цен\w*|стоимост\w*|"
    r"бюджет\w*|оплат\w*|аванс\w*|платеж\w*|деньг\w*|сумм\w*|рубл\w*|"
    r"час\w*|объем\w*|скидк\w*|доплат\w*|марж\w*|затрат\w*|себестоимост\w*|"
    r"команд\w*|ресурс\w*|услови\w*|нагрузк\w*|убыт\w*|прибыл\w*|"
    r"запуск\w*|запуст\w*|сдач\w*|реклам\w*|результат\w*)\b"
)
_SCOPE_TOPIC = r"\b(?:сайт\w*|дизайн\w*|функци\w*|кампани\w*|релиз\w*|выпуск\w*|перенос\w*|перенес\w*|дата\w*)\b"
_PAYMENT_TOPIC = r"\b(?:предоплат\w*|рассрочк\w*|транш\w*|финанс\w*|платит\w*|заплат\w*|кассов\w*|платеж\w*)\b"
_INTEREST = r"\b(?:важн\w*|важен|важнее|критич\w*|приоритет\w*|главн\w*|цел[ьи]\w*|добит\w*|потребност\w*|нужн\w*|необходим\w*|ценност\w*)\b"
_CONSTRAINT = r"\b(?:ограничени\w*|ограничен\w*|лимит\w*|предел\w*|бюджет\w*|аванс\w*|платеж\w*|предоплат\w*|максимум|доступн\w*|меша\w*|препятств\w*)\b"
_CLIENT = r"\b(?:вас|вам|вами|ваш\w*|вы)\b"
_HOSTILITY = r"\b(?:груби\w*|хам\w*|орете|орать|поорать|разговарива\w*|оскорб\w*|крич\w*)\b"
_REQUEST = r"\b(?:расскажите|уточните|объясните|поясните|подскажите|помогите понять|хочу понять|хотел[аи]? бы понять|позвольте узнать)\b"
_QUESTION_START = r"^(?:(?:а|и|но|скажите|пожалуйста|тогда)\s*[, :]?\s*)*(?:что|чего|чем|как\w*|почему|зачем|насколько|сколько|когда|в чем|есть ли)\b"
_REASON = r"\b(?:потому что|так как|поскольку|ведь|поэтому|иначе|из-за|чтобы|значит)\b"


def _mask_quotes(text: str) -> str:
    """Exclude quoted speech/code from intent credit without changing offsets."""
    def blank(match):
        return "".join("\n" if char == "\n" else " " for char in match.group())

    masked = re.sub(r"```[\s\S]*?(?:```|$)", blank, text)
    masked = re.sub(r"(?m)^\s*>[^\n]*", blank, masked)
    return re.sub(
        r"«[^»]*(?:»|$)|„[^“]*(?:“|$)|“[^”]*(?:”|$)|‘[^’]*(?:’|$)|"
        r'"[^"]*(?:"|$)|\x27[^\x27]*(?:\x27|$)|`[^`]*(?:`|$)',
        blank, masked,
    )


def _units(text: str):
    """Yield real evidence plus unquoted text; both share the original span."""
    masked = _mask_quotes(text)
    for match in re.finditer(r"[^.!?;\n]+[.!?;]*", masked):
        start, end = match.span()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        # Overlap keeps a short phrase spanning a window edge recognisable.
        for offset in range(start, end, 350):
            piece_end = min(offset + 500, end)
            searchable = masked[offset:piece_end].strip()
            if searchable:
                yield text[offset:piece_end], searchable
            if piece_end == end:
                break


def _override(s: str) -> bool:
    command = _has(
        r"\b(?:забудь(?:те)?|игнорируй(?:те)?|отмени(?:те)?|перепиши(?:те)?|"
        r"отбрось(?:те)?|нарушь(?:те)?|ignore|disregard|forget)\b", s,
    )
    target = _has(r"\b(?:роль|роли|правил\w*|инструкци\w*|ограничени\w*|систем\w*|prompt|instructions?|rules?)\b", s)
    negated_command = _has(r"\bне\s+(?:забудь(?:те)?|игнорируй(?:те)?|отмени(?:те)?|перепиши(?:те)?|нарушь(?:те)?)\b", s)
    forged_result = _has(
        r"\b(?:считай(?:те)?|объяви(?:те)?|пометь(?:те)?|запиши(?:те)?|признай(?:те)?)\b.*"
        r"\b(?:сделк\w*|договоренност\w*|соглашени\w*|предложени\w*)\b.*"
        r"\b(?:подтвержден\w*|принят\w*|согласован\w*|успешн\w*)\b", s,
    )
    new_role = _has(r"\b(?:теперь ты|ты больше не|you are now)\b.*\b(?:клиент\w*|судь\w*|ассистент\w*|system|assistant|администратор\w*)\b", s)
    return (command and target and not negated_command) or forged_result or new_role


def _not_direct_inquiry(s: str, *, conservative: bool = True) -> bool:
    """Do not credit advice, hypothetical/past speech, or a refusal to ask."""
    inquiry = r"(?:спраш\w*|спрос\w*|расспраш\w*|выясн\w*|уточн\w*|узна\w*|интересова\w*)"
    if _has(r"\bне\s+" + inquiry + r"\b", s):
        return True
    if _has(r"\bне\s+(?:собира\w*|буд\w*|хоч\w*|нуж\w*|стоит|следует)(?:\s+[а-я]+){0,4}\s+" + inquiry + r"\b", s):
        return True
    if _has(r"\b(?:не хочу (?:знать|понимать|понять)|не интересует|неинтересно)\b", s):
        return True
    if _has(r"\b(?:спросил\w*|спрашивал\w*|сказал\w*|говорил\w*|написал\w*|посоветовал\w*|учил\w*)\b", s):
        return True
    if _has(r"\b(?:советует|советуют|рекомендует|рекомендуют)\b", s):
        return True
    if _has(r"\b(?:учитель|преподаватель|тренер|наставник|коллега|клиент|автор|инструктор|он|она)\s+(?:говорит|пишет|спрашивает|объясняет)\b", s):
        return True
    if _has(r"^(?:совет|рекомендация|цитата|образец|пример\s+(?:вопроса|реплики)|шаблон\s+(?:вопроса|реплики)|вот\s+(?:такой вопрос|такая реплика))\b", s):
        return True
    if conservative and _has(r"\b(?:нужно|надо|стоит|следует|можно|попробуйте|рекомендуется)\s+" + inquiry + r"\b", s):
        return True
    return _has(r"\b(?:если бы|представим|предположим|допустим)\b.*\b" + inquiry + r"\b", s)


def owns_interest_evidence(text: str, evidence: str) -> bool:
    """Reject clearly copied/negated evidence without redoing semantic analysis.

    This is a narrow backstop for live model output, not an intent classifier.
    It deliberately accepts unfamiliar wording: the model is responsible for
    determining the intent. Every accepted quote must have a real, unquoted
    occurrence outside an explicit report, hypothetical example, or refusal.
    """
    if not evidence.strip() or evidence not in text:
        return False
    masked = _mask_quotes(text)
    # A direct follow-up after "..., но ..." is owned by the speaker even if
    # the preceding clause reports someone else's question or refuses to ask.
    boundaries = [0]
    for separator in re.finditer(r"[.!?;\n]+|,\s*(?:но|а|однако|теперь|тогда)\s+", masked, flags=re.IGNORECASE):
        boundaries.extend([separator.start(), separator.end()])
    boundaries.append(len(text))
    contexts = list(zip(boundaries[::2], boundaries[1::2]))
    start = text.find(evidence)
    while start != -1:
        end = start + len(evidence)
        for context_start, context_end in contexts:
            left, right = max(start, context_start), min(end, context_end)
            if left >= right or not _has(r"\w", masked[left:right]):
                continue
            context = _normalise(masked[context_start:context_end].strip())
            if not _not_direct_inquiry(context, conservative=False):
                return True
        start = text.find(evidence, start + 1)
    return False


def _is_question(s: str) -> bool:
    if _not_direct_inquiry(s):
        return False
    return "?" in s or _has(_REQUEST, s) or _has(_QUESTION_START, s)


def _constraint_paraphrase(s: str, relevant: bool):
    """Recognise a few concrete constraint questions without keyword credit.

    These patterns run only after the question/quotation guards. Client-directed
    comparisons and spending ceilings differ from a speaker naming their own
    interest; the collective "нам нужно попасть" can describe a client's cap.
    """
    if not relevant:
        return None
    if (
        _has(r"\b(?:что|какой вариант|какая уступка)\b", s)
        and _has(r"\b(?:вам|для вас)\b", s)
        and _has(r"\b(?:болезненнее|хуже|тяжелее|терпимее|приемлемее|предпочтительнее)\b", s)
        and _has(r"\bили\b", s)
    ):
        return "interest"

    financial = _has(r"\b(?:сумм\w*|цен\w*|стоимост\w*|бюджет\w*|оплат\w*)\b", s)
    ceiling = _has(r"\b(?:в какие рамки|в каких рамках|до какой суммы|какой (?:предел|потолок))\b", s)
    client_capacity = _has(r"\bвы\b[^.!?]{0,60}\b(?:можете|могли|сможете|готовы)\b", s)
    if financial and ceiling and client_capacity:
        return "constraint"

    # Ask which of two payment constraints applies. "Нас" can name the two
    # negotiating parties; an explicit "меня"/"нашу студию" is not credited.
    shared_constraint = _has(r"\b(?:нас|вас)\s+(?:ограничива\w*|сдержива\w*)\b", s)
    named_constraint = _has(r"\bограничение\s+связано\b", s)
    full_price = _has(r"\b(?:(?:общ\w*|вся|всю|всей|полная)\s+(?:сумм\w*|цен\w*|стоимост\w*)|сумма\s+целиком)\b", s)
    first_payment = _has(r"\b(?:аванс\w*|перв\w*\s+(?:платеж\w*|взнос\w*)|на старте|в начале)\b", s)
    if (shared_constraint or named_constraint) and full_price and first_payment and _has(r"\bили\b", s):
        return "constraint"
    return None


def _interest(s: str, relevant: bool, has_discovered: bool):
    if not _is_question(s):
        return None
    if _has(_HOSTILITY, s) and not relevant:
        return None
    # A check of an already stated understanding is not new discovery.
    if _has(r"\b(?:правильно ли|верно ли|я правильно|я верно|(?:правильно|верно)\s+(?:я\s+)?(?:понимаю|понял[аи]?))\b", s):
        return None
    if _has(r"\b(?:не хочу (?:знать|понимать|понять)|не интересует)\b", s):
        return None
    # New conversational paraphrases still need a client-owned target. A
    # question about our own spending cap/result cannot reveal their priority.
    own_constraint = _has(
        r"\b(?:(?:я|мы)\s+(?:готов\w*|мож\w*|смож\w*)|наш\w*|"
        r"мо[йяеюи]\w*|для меня|для нас)\b", s,
    )
    direct_client = _has(r"\b(?:вы|вам|для вас)\b", s)
    if own_constraint and not direct_client:
        return None
    if _has(r"\b(?:что стоит за вашей просьбой|что вы готовы предложить со своей стороны)\b", s):
        return "interest"
    if _has(r"\bкакие условия для вас можно изменить\b", s):
        return None if has_discovered else "constraint"
    if _has(r"\bсколько\b.*\bвы\s+готовы\b.*\b(?:внести|заплатить)\b", s):
        return "constraint"
    if _has(r"\bнасколько\s+вы\s+готовы\s+уступить\b", s):
        return "constraint"
    if _has(r"\bчто\s+обязательно\s+должно\s+войти\s+в\s+результат\b", s):
        return "interest"
    if (_has(r"\bлимит\b", s) and _has(r"\bвсего\s+проекта\b", s)
            and _has(r"\bили\b.*\bпервого\s+платежа\b", s)):
        return "constraint"
    client = _has(_CLIENT, s)
    own_demand = _has(r"\b(?:почему|зачем)\s+(?:именно\s+)?(?:я|мы)\b", s)
    if own_demand:
        return None
    constraint_paraphrase = _constraint_paraphrase(s, relevant)
    # Mentioning "your project" does not turn a question about MY interests
    # into a question about the client. Allow explicit mixed questions, though.
    own_target = r"\b(?:мне|нам|для меня|для нас|мо[йяие]|наш[аи]?)\b"
    client_target = r"\b(?:вам|для вас)\b"
    own_interest = _has(own_target + r"[^,!?]{0,45}" + _INTEREST, s) or _has(_INTEREST + r"[^,!?]{0,30}" + own_target, s)
    client_interest = _has(client_target + r"[^,!?]{0,45}" + _INTEREST, s) or _has(_INTEREST + r"[^,!?]{0,30}" + client_target, s)
    constraint_question = _has(r"\b(?:какие|какое|какой|что за|есть ли)\b.*\b(?:ограничени\w*|лимит\w*|предел\w*)\b", s)
    # "Нам нужно учесть" describes the act of checking constraints together,
    # not a personal need. Keep explicit ownership ("наши ограничения") out.
    collective_inquiry = (
        constraint_question
        and _has(r"\bнам\s+(?:нужно|необходимо|важно)\s+(?:учесть|учитывать)\b", s)
        and not _has(r"\b(?:мне|для меня|для нас|мо[йяеих]\w*|наш\w*)\b", s)
    )
    if own_interest and not client_interest and not constraint_paraphrase and not collective_inquiry:
        return None
    if constraint_paraphrase:
        return constraint_paraphrase
    if client and _has(_INTEREST, s):
        return "constraint" if _has(_CONSTRAINT, s) else "interest"
    if constraint_question:
        return "constraint"
    if client and _has(_CONSTRAINT, s):
        return "constraint"
    if relevant and _has(r"\b(?:почему|зачем|что стоит за|с чем связан\w*|из-за чего)\b", s):
        return "constraint" if _has(_CONSTRAINT, s) else "interest"
    if relevant and _has(r"\b(?:что\s+(?:будет|случится|произойдет|изменится)|чем\s+(?:грозит|обернется)|как\s+повлияет)\b", s):
        return "constraint"
    if relevant and _has(r"\b(?:какой|какого|что|чего)\b.*\b(?:результат\w*|добит\w*|ожида\w*|получить)\b", s) and (_has(_REQUEST, s) or client):
        return "interest"
    if relevant and _has(r"\b(?:сколько|какую сумму|какой размер|когда)\b", s) and _has(r"\b(?:можете|готовы|доступн\w*|располага\w*)\b", s):
        return "constraint"
    if relevant and _has(r"\b(?:каки\w*|что|чем|можно ли|допустим ли)\b", s) and _has(r"\b(?:исключ\w*|отказ\w*|пожертв\w*|поступит\w*|перенос\w*|перенес\w*)\b", s):
        return None if has_discovered else "constraint"
    return None


def _justifies(s: str, topic_pattern: str) -> bool:
    if not _has(topic_pattern, s):
        return False
    # A causal marker alone is not evidence of a business argument. The reason
    # itself must mention a relevant constraint, resource, or consequence.
    for reason in re.finditer(_REASON, s):
        explanation = s[reason.end():]
        if _has(topic_pattern, explanation) or _has(
            r"\b(?:не успе\w*|не хват\w*|не улож\w*|не покро\w*|убыточн\w*|"
            r"переработ\w*|задерж\w*|сорв\w*|не выполни\w*)\b", explanation,
        ):
            return True
    return False


# Topics route prepared responses only; they never grant interest-discovery credit.
_TOPIC_PATTERNS = (
    ("summary", r"\b(?:итог\w*|резюм\w*|подытож\w*|сверим условия|правильно ли|верно ли|я правильно|я верно|(?:правильно|верно)\s+(?:я\s+)?(?:понимаю|понял[аи]?))\b"),
    ("risk", r"\b(?:риск\w*|опасн\w*|сорв\w*|выполним\w*)\b"),
    ("next_step", r"\b(?:что дальше|дальнейш\w*|следующ\w* шаг\w*|как продолжить|с чего начать|с чего начнем|что предложить)\b"),
    ("compromise", r"\b(?:компромисс\w*|уступ\w*|взамен|альтернатив\w*|другой вариант|сравним варианты|какие варианты|разбить на этапы|со своей стороны|условия для вас можно изменить|обмен\w*)\b"),
    ("payment", r"\b(?:аванс\w*|предоплат\w*|платеж\w*|рассроч\w*|оплат\w*|транш\w*|внести на старте)\b"),
    ("deadline", r"\b(?:срок\w*|дедлайн\w*|дат[аыуе]\w*|дней|дня|день|перенос\w*|перенести|сдач\w*|когда)\b"),
    ("budget", r"\b(?:бюджет\w*|цен[аыуе]\w*|стоимост\w*|скидк\w*|денег|деньг\w*|сумм\w*)\b"),
    ("scope", r"\b(?:объем\w*|задач\w*|функци\w*|час\w*|исключ\w*|сократ\w*|сокращ\w*|работ\w*)\b"),
    ("goal", r"\b(?:цел[ьи]\w*|цел[ья]|результат\w*|приоритет\w*|важн\w*|важнее|главн\w*)\b"),
    ("reason", r"\b(?:почему|зачем|причин\w*|обосну\w*|за (?:вашей )?просьбой|за отказом|не подходит|ограничени\w*)\b"),
    ("terms", r"\b(?:пакет\w*|услови\w*)\b"),
    ("relationship", r"\b(?:здравствуйте|добрый день|добрый вечер|привет|рад[аы]? знакомству|понимаю вас|понимаю вашу позицию|слышу вас|спасибо|благодарю)\b"),
)


def dialogue_topic(text: str, *, has_discovered: bool = False):
    """Return a topic from owned speech, never from quoted/negated examples.

    This helper is deliberately separate from semantic intent and scoring. A
    fragment such as «про сроки» can select a useful branch without pretending
    that the speaker has asked about the client's hidden priority.
    """
    for _, searchable in _units(text):
        s = _normalise(searchable)
        if _not_direct_inquiry(s) or _has(
            r"\bне\s+(?:(?:хочу|буду|будем|нужно|надо)\s+)?(?:обсужд\w*|говор\w*|касаться|затраг\w*)\b", s,
        ):
            continue
        selection = re.search(r"\b(?:обсудим|обсудить|поговорим|разберем)\s+(.+)", s)
        if selection:
            s = selection.group(1)
        for topic, pattern in _TOPIC_PATTERNS:
            if _has(pattern, s):
                return topic
    return None


def _topic_selection(s: str) -> bool:
    """Small conversational fragments/requests, rather than arbitrary keywords."""
    if _not_direct_inquiry(s):
        return False
    if _has(r"\bне\s+(?:(?:хочу|буду|будем|нужно|надо)\s+)?(?:обсужд\w*|говор\w*|касаться|затраг\w*)\b", s):
        return False
    topic = dialogue_topic(s)
    if not topic:
        return False
    if topic in {"summary", "next_step"} or "сравним варианты" in s or "разбить на этапы" in s:
        return True
    if _has(r"^(?:(?:а|ну|давайте|лучше|сначала)\s+)*(?:про|о|об|насчет)\s+", s):
        return True
    if _has(r"\b(?:обсудим|обсудить|разберем|разобрать|поговорим|расскажите|уточните|поясните|начнем с)\b", s):
        return True
    # One-word answers to the client's branch menu are valid selections.
    return bool(re.fullmatch(r"(?:цель|цели|сроки|срок|дата|бюджет|цена|оплата|аванс|объем|задачи|компромисс|причина|ограничения|(?:конкретный )?пакет условий)(?: проекта)?[.!?]*", s.strip()))


def classify_demo(text: str, scenario_id: str, has_discovered: bool = False) -> DialogueAnalysis:
    """Classify recognisable patterns; uncertainty never invents an interest."""
    if scenario_id not in {"scope", "discount"}:
        raise ValueError("Неизвестный сценарий для демоанализа.")
    topic = _GENERAL_TOPIC + "|" + (_SCOPE_TOPIC if scenario_id == "scope" else _PAYMENT_TOPIC)
    pieces = [(piece, _normalise(searchable)) for piece, searchable in _units(text)]

    def result(intent: Intent, piece: str, focus: Focus, uncertain: bool = False):
        return validate_analysis({"intent": intent, "evidence": piece, "focus": focus, "uncertain": uncertain}, text)

    # Security-related requests win even when another sentence contains a
    # legitimate interest question. They still cannot mutate business state.
    for piece, s in pieces:
        if _override(_normalise(piece)):
            return result("instruction_override", piece, "none")
    for piece, s in pieces:
        focus = _interest(s, _has(topic, s), has_discovered)
        if focus:
            return result("ask_interest", piece, focus)
    for piece, s in pieces:
        if _justifies(s, topic):
            return result("justify", piece, "constraint")
    for piece, s in pieces:
        if _is_question(s) and _has(r"\bчто\b.*\b(?:в моем предложении|вам не подход\w*)\b", s):
            return result("clarify", piece, "terms")
        if _has(_HOSTILITY, s) and not _has(topic, s):
            return result("object", piece, "relationship")
        if _has(r"\b(?:не соглас(?:ен|н[аы])|не могу|не можем|не готов\w*|не подход\w*|не устраива\w*|не устро\w*|невозможн\w*|слишком дорого|это дорого)\b", s):
            return result("object", piece, "terms")
        if _has(r"\b(?:почему|зачем)\s+(?:именно\s+)?(?:я|мы)\b", s) and _has(topic, s):
            return result("object", piece, "terms")
    for piece, s in pieces:
        if _is_question(s) and (_has(topic, s) or _has(_INTEREST, s) or dialogue_topic(s) not in {None, "relationship"}):
            focus = "interest" if _has(_INTEREST, s) and not _has(topic, s) else "terms"
            return result("clarify", piece, focus)
    for piece, s in pieces:
        if _topic_selection(s):
            return result("clarify", piece, "terms")
    for piece, s in pieces:
        agreement = _has(r"\b(?:соглас(?:ен|н[аы])|договорились|принимаю|обещаю)\b", s)
        offer = _has(r"\b(?:предлагаю|предлагаем|давайте|можем предложить|готов[аы]? взять)\b", s)
        if agreement or (offer and (_has(topic, s) or _has(r"\b(?:компромисс\w*|вариант\w*)\b", s))):
            return result("propose", piece, "terms")
    for piece, s in pieces:
        if not _has(topic, s) and _has(r"\b(?:погод\w*|рецепт\w*|анекдот\w*|стих\w*|футбол\w*|президент\w*|гороскоп\w*|котик\w*)\b", s):
            return result("off_topic", piece, "none")
    for piece, s in pieces:
        if _has(r"^(?:да[, ]+)?(?:понятно|понял[аи]?|спасибо|благодарю|хорошо|окей|ок|услышал[аи]?|учту|здравствуйте|добрый день|добрый вечер|привет|понимаю вас|понимаю вашу позицию|слышу вас)\b", s):
            return result("acknowledge", piece, "relationship")
    return result("other", "", "none", uncertain=True)
