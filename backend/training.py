"""Authored conversation contexts and explicit legacy financial snapshots."""

import json
from hashlib import sha256
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .scenarios import get_scenario
from .conversation_practice import build_scenario


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    industry: Literal["digital", "it", "consulting"]
    topic: Literal["scope", "discount"]
    difficulty: Literal["standard", "hard"]
    tone: Literal["collaborative", "reserved", "pressing"]
    client_role: Literal["project_lead", "business_owner", "procurement"]
    goal: Literal["deadline", "full_scope", "budget", "cashflow"]
    duration_minutes: Literal[5, 10, 15]
    format: Literal["text", "voice"]
    response_seconds: Literal[0, 45]

    @field_validator("duration_minutes", "response_seconds", mode="before")
    @classmethod
    def integer_options(cls, value):
        if type(value) is not int:
            raise ValueError("Время задаётся целым числом из допустимых вариантов.")
        return value

    @model_validator(mode="after")
    def compatible_goal(self):
        permitted = {"scope": {"deadline", "full_scope"}, "discount": {"budget", "cashflow"}}
        if self.goal not in permitted[self.topic]:
            raise ValueError("Цель должна соответствовать теме переговоров.")
        return self


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration: TrainingConfig


class StartBody(PreviewBody):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: Literal["demo", "live"] = "demo"
    client_action_id: str = Field(min_length=1, max_length=100)
    route_stage: Literal["discover", "explain", "objection", "independent"] | None = None


INDUSTRIES = {
    "digital": {
        "label": "Digital-услуги", "provider": "digital-агентства", "company": "Бюро «Контур»",
        "project": "сайт для запуска нового продукта", "work": "разработку сайта",
        "extra": "новые страницы и материалы для запуска", "milestone": "к старту рекламной кампании",
        "short": "основные страницы для запуска", "scope_title": "Новые страницы к дате запуска",
        "discount_title": "Бюджет на запуск сайта",
    },
    "it": {
        "label": "IT и автоматизация", "provider": "команды внедрения IT-систем", "company": "Компания «Вектор»",
        "project": "внедрение CRM для отдела продаж", "work": "внедрение CRM",
        "extra": "дополнительные отчёты и автоматизации", "milestone": "к переходу отдела продаж в новую CRM",
        "short": "основной процесс продаж в CRM", "scope_title": "Больше автоматизаций к запуску CRM",
        "discount_title": "Бюджет на внедрение CRM",
    },
    "consulting": {
        "label": "Консалтинг", "provider": "консалтинговой команды", "company": "Компания «Опора»",
        "project": "аудит процесса закупок", "work": "аудит и рекомендации",
        "extra": "разбор ещё одного подразделения и дополнительные рекомендации", "milestone": "к заседанию руководства по закупкам",
        "short": "аудит основного процесса закупок", "scope_title": "Расширить аудит до заседания",
        "discount_title": "Цена консалтингового проекта",
    },
}

ROLES = {
    "project_lead": {
        "label": "Руководитель проекта",
        "frame": "Я отвечаю за результат проекта перед командой.",
        "brief": "Собеседник координирует проект и защищает согласованный результат перед своей командой.",
    },
    "business_owner": {
        "label": "Владелец бизнеса",
        "frame": "Для меня это решение о расходах и результате для бизнеса.",
        "brief": "Собеседник лично принимает решение о расходах и ожидает понятного результата для бизнеса.",
    },
    "procurement": {
        "label": "Менеджер по закупкам",
        "frame": "Мне нужно согласовать этот пакет с внутренним заказчиком.",
        "brief": "Собеседник согласует пакет с внутренним заказчиком и проверяет формулировки объёма, цены и оплаты.",
    },
}


def context_key(configuration):
    canonical = json.dumps(configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "training-v1-" + sha256(canonical.encode()).hexdigest()


def start_session_id(owner, action_id):
    # Browser ownership is a random secret cookie. Its digest never exposes it.
    # PostgreSQL hold(id) serializes this same ID across all serverless workers.
    return str(uuid5(NAMESPACE_URL, json.dumps(["posle/training/start/v1", owner, action_id])))


def style_reply(configuration, text, turn=0):
    """Add tone without rewriting authoritative terms, status or amounts."""
    if not configuration:
        return text
    variants = {
        "collaborative": ("Давайте найдём подходящее решение. ", "Давайте разберёмся вместе. ", "", "Готовы обсудить. ", ""),
        "reserved": ("Отвечу по существу. ", "По сути вопроса: ", "", "Уточню свою позицию. ", ""),
        "pressing": ("Мне нужен конкретный ответ без затягивания. ", "Перейдём к конкретике. ", "", "Хочу прояснить этот момент. ", ""),
    }
    prefix = variants[configuration["tone"]][turn % 5]
    return prefix + text


def build_financial_preview(configuration: TrainingConfig):
    """Compatibility for an already published, markerless catalogue snapshot."""
    config = configuration.model_dump()
    domain = INDUSTRIES[config["industry"]]
    role = ROLES[config["client_role"]]
    scenario = get_scenario(config["topic"])
    is_scope = config["topic"] == "scope"
    scenario.update({
        "title": domain["scope_title" if is_scope else "discount_title"],
        "eyebrow": domain["label"].upper(),
        "duration": f"Около {config['duration_minutes']} минут",
        "client_role": role["label"], "company": domain["company"],
        "description": (
            f"Клиент расширяет {domain['project']}, сохраняя прежние цену и срок."
            if is_scope else f"Клиент просит снизить цену на {domain['work']}. Выясните ограничение и обсудите встречные условия."
        ),
        "briefing": (
            f"Вы — менеджер {domain['provider']}. Проект — {domain['project']}. "
            + (f"До сдачи 15 рабочих дней, в плане 120 часов при ресурсе 8 часов в день. Клиент просит {domain['extra']} — ещё 40 часов. Исходная цена — 200 000 ₽. "
               if is_scope else "Согласовываете 180 000 ₽ за 120 часов работ, 15 рабочих дней при ресурсе 8 часов в день. Клиент просит 120 000 ₽ за прежний объём. ")
            + role["brief"]
        ),
        "objective": (
            "Выясните ограничение клиента и согласуйте выполнимый объём, срок и цену либо обоснованно завершите разговор без сделки."
            if is_scope else "Выясните причину запроса на скидку и согласуйте пакет, сохраняющий допустимую экономику вашей команды."
        ),
    })
    scenario["constraints"] = [item.replace("Правило студии", "Правило вашей команды") for item in scenario["constraints"]]
    project_title = domain["project"][0].upper() + domain["project"][1:]
    short_title = domain["short"][0].upper() + domain["short"][1:]
    scenario["baseline"]["scope"] = f"{project_title} — исходные работы"
    if is_scope:
        scenario["priorities"][0].update({
            "label": "Дата сдачи",
            "description": "У клиента фиксированная дата сдачи. Выясните, какие задачи для неё важнее.",
        })
    for option in scenario["options"]:
        if option["terms"]["scope"] == "Исходные работы":
            option["terms"]["scope"] = scenario["baseline"]["scope"]
        if option["id"] == "reduce_scope":
            option["terms"]["scope"] = f"{short_title} — самостоятельный пакет на 80 ч; 40 ч исключены без обязательств на следующий этап"
    interest = {
        "deadline": f"Дата привязана {domain['milestone']}. Важны 20 часов новых задач; 20 часов прежних можно убрать. Оставшиеся новые задачи сейчас не обязательны.",
        "full_scope": f"Для проекта «{domain['project']}» нужны все исходные и новые задачи. Перенос на 5 рабочих дней допустим; бюджет можно увеличить до 240 000 ₽, если полный объём явно зафиксирован.",
        "budget": f"Весь бюджет — максимум 120 000 ₽. Подходит {domain['short']}: самостоятельный пакет на 80 часов. Остальные задачи можно исключить.",
        "cashflow": f"Нужны все 120 часов работ по проекту «{domain['project']}». Общая цена 180 000 ₽ допустима, но при старте можно заплатить не больше 60 000 ₽. Остаток сможем оплатить после сдачи.",
    }[config["goal"]]
    scenario["client_interest"] = role["frame"] + " " + interest
    opening = (
        f"Нужно добавить {domain['extra']} — примерно 40 часов. Хотелось бы сохранить дату и цену проекта. Сможете взять?"
        if is_scope else f"Обсудим {domain['work']}: хотелось бы уложиться в 120 тысяч вместо 180. Можно оставить весь объём и снизить цену?"
    )
    scenario["opening"] = style_reply(config, role["frame"] + " " + opening)
    return {
        "scenario": scenario, "configuration": config, "generation_method": "template",
        "max_turns": {5: 8, 10: 16, 15: 24}[config["duration_minutes"]],
        "context_key": context_key(config),
    }


def build_preview(configuration: TrainingConfig):
    """New practice judges communication rather than a fictional cost model."""
    config = configuration.model_dump()
    scenario = build_scenario(config, INDUSTRIES[config["industry"]], ROLES[config["client_role"]])
    scenario["opening"] = style_reply(config, scenario["opening"])
    return {
        "scenario": scenario, "configuration": config, "generation_method": "template",
        "max_turns": {5: 8, 10: 16, 15: 24}[config["duration_minutes"]],
        "context_key": "conversation-v1-" + context_key(config),
    }
