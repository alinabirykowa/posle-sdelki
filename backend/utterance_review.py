"""Turn-by-turn business-language review, built only from the saved transcript.

Quotes and problem spans always point into the participant's original message.
These conservative rules provide practice feedback; they are not a claim of
human-level semantic understanding and never invent deal terms.
"""

import re

from .feedback import _transcript
from .delivery import assess_delivery


_TOKEN = re.compile(r"[а-яёa-z0-9]+", re.I)
_VOWELS = set("аеёиоуыэюяaeiouy")
_QUOTED = re.compile(
    r"```[\s\S]*?(?:```|$)|(?m:^\s*>[^\n]*)|«[^»]*(?:»|$)|"
    r"„[^“]*(?:“|$)|“[^”]*(?:”|$)|‘[^’]*(?:’|$)|"
    r'"[^"]*(?:"|$)|\x27[^\x27]*(?:\x27|$)|`[^`]*(?:`|$)'
)
_INSULT = re.compile(
    r"\b(?:идиот\w*|дебил\w*|дурак\w*|туп(?:ой|ая|ое|ые|ица|ицы)|"
    r"мудак\w*|урод\w*|сволоч\w*|коз[её]л\w*|мерзав\w*|"
    r"ничтож\w*|клоун\w*|заткнись|пош[её]л\s+ты|"
    r"вы\s+(?:ничего\s+не\s+понимаете|полный\s+ноль))\b",
    re.I,
)
_PROFANITY = re.compile(
    r"\b(?:бля(?:дь|ть|ха)?|бляд\w*|хуй\w*|пизд\w*|еба\w*|ебл\w*|"
    r"нахер|нафиг|сука\w*|говн\w*|сран\w*|fuck\w*|shit\w*)\b",
    re.I,
)
_DISPARAGING = re.compile(r"\b(?:фигн\w*|хрен\w*|отстой\w*|чушь|бред\w*|ч[её]\s+за\w*|закрой\s+рот|заткнитесь)\b", re.I)
_SLANG = re.compile(r"\b(?:хз|ч[её]|лол|кек|изи|забей)\b", re.I)
_VAGUE = re.compile(
    r"^(?:ок(?:ей)?|ага|понятно|хорошо|как скажете|посмотрим|"
    r"может быть|не знаю|без проблем|сделаем|решим|договоримся|"
    r"норм|ладно|давайте)[.!?… ]*$",
    re.I,
)
_YES_NO = re.compile(
    r"^\s*(?:да|нет|согласен|согласна|не согласен|не согласна|"
    r"подходит|не подходит|готов|готова|не готов|не готова)\s*[.!?… ]*$",
    re.I,
)
_QUESTION = re.compile(
    r"\?|\b(?:расскажите|уточните|объясните|подскажите|помогите понять|"
    r"хочу понять|почему|насколько|сколько|какой|какая|какие|"
    r"есть ли|сможете ли|можете ли|готовы ли)\b",
    re.I,
)
_ASK_BUDGET = re.compile(r"бюджет|цен[аыуе]|стоимост|сумм|сколько\s+стоит|оплат|аванс|плат[её]ж", re.I)
_ASK_TIME = re.compile(r"срок|дат[аыуе]|когда|дедлайн|запуск|успеть|успеете|дней|недел", re.I)
_ASK_SCOPE = re.compile(r"объ[её]м|задач|работ|функци|часов|включить|состав", re.I)
_ASK_PRIORITY = re.compile(r"важн|приоритет|главн|цель|результат|предпочит", re.I)
_ASK_REASON = re.compile(r"почему|зачем|по какой причине|что стоит за", re.I)
_DIRECT_YES_NO = re.compile(r"\b(?:сможете|успеете|успеем|устраивает|подходит|согласны)\b|\b(?:можете|готовы|будете|устраивает|верно)\s+ли\b", re.I)
_NUMBER = re.compile(
    r"\d|\b(?:ноль|один|одна|одно|два|две|три|четыре|пять|шесть|семь|"
    r"восемь|девять|десять|двадцать|тридцать|сорок|пятьдесят|"
    r"сто|двести|тысяч\w*|миллион\w*)\b|₽|руб\w*|процент\w*",
    re.I,
)
_DATE = re.compile(r"\d+\s*(?:рабоч\w*\s*)?(?:дн\w*|недел\w*|месяц\w*)|понедельник|вторник|сред\w*|четверг|пятниц\w*|завтра|сегодня|до\s+\w+", re.I)
_SCOPE = re.compile(r"\b(?:задач\w*|работ\w*|функци\w*|модул\w*|этап\w*|объ[её]м\w*|час\w*|исключ\w*|включ\w*|остав\w*)\b", re.I)
_TOPIC = re.compile(
    r"\b(?:проект\w*|задач\w*|работ\w*|срок\w*|дат\w*|цен\w*|стоимост\w*|"
    r"бюджет\w*|оплат\w*|аванс\w*|плат[её]ж\w*|час\w*|объ[её]м\w*|"
    r"услови\w*|команд\w*|ресурс\w*|результат\w*|приоритет\w*|"
    r"ограничени\w*|вариант\w*|соглас\w*|договор\w*|сделк\w*|"
    r"подход\w*|предложени\w*|да|нет|сможем|не могу)\b",
    re.I,
)
_PROMISE = re.compile(
    r"\b(?:обещаю|гарантирую|точно сделаем|всё сделаем|успеем|"
    r"без проблем сделаем|бер[её]м на себя|сделаем бесплатно|"
    r"любую цену|любые сроки|обязуемся|гарантируем)\b",
    re.I,
)
_SAFE_PROMISE = re.compile(
    r"\b(?:не обещаю|не могу гарантировать|не буду обещать|не гарантируем|"
    r"не успеем|не уверены,? что успеем|не готов\w* обещать|"
    r"не могу взять на себя)\b",
    re.I,
)
_KNOWN_ABBREVIATIONS = {"ооо", "ип", "ндс", "нпд", "тз", "кп", "тз", "it", "b2b", "crm", "kpi", "api", "ux", "ui", "hr", "ai"}
_KEYBOARD_ROWS = (
    "йцукенгшщзхъ",
    "фывапролджэ",
    "ячсмитьбю",
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
)
_ALPHABET_ROWS = ("абвгдежзийклмнопрстуфхцчшщ", "abcdefghijklmnopqrstuvwxyz")
_STOP = {
    "это", "для", "что", "как", "или", "если", "мы", "вы", "вам", "нас", "наш", "ваш", "мне", "нам", "они", "она", "его", "есть", "при", "про", "так", "уже", "тогда", "пожалуйста", "клиент", "проект", "задачи", "работы", "можно", "нужно", "будет", "будем", "быть", "хочу", "могу", "сможем", "который", "которые", "важно", "важнее", "нужен", "нужна", "нужно", "пожалуйста",
}


def _mask_quotes(text):
    """Blank quotations without changing offsets so quotes aren't attributed."""
    chars = list(text)
    for match in _QUOTED.finditer(text):
        for index in range(match.start(), match.end()):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def _context(session, position):
    for message in reversed(session.get("messages", [])[:position]):
        if isinstance(message, dict) and message.get("role") == "assistant" and isinstance(message.get("text"), str):
            return {"message_id": message.get("id", ""), "quote": message["text"]}
    return None


def _matches(pattern, text):
    return list(pattern.finditer(text))


def _problem(text, spans, title, explanation, improved):
    items = []
    seen = set()
    for match in spans:
        quote = text[match.start():match.end()]
        if quote.strip() and (match.start(), match.end()) not in seen:
            seen.add((match.start(), match.end()))
            items.append({"quote": quote, "title": title, "explanation": explanation, "improved_reply": improved})
    return items


def _random_tokens(text):
    """Find high-confidence keyboard mashes without penalizing real words.

    Consonant clusters alone are not enough: Russian business words such as
    "встреча" and "строительство" contain clusters that look unusual to a
    simple vowel-ratio heuristic. Treat those as language unless there is a
    long keyboard/alphabet run, repeated character, or an exceptionally
    implausible long token.
    """
    noise = []
    for match in _TOKEN.finditer(text):
        token = match.group()
        folded = token.lower()
        if folded in _KNOWN_ABBREVIATIONS:
            continue
        letters = [char for char in folded if char.isalpha()]
        if not letters:
            continue
        vowels = sum(char in _VOWELS for char in letters)
        longest_consonants = max((len(part) for part in re.findall(r"[^аеёиоуыэюяaeiouy]+", folded)), default=0)
        repeated_mash = bool(re.fullmatch(r"([а-яёa-z])\1{3,}", folded))
        keyboard_run = any(
            any(row[index:index + 5] in folded for index in range(len(row) - 4))
            for row in _KEYBOARD_ROWS
        )
        alphabet_run = any(
            any(row[index:index + 6] in folded for index in range(len(row) - 5))
            for row in _ALPHABET_ROWS
        )
        latin_mash = (
            bool(re.fullmatch(r"[a-z]{10,}", folded))
            and vowels / len(letters) < 0.16
            and longest_consonants >= 5
        )
        cyrillic_mash = (
            bool(re.fullmatch(r"[а-яё]{10,}", folded))
            and vowels / len(letters) < 0.20
            and longest_consonants >= 5
        )
        # In Russian, й is preceded by a vowel (май, бой, край), not a
        # consonant. This catches vowel-rich keyboard mashes such as
        # "вавотфвэфй" that the conservative vowel-ratio check misses.
        impossible_cyrillic = (
            bool(re.fullmatch(r"[а-яё]{8,}", folded))
            and bool(re.search(r"[бвгджзйклмнпрстфхцчшщ]й", folded))
        )
        if latin_mash or cyrillic_mash or impossible_cyrillic or repeated_mash or keyboard_run or alphabet_run:
            noise.append(match)
    return noise


def _question_kind(context):
    if not context or not _QUESTION.search(context):
        return "none"
    if _DIRECT_YES_NO.search(context):
        return "yes_no"
    if _ASK_BUDGET.search(context):
        return "budget"
    if _ASK_TIME.search(context):
        return "time"
    if _ASK_SCOPE.search(context):
        return "scope"
    if _ASK_PRIORITY.search(context):
        return "priority"
    if _ASK_REASON.search(context):
        return "reason"
    return "open"


def _response_status(text, context):
    kind = _question_kind(context or "")
    if kind == "none":
        return "not_question", "В предыдущей реплике не найден прямой вопрос; проверяем ясность ответа и деловой тон."
    if kind == "yes_no":
        if _YES_NO.fullmatch(text.strip()):
            return "answered", "Вы прямо ответили на вопрос «да/нет». Короткий ответ уместен; причина нужна только если без неё позиция неясна."
        return "partial", "Вопрос предполагал прямой ответ «да/нет», но он не прозвучал явно."
    if kind == "budget":
        if _NUMBER.search(text) or re.search(r"уточн\w*|провер\w*|пока не зна\w*|не готов\w* назвать", text, re.I):
            return "answered", "Вы назвали денежный ориентир или честно обозначили, что его нужно проверить."
        return "missed", "Клиент спросил о бюджете или цене, но в ответе нет суммы и нет прямого пояснения, что её нужно уточнить."
    if kind == "time":
        if _DATE.search(text) or re.search(r"уточн\w*|провер\w*|пока не зна\w*|не готов\w* подтвердить", text, re.I):
            return "answered", "Вы обозначили срок или прямо сказали, что его нужно проверить."
        return "missed", "Клиент спросил о сроке, но в ответе нет даты/периода и нет пояснения, что срок ещё проверяется."
    if kind == "scope":
        if _SCOPE.search(text) or re.search(r"уточн\w*|провер\w*|пока не зна\w*", text, re.I):
            return "answered", "В ответе есть информация об объёме или честное указание на необходимость уточнения."
        return "missed", "Клиент спросил о составе или объёме работ, но ответ не уточняет, какие работы имеются в виду."
    if kind == "priority":
        if _ASK_PRIORITY.search(text) or _TOPIC.search(text) and len(_TOKEN.findall(text)) >= 3:
            return "answered", "Вы обозначили приоритет или продолжили уточнять, что для клиента важно."
        return "partial", "Клиент спросил о приоритете; ответ не называет, что именно для вас или клиента важнее."
    if kind == "reason":
        if re.search(r"потому что|поскольку|так как|причин\w*|связан\w* с|не знаю|уточн\w*", text, re.I):
            return "answered", "В ответе названа причина или прямо обозначено, что её нужно уточнить."
        return "partial", "Клиент спросил о причине; позиция прозвучала без объяснения «почему»."
    words = {word.lower() for word in _TOKEN.findall(context) if len(word) > 3} - _STOP
    reply = {word.lower() for word in _TOKEN.findall(text) if len(word) > 3} - _STOP
    if words & reply or len(_TOKEN.findall(text)) >= 5:
        return "answered", "В ответе есть слова по теме вопроса или развёрнутое пояснение."
    if _QUESTION.search(text):
        return "partial", "Вы задали встречный вопрос, но не ответили на вопрос клиента. Сначала ответьте, затем уточняйте."
    return "missed", "Клиент задал вопрос, но ответ не содержит понятного ответа по существу."


def _base_review(message, context):
    return {
        "message_id": message["id"],
        "quote": message["text"],
        "context": context,
        "problems": [],
        "issues": [],
        "response_status": "not_question",
        "response_explanation": "",
    }


def _finish(card, status, verdict, rule, explanation, improved, issues=(), problems=()):
    card.update({
        "status": status,
        "verdict": verdict,
        "rule": rule,
        "explanation": explanation,
        "improved_reply": improved,
        "issues": list(issues),
        "problems": list(problems),
    })
    return card


def _analyze(message, context):
    text = message["text"]
    card = _base_review(message, context)
    card["delivery"] = assess_delivery(text)
    if (message.get("kind") or "message") == "proposal":
        card["response_explanation"] = "Вы выбрали готовое предложение из интерфейса. Это не ваша самостоятельная формулировка."
        return _finish(
            card, "improve", "needs_improvement", "Готовый вариант не проверяет вашу формулировку",
            "Пункт из карточки нельзя считать доказательством навыка самостоятельного ответа. Перед подтверждением проверьте, что перечисленные условия действительно подходят.",
            "Своими словами объясните, почему этот вариант учитывает интересы обеих сторон.",
            ["template_choice"],
        )

    if not text.strip():
        card["response_status"] = "unclear"
        card["response_explanation"] = "Отправлен пустой ответ."
        return _finish(card, "unclear", "incorrect", "Пустая реплика", "Пустое сообщение не передаёт позицию и не отвечает собеседнику.", "Напишите ответ словами или прямо попросите время, чтобы проверить информацию.", ["unintelligible"])

    unquoted = _mask_quotes(text)
    insult = _matches(_INSULT, unquoted)
    profanity = _matches(_PROFANITY, unquoted)
    disparaging = _matches(_DISPARAGING, unquoted)
    slang = _matches(_SLANG, unquoted)
    lexical_findings = []
    if insult:
        lexical_findings.append((
            "Оскорбление", insult,
            "Это слово направлено на человека и переводит обсуждение условий в личный конфликт.",
            "Назовите несогласие с условием без оценки собеседника.", "rudeness",
        ))
    if profanity:
        lexical_findings.append((
            "Ненормативная лексика", profanity,
            "Это грубое слово неуместно в деловой переписке и мешает обсуждать задачу по существу.",
            "Замените его нейтральным описанием проблемы.", "inappropriate_language",
        ))
    if disparaging:
        lexical_findings.append((
            "Пренебрежительная формулировка", disparaging,
            "Это слово обесценивает предложение или собеседника и не объясняет, какое именно условие не подходит.",
            "Назовите конкретное несоответствие: цена, срок, объём или состав работ.", "disparaging_language",
        ))
    if slang:
        lexical_findings.append((
            "Слишком разговорное слово", slang,
            "Это сокращение или сленг может быть непонятен собеседнику и снижает деловой тон.",
            "Замените его нейтральной формулировкой и изложите позицию полностью.", "informal_language",
        ))
    if lexical_findings:
        # Keep every flagged occurrence so repeated bad words and mixed issues
        # remain visible instead of collapsing into one generic verdict.
        problems = []
        for title, matches, explanation, improved, _code in lexical_findings:
            problems.extend(_problem(text, matches, title, explanation, improved))
        severe = bool(insult or profanity)
        codes = list(dict.fromkeys(item[4] for item in lexical_findings))
        card["response_status"] = "not_question"
        card["response_explanation"] = (
            "Сначала замените подсвеченные грубые или оскорбительные слова, "
            "затем изложите деловую позицию."
            if severe else
            "Сначала замените подсвеченные разговорные формулировки, затем проверьте, что ответ по существу."
        )
        if severe:
            return _finish(
                card, "unclear", "incorrect", "В реплике есть слова, недопустимые для деловой переписки",
                "Подсветил каждое найденное оскорбительное или грубое слово отдельно.",
                "Опишите проблему нейтрально и укажите, с каким конкретно условием вы не согласны.", codes, problems,
            )
        return _finish(
            card, "improve", "needs_improvement", "Замените разговорные и пренебрежительные слова",
            "Подсветил каждую найденную формулировку, которая звучит резко или слишком разговорно.",
            "Назовите конкретное несоответствие и предложите обсудить подходящий вариант.", codes, problems,
        )

    random = _random_tokens(unquoted)
    words = _TOKEN.findall(unquoted)
    if random and len(random) >= max(1, len([word for word in words if re.search(r"[а-яёa-z]", word, re.I)]) // 2):
        problems = _problem(text, random, "Похоже на случайный набор букв", "По этому фрагменту нельзя восстановить смысл. В деловой переписке собеседник не сможет понять вашу позицию.", "Удалите случайный текст и отправьте осмысленный ответ на вопрос клиента.")
        card["response_status"] = "unclear"
        card["response_explanation"] = "Содержание реплики не распознано, поэтому ответ на вопрос оценить нельзя."
        return _finish(card, "unclear", "incorrect", "Случайный набор букв не является деловым ответом", "Подсветил фрагмент, который выглядит как случайный ввод.", "Напишите заново: коротко ответьте на вопрос клиента или попросите время на проверку.", ["unintelligible"], problems)

    context_text = context["quote"] if context else ""
    response_status, response_explanation = _response_status(text, context_text)
    card["response_status"] = response_status
    card["response_explanation"] = response_explanation

    vague = _matches(_VAGUE, unquoted)
    if vague:
        problems = _problem(text, vague, "Слишком общий ответ", "«Понятно» или «посмотрим» не сообщает позицию и не отвечает на содержательный вопрос.", "Добавьте конкретный ответ, причину или то, что нужно проверить.")
        return _finish(card, "improve", "needs_improvement", "Не подменяйте содержательный ответ общим подтверждением", "Клиенту непонятно, что именно вы принимаете, отклоняете или собираетесь уточнить.", "Сначала ответьте по существу, затем задайте свой вопрос.", ["vague"], problems)

    abbreviation = re.fullmatch(r"\s*([А-ЯЁA-Z]{2,8})[.!?… ]*", text)
    if abbreviation:
        explanation = "Аббревиатура может быть понятна обеим сторонам, но по одной записи нельзя проверить её значение. Не считаю её ошибкой автоматически."
        card["response_status"] = "unclear" if response_status not in {"answered", "not_question"} else response_status
        problems = _problem(text, [abbreviation], "Сокращение не расшифровано", explanation, "Если сокращение ещё не вводили, расшифруйте его при первом употреблении.")
        return _finish(card, "improve", "uncertain", "Аббревиатуру нужно проверить по контексту", explanation, "Если сокращение ещё не вводили, расшифруйте его при первом употреблении.", ["insufficient_context"], problems)

    promise = _matches(_PROMISE, unquoted)
    if promise and not _SAFE_PROMISE.search(unquoted):
        problems = _problem(text, promise, "Безусловное обещание", "Эта формулировка звучит как гарантия, хотя в диалоге нет подтверждения ресурсов или выполнимости условия.", "Сначала назовите, что проверите, и подтвердите обязательство после проверки.")
        return _finish(card, "improve", "needs_improvement", "Не обещайте то, что ещё не проверили", "Подсветил формулировку, которая может создать обязательство без подтверждённых условий.", "«Проверю доступные ресурсы и вернусь с подтверждённым ответом». Не добавляйте срок проверки, если он не согласован.", ["risky_promise"], problems)

    if (
        not _TOPIC.search(unquoted)
        and not _QUESTION.search(unquoted)
        and not _NUMBER.search(unquoted)
        and not _YES_NO.fullmatch(unquoted.strip())
        and not re.search(r"провер\w*|уточн\w*|пока не зна\w*", unquoted, re.I)
    ):
        problems = _problem(text, [re.match(r"[\s\S]+", text)], "Ответ не связан с темой разговора", "В этой реплике не удалось найти связь с вопросом или обсуждаемым деловым условием.", "Вернитесь к вопросу клиента и ответьте на него. Если это шутка или побочная тема, перенесите её за рамки деловой переписки.")
        return _finish(card, "unclear", "incorrect", "Ответ должен относиться к теме переговоров", "По текущей реплике собеседник не поймёт вашу позицию по обсуждаемому вопросу.", "Ответьте на последнюю реплику клиента или обозначьте, какую информацию нужно уточнить.", ["off_topic"], problems)

    if response_status == "missed":
        problems = _problem(text, [re.match(r"[\s\S]+", text)], "Нет ответа на вопрос клиента", response_explanation, "Дайте прямой ответ. Если данных нет, скажите, что именно нужно уточнить, и не придумывайте цифру или срок.")
        return _finish(card, "unclear", "incorrect", "Сначала ответьте на вопрос клиента", response_explanation, "Ответьте по существу; затем можно задать встречный вопрос.", ["unanswered_question"], problems)
    if response_status == "partial":
        problems = _problem(text, [re.match(r"[\s\S]+", text)], "Ответ неполный", response_explanation, "Сначала ответьте на вопрос, затем уточните недостающие условия.")
        return _finish(card, "improve", "needs_improvement", "Ответьте на вопрос до встречного уточнения", response_explanation, "Добавьте прямой ответ и коротко объясните его.", ["partial_answer"], problems)

    if len(words) <= 2 and response_status != "answered" and not _QUESTION.search(unquoted):
        problems = _problem(text, [re.match(r"[\s\S]+", text)], "Недостаточно информации", "По такой короткой реплике нельзя понять вашу позицию. Односложный ответ не всегда ошибочен: здесь не видно, что именно вы подтверждаете или отклоняете.", "Добавьте к короткому ответу предмет разговора или одну причину.")
        return _finish(card, "improve", "uncertain", "Короткий ответ требует контекста", "Нельзя надёжно определить, что именно вы имеете в виду.", "Уточните, к какому условию относится ответ и что нужно сделать дальше.", ["insufficient_context"], problems)

    if response_status == "answered" or _QUESTION.search(unquoted) or re.search(r"\b(?:потому что|поскольку|так как|предлагаю|давайте сверим|верно ли я понял)\b", unquoted, re.I):
        return _finish(card, "strong", "correct", "Ответ по существу и в деловом тоне", "Реплика связана с темой и отвечает на вопрос либо помогает уточнить интересы или ограничения. В этом ходе явной ошибки не найдено.", "Сохраните этот подход: подтверждайте условия фактами из разговора и уточняйте следующий шаг.")

    problems = _problem(text, [re.match(r"[\s\S]+", text)], "Неясна позиция", "Тема понятна, но из формулировки не видно конкретной позиции, причины или следующего шага.", "Назовите позицию, коротко объясните причину и уточните, правильно ли стороны поняли друг друга.")
    return _finish(card, "improve", "needs_improvement", "Формулируйте позицию конкретнее", "Собеседнику трудно понять, что вы предлагаете и на каком условии.", "«Я предлагаю …, потому что … . Такой вариант учитывает ваше ограничение?» Заполните пропуски условиями из разговора.", ["low_specificity"], problems)


def build_utterance_review(session):
    """Produce one contextual, verifiable card for each unique user message."""
    transcript = _transcript(session)
    reviews = []
    counts = {"correct": 0, "needs_improvement": 0, "incorrect": 0, "uncertain": 0}
    for position, message in enumerate(session.get("messages", [])):
        if not isinstance(message, dict) or message.get("role") != "user" or not isinstance(message.get("text"), str):
            continue
        message_id = message.get("id")
        if not isinstance(message_id, str) or message_id not in transcript:
            continue
        context = _context(session, position)
        card = _analyze(message, context)
        if "template_choice" not in card["issues"]:
            counts[card["verdict"]] += 1
        reviews.append(card)

    analyzed = sum(counts.values())
    error_titles = []
    for card in reviews:
        for problem in card["problems"]:
            if problem["title"] not in error_titles:
                error_titles.append(problem["title"])
    strengths = [
        f"{sum(card['verdict'] == 'correct' for card in reviews)} ответа по делу: отвечайте так же ясно и проверяйте договорённости."
    ] if counts["correct"] else []
    improvements = error_titles[:4]
    practice = [
        "Сначала ответьте на вопрос собеседника; встречный вопрос задайте после ответа.",
        "Если данных нет, прямо скажите, что нужно проверить. Не придумывайте сумму или срок.",
        "Перед отправкой перечитайте фразу и уберите случайный ввод и грубые слова.",
    ]
    if not analyzed:
        assessment = "В этой попытке нет самостоятельных реплик для оценки. Готовые варианты не считаются вашим ответом."
        next_training = "Повторите ситуацию и ответьте на реплику клиента своими словами."
    else:
        assessment = (
            f"Разобрано ходов: {analyzed}. Корректных ответов: {counts['correct']}; "
            f"нужно доработать: {counts['needs_improvement']}; ошибок: {counts['incorrect']}; "
            f"нужен контекст: {counts['uncertain']}."
        )
        if counts["incorrect"]:
            next_training = "Повторите разговор и сначала исправьте ошибки, отмеченные в красных карточках."
        elif counts["needs_improvement"]:
            next_training = "Повторите тот же сценарий: ответьте на каждый вопрос и назовите конкретный следующий шаг."
        elif counts["uncertain"]:
            next_training = "Повторите сценарий и добавьте недостающий контекст к коротким или сокращённым ответам."
        else:
            next_training = "Повторите сценарий на более сложном уровне и сохраните ясность ответов."
    return {
        "review_method": "rules",
        "review_version": 3,
        "utterance_reviews": reviews,
        "review_summary": {
            "assessment": assessment,
            "strengths": strengths,
            "improvements": improvements,
            "practice": practice,
            "next_training": next_training,
        },
    }
