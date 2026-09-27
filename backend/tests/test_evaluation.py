from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from scripts import evaluate_dialogues as evaluation


def authored_case(**changes):
    case = {
        "id": "direct-interest", "scenario": "scope", "priority": "deadline",
        "difficulty": "hard", "setup": [],
        "text": "Что для вас важнее всего в этом проекте?",
        "expected": {"discloses_interest": True, "allowed_intents": ["ask_interest"],
                     "reply_contains": ["рекламной кампанией"],
                     "reply_excludes": ["Предложение принято"]},
        "rationale": "Прямой вопрос о приоритете клиента раскрывает его ограничение.",
    }
    case.update(changes)
    return case


def dataset(*cases):
    return {"version": 2, "purpose": "Авторские контрольные примеры.",
            "cases": list(cases) if cases else [authored_case()]}


def write_dataset(tmp_path, payload):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def run_payload(payload):
    return evaluation.evaluate_dataset(evaluation.EvaluationDataset.model_validate(payload))


def test_good_case_checks_source_evidence_and_preserves_terms():
    report = run_payload(dataset())
    assert report["mode"] == "demo"
    assert report["dataset_version"] == 2
    assert report["summary"] == {"passed": 1, "failed": 0, "total": 1}
    result = report["cases"][0]
    assert result["analysis"]["source"] == "demo_rules"
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["evidence_is_verbatim"]["actual"] is True
    assert checks["proposal_unchanged"]["expected"] is None
    assert checks["status"]["actual"] == "active"


def test_mismatch_is_honest_and_does_not_stop_next_case():
    bad = authored_case(expected={"discloses_interest": False, "allowed_intents": ["other"],
                                  "reply_contains": ["такой строки нет"],
                                  "reply_excludes": ["РЕКЛАМНОЙ КАМПАНИЕЙ"]})
    report = run_payload(dataset(bad, authored_case(id="next-good")))
    assert report["summary"] == {"passed": 1, "failed": 1, "total": 2}
    checks = {check["name"]: check for check in report["cases"][0]["checks"]}
    assert checks["discloses_interest"] == {
        "name": "discloses_interest", "expected": False, "actual": True, "passed": False,
    }
    assert checks["allowed_intents"]["actual"] == "ask_interest"
    assert checks["allowed_intents"]["passed"] is False
    assert checks["reply_contains:такой строки нет"]["passed"] is False
    assert checks["reply_excludes:РЕКЛАМНОЙ КАМПАНИЕЙ"]["passed"] is False


def test_setup_messages_and_proposal_use_engine_and_sessions_are_independent():
    first = authored_case(
        id="with-setup", priority="full_scope", setup=[
            {"action": "message", "text": "Что для вас важнее всего?"},
            {"action": "proposal", "option_id": "paid_change"},
        ], text="Какой срок у текущего пакета?",
        expected={"discloses_interest": True, "allowed_intents": ["clarify"],
                  "reply_contains": ["240 000", "160", "20"]},
    )
    second = authored_case(id="fresh-session", text="Понятно, спасибо.",
                           expected={"discloses_interest": False})
    report = run_payload(dataset(first, second))
    assert report["summary"]["passed"] == 2, report
    first_checks = {item["name"]: item for item in report["cases"][0]["checks"]}
    assert first_checks["proposal_unchanged"]["actual"]["option_id"] == "paid_change"
    assert first_checks["proposal_unchanged"]["actual"]["client_status"] == "accepted"
    second_checks = {item["name"]: item for item in report["cases"][1]["checks"]}
    assert second_checks["proposal_unchanged"]["actual"] is None
    assert second_checks["one_target_turn"]["actual"] == 1


def test_report_is_deterministic_and_does_not_mutate_dataset():
    parsed = evaluation.EvaluationDataset.model_validate(dataset())
    original = deepcopy(parsed)
    assert evaluation.evaluate_dataset(parsed) == evaluation.evaluate_dataset(parsed)
    assert parsed == original


@pytest.mark.parametrize("mutation", [
    lambda data: data.update(version=1),
    lambda data: data.update(version=True),
    lambda data: data.update(cases=[]),
    lambda data: data["cases"].append(deepcopy(data["cases"][0])),
    lambda data: data["cases"][0].update(scenario="unknown"),
    lambda data: data["cases"][0].update(priority="budget"),
    lambda data: data["cases"][0].update(difficulty="expert"),
    lambda data: data["cases"][0].update(text="  "),
    lambda data: data["cases"][0].update(expected={}),
    lambda data: data["cases"][0].update(expected={"discloses_interest": "false"}),
    lambda data: data["cases"][0]["expected"].update(allowed_intents=[]),
    lambda data: data["cases"][0]["expected"].update(allowed_intents=["invented"]),
    lambda data: data["cases"][0]["expected"].update(reply_contains=[""]),
    lambda data: data["cases"][0]["expected"].update(reply_excludes=[]),
    lambda data: data["cases"][0].update(setup=[{"action": "finish"}]),
    lambda data: data["cases"][0].update(setup=[{"action": "proposal", "option_id": "staged_payment"}]),
    lambda data: data["cases"][0].update(setup=[{"action": "message", "text": " "}]),
    lambda data: data["cases"][0].update(setup=[{"action": "message", "text": "Понятно"}] * 30),
    lambda data: data["cases"][0].update(unknown="typo"),
])
def test_malformed_dataset_is_rejected_before_execution(tmp_path, monkeypatch, mutation):
    payload = dataset()
    mutation(payload)
    path = write_dataset(tmp_path, payload)
    monkeypatch.setattr(evaluation.engine, "new_session", lambda *args: pytest.fail("must validate first"))
    with pytest.raises(evaluation.DatasetError):
        evaluation.load_dataset(path)


@pytest.mark.parametrize("contents", ['{"version":', '{"version":2,"version":2}', '\ud800'])
def test_invalid_json_or_encoding_has_no_cli_traceback(tmp_path, capsys, contents):
    path = tmp_path / "malformed.json"
    path.write_bytes(contents.encode("utf-8", errors="surrogatepass"))
    assert evaluation.main(["--dataset", str(path)]) == 2
    output = capsys.readouterr()
    assert "Ошибка:" in output.err
    assert "Traceback" not in output.err


def test_cli_exit_codes_output_opt_in_and_atomic_json(tmp_path, capsys, monkeypatch):
    source = write_dataset(tmp_path, dataset())
    output = tmp_path / "nested" / "report.json"
    assert evaluation.main(["--dataset", str(source), "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["passed"] == 1
    assert "DEMO: 1/1" in capsys.readouterr().out
    assert list(output.parent.iterdir()) == [output]

    source = write_dataset(tmp_path, dataset(authored_case(expected={"discloses_interest": False})))
    monkeypatch.setattr(evaluation, "write_report", lambda *args: pytest.fail("output not requested"))
    assert evaluation.main(["--dataset", str(source)]) == 1
    assert "FAIL direct-interest" in capsys.readouterr().out
    assert evaluation.main(["--dataset", str(tmp_path / "missing.json")]) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_cli_refuses_to_overwrite_dataset(tmp_path, capsys):
    path = write_dataset(tmp_path, dataset())
    original = path.read_bytes()
    assert evaluation.main(["--dataset", str(path), "--output", str(path)]) == 2
    assert path.read_bytes() == original
    assert "отличаться" in capsys.readouterr().err


def test_atomic_replace_failure_keeps_previous_report_and_removes_temp(tmp_path, monkeypatch):
    report = tmp_path / "report.json"
    report.write_text("previous", encoding="utf-8")

    def fail_replace(*args):
        raise OSError("test: output unavailable")

    monkeypatch.setattr(evaluation.os, "replace", fail_replace)
    with pytest.raises(OSError, match="unavailable"):
        evaluation.write_report(report, {"new": True})
    assert report.read_text() == "previous"
    assert list(tmp_path.iterdir()) == [report]


def test_regressed_engine_is_failed_case_instead_of_cli_traceback(tmp_path, monkeypatch, capsys):
    def broken_engine(*args):
        raise RuntimeError("test regression")

    monkeypatch.setattr(evaluation.engine, "process_message", broken_engine)
    path = write_dataset(tmp_path, dataset())
    output = tmp_path / "report.json"
    assert evaluation.main(["--dataset", str(path), "--output", str(output)]) == 1
    result = json.loads(output.read_text())["cases"][0]
    assert result["checks"][-1]["actual"] == "RuntimeError: test regression"
    assert "Traceback" not in capsys.readouterr().err


def test_proposal_mutation_is_detected(tmp_path, monkeypatch):
    original = evaluation.engine.process_message

    def corrupt(session, *args, **kwargs):
        reply = original(session, *args, **kwargs)
        session["proposal"] = {"unexpected": "text changed deal"}
        return reply

    monkeypatch.setattr(evaluation.engine, "process_message", corrupt)
    result = run_payload(dataset())["cases"][0]
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["proposal_unchanged"]["passed"] is False
    assert result["passed"] is False


def test_runner_never_uses_database_or_provider(tmp_path, monkeypatch):
    import httpx
    from backend import live

    database = tmp_path / "existing.sqlite3"
    database.write_bytes(b"Existing sessions must stay untouched.")
    original = database.read_bytes()
    monkeypatch.setenv("DB_PATH", str(database))

    def forbidden(*args, **kwargs):
        pytest.fail("Evaluation must not use SQLite or a provider")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(live, "analyze", forbidden)
    monkeypatch.setattr(httpx, "post", forbidden)
    assert run_payload(dataset())["summary"]["passed"] == 1
    assert database.read_bytes() == original


def test_script_works_from_another_working_directory_without_default_files(tmp_path):
    source = write_dataset(tmp_path, dataset())
    before = set(tmp_path.iterdir())
    process = subprocess.run(
        [sys.executable, str(evaluation.ROOT / "scripts" / "evaluate_dialogues.py"),
         "--dataset", str(source)], cwd=tmp_path, capture_output=True, text=True,
        timeout=15, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert process.returncode == 0, process.stderr
    assert "DEMO: 1/1" in process.stdout
    assert process.stderr == ""
    assert set(tmp_path.iterdir()) == before
