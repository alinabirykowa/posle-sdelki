#!/usr/bin/env python3
"""Run authored dialogue regression cases locally, without HTTP or persistence.

Usage: .venv/bin/python scripts/evaluate_dialogues.py --output /tmp/dialogues.json
Exit codes: 0 = every check passed, 1 = regression, 2 = invalid input / I/O error.
This checks the demo rules, not an external model or a person's skill. Reply
substrings are compared with Unicode casefold; evidence is checked verbatim.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import engine  # noqa: E402 — usable when launched outside the repo
from backend.dialogue import Intent  # noqa: E402
from backend.scenarios import get_scenario  # noqa: E402


class DatasetError(ValueError):
    """Actionable dataset errors; the CLI prints them without a traceback."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Text = Annotated[str, Field(min_length=1, max_length=2000)]


class MessageAction(StrictModel):
    action: Literal["message"]
    text: Text


class ProposalAction(StrictModel):
    action: Literal["proposal"]
    option_id: str = Field(min_length=1)


Action = Annotated[MessageAction | ProposalAction, Field(discriminator="action")]


class Expected(StrictModel):
    discloses_interest: bool
    allowed_intents: list[Intent] | None = Field(default=None, min_length=1)
    reply_contains: list[str] | None = Field(default=None, min_length=1)
    reply_excludes: list[str] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def meaningful_fragments(self):
        for field in ("reply_contains", "reply_excludes"):
            values = getattr(self, field)
            if values is not None and any(not value.strip() for value in values):
                raise ValueError(f"{field}: фрагменты ответа должны быть непустыми")
        return self


class EvaluationCase(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    scenario: str
    priority: str
    difficulty: Literal["standard", "hard"]
    setup: list[Action] = Field(max_length=29)
    text: Text
    expected: Expected
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_scenario_and_actions(self):
        scenario = get_scenario(self.scenario)
        if self.priority not in {item["id"] for item in scenario["priorities"]}:
            raise ValueError("Приоритет не подходит сценарию")
        options = {item["id"] for item in scenario["options"]}
        if not self.id.strip() or not self.rationale.strip() or not self.text.strip():
            raise ValueError("id, rationale и text должны быть непустыми")
        for action in self.setup:
            if isinstance(action, ProposalAction) and action.option_id not in options:
                raise ValueError(f"В этом сценарии нет предложения {action.option_id!r}")
            if isinstance(action, MessageAction) and not action.text.strip():
                raise ValueError("Реплика setup не может состоять из пробелов")
        return self


class EvaluationDataset(StrictModel):
    version: int
    purpose: str = Field(min_length=1)
    cases: list[EvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def supported_version_and_unique_ids(self):
        if self.version != 2:
            raise ValueError("Поддерживается только version=2")
        if not self.purpose.strip():
            raise ValueError("purpose должен быть непустым")
        ids = [case.id for case in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("Идентификаторы cases должны быть уникальными")
        return self


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DatasetError(f"Повторяющийся JSON-ключ: {key!r}")
        result[key] = value
    return result


def load_dataset(path: Path | str) -> EvaluationDataset:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        return EvaluationDataset.model_validate(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DatasetError(f"Не удалось прочитать датасет: {error}") from None
    except ValidationError as error:
        first = error.errors(include_url=False, include_input=False)[0]
        location = ".".join(str(part) for part in first["loc"]) or "dataset"
        raise DatasetError(f"Некорректный датасет ({location}): {first['msg']}") from None


def _check(name, expected, actual, passed=None):
    return {"name": name, "expected": expected, "actual": actual,
            "passed": expected == actual if passed is None else passed}


def evaluate_case(case: EvaluationCase) -> dict:
    result = {"id": case.id, "input": case.model_dump(exclude_none=True), "checks": []}
    checks = result["checks"]
    try:
        session = engine.new_session(case.scenario, case.priority, case.difficulty, "demo")
        for index, action in enumerate(case.setup):
            if isinstance(action, MessageAction):
                reply = engine.process_message(session, action.text, f"setup-{index}")
                kind = "message"
            else:
                reply = engine.submit_proposal(session, action.option_id)
                kind = "proposal_reply"
            engine.add_message(session, "assistant", reply, kind)

        proposal_before = deepcopy(session["proposal"])
        proposal_events_before = deepcopy(session["_proposal_events"])
        turns_before = session["turns"]
        reply = engine.process_message(session, case.text, "target")
        user_message = session["messages"][-1]
        event = session["_dialogue_events"][-1]
        engine.add_message(session, "assistant", reply)
        result["reply"] = reply
        result["analysis"] = {
            key: event[key] for key in ("intent", "evidence", "focus", "uncertain", "source")
        }
        checks.append(_check("discloses_interest", case.expected.discloses_interest,
                             bool(session["discovered_interests"])))
        if case.expected.allowed_intents is not None:
            checks.append(_check("allowed_intents", case.expected.allowed_intents, event["intent"],
                                 event["intent"] in case.expected.allowed_intents))
        for field, should_contain in (("reply_contains", True), ("reply_excludes", False)):
            for fragment in getattr(case.expected, field) or []:
                checks.append(_check(f"{field}:{fragment}", should_contain,
                                     fragment.casefold() in reply.casefold()))
        checks.extend([
            _check("proposal_unchanged", proposal_before, session["proposal"]),
            # Event UUIDs are not useful in an otherwise reproducible report.
            _check("proposal_history_unchanged", True,
                   proposal_events_before == session["_proposal_events"]),
            _check("status", "active", session["status"]),
            _check("one_target_turn", turns_before + 1, session["turns"]),
            _check("message_preserved", case.text, user_message["text"]),
            _check("message_role", "user", user_message["role"]),
            _check("analysis_source", "demo_rules", event["source"]),
            _check("analysis_matches_message", True, event["message_id"] == user_message["id"]),
            _check("evidence_is_verbatim", True, event["evidence"] in case.text),
            _check("reply_nonempty", True, isinstance(reply, str) and bool(reply.strip())),
        ])
    except Exception as error:
        # A broken engine is a failed case, so remaining cases still produce evidence.
        checks.append(_check("engine_execution", "completed", f"{type(error).__name__}: {error}"))
    result["passed"] = all(check["passed"] for check in checks)
    return result


def evaluate_dataset(dataset: EvaluationDataset) -> dict:
    results = [evaluate_case(case) for case in dataset.cases]
    passed = sum(result["passed"] for result in results)
    return {
        "report_version": 1, "dataset_version": dataset.version, "mode": "demo",
        "purpose": dataset.purpose,
        "limitation": "Авторские регрессионные примеры для правил деморежима. Не оценка реального AI или переговорного навыка.",
        "summary": {"passed": passed, "failed": len(results) - passed, "total": len(results)},
        "cases": results,
    }


def write_report(path: Path | str, report: dict) -> None:
    """Replace one JSON report atomically; never leave a partially written report."""
    path = Path(path)
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump(report, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "docs" / "ai-evaluation-cases.json")
    parser.add_argument("--output", type=Path, help="Опциональный путь для JSON-отчёта")
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.resolve() == args.dataset.resolve():
            raise DatasetError("Путь отчёта должен отличаться от пути датасета")
        report = evaluate_dataset(load_dataset(args.dataset))
        if args.output:
            write_report(args.output, report)
    except (DatasetError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    summary = report["summary"]
    print(f"DEMO: {summary['passed']}/{summary['total']} примеров прошли; ошибок: {summary['failed']}.")
    for case in report["cases"]:
        if not case["passed"]:
            failures = ", ".join(check["name"] for check in case["checks"] if not check["passed"])
            print(f"  FAIL {case['id']}: {failures}")
    print("Проверка правил деморежима; качество внешнего AI и навыки пользователя не оценивались.")
    if args.output:
        print(f"Отчёт: {args.output}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
