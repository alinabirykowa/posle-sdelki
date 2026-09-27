"""Exercise a deployed demo with synthetic turns, optionally via Vercel CLI.

Creates two anonymous QA attempts. Use --configured for the B2B constructor;
the default continues checking the legacy API. Cookies stay in a temporary
directory and are never printed. Does not call AI or read local user sessions.
"""

import argparse
import json
import os
import re
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--via-vercel", action="store_true")
    parser.add_argument("--configured", action="store_true", help="Check the configurable B2B constructor instead of legacy session creation")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="posle-smoke-") as temp, httpx.Client(base_url=args.url, timeout=45) as client, httpx.Client(base_url=args.url, timeout=45) as outsider:
        def request(path, body=None, foreign=False, expected=200, raw=False):
            if args.via_vercel:
                cookie = str(Path(temp) / ("foreign-cookie" if foreign else "owner-cookie"))
                command = ["npm", "exec", "--offline", "--cache", "/private/tmp/posle-vercel-npm", "--package=vercel@59.23.2", "--", "vercel", "curl", path, "--deployment", args.url, "--scope", "alinkas-projects-87b7b6a2", "--", "--silent", "--show-error", "--max-time", "45", "--cookie-jar", cookie, "--cookie", cookie, "--write-out", "\n%{http_code}"]
                if body is not None:
                    command += ["--request", "POST", "--header", "Content-Type: application/json", "--data", json.dumps(body, ensure_ascii=False)]
                result = subprocess.run(command, capture_output=True, text=True, timeout=70, env={**os.environ, "VERCEL_TELEMETRY_DISABLED": "1"})
                if result.returncode:
                    raise RuntimeError(f"Request failed: {path} (CLI exit {result.returncode})")
                content, status = result.stdout.rsplit("\n", 1)
                status = int(status.strip())
                data = content if raw else json.loads(content)
            else:
                browser = outsider if foreign else client
                response = browser.post(path, json=body) if body is not None else browser.get(path)
                status = response.status_code
                data = response.text if raw else response.json()
            assert status == expected, f"{path}: HTTP {status}, expected {expected}"
            return data

        page = request("/", raw=True)
        assert '<div id="root"></div>' in page
        asset_paths = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', page)
        assert asset_paths
        for asset_path in asset_paths:
            assert request(asset_path, raw=True).strip()
        assert request("/api/health")["status"] == "ok"
        assert len(request("/api/scenarios")["scenarios"]) == 2
        constructor_checks = []
        if args.configured:
            configuration = {
                "industry": "consulting", "topic": "scope", "difficulty": "hard",
                "tone": "pressing", "client_role": "procurement", "goal": "full_scope",
                "duration_minutes": 10, "format": "voice", "response_seconds": 45,
            }
            preview_body = {"configuration": configuration}
            preview = request("/api/training/preview", preview_body)
            assert request("/api/training/preview", preview_body) == preview
            assert preview["generation_method"] == "template"
            assert preview["scenario"]["practice_model"] == "conversation"
            assert preview["scenario"]["baseline"] is None
            assert all(option.get("terms") is None for option in preview["scenario"]["options"])
            assert preview["configuration"] == configuration
            assert preview["max_turns"] == 16
            assert "аудит" in preview["scenario"]["briefing"].lower()
            assert request("/api/sessions")["sessions"] == []
            impossible = {**configuration, "goal": "budget"}
            request("/api/training/preview", {"configuration": impossible}, expected=422)
            request("/api/training/start", {"configuration": impossible, "client_action_id": str(uuid4())}, expected=422)
            start_body = {**preview_body, "mode": "demo", "client_action_id": str(uuid4())}
            session = request("/api/training/start", start_body)
            assert request("/api/training/start", start_body) == session
            request("/api/training/start", {**start_body, "configuration": {**configuration, "tone": "reserved"}}, expected=409)
            assert session["scenario"] == preview["scenario"]
            assert session["training_config"] == configuration
            assert session["context_key"] == preview["context_key"]
            assert session["max_turns"] == preview["max_turns"]
            assert session["generation_method"] == "template"
            assert session["mode"] == "demo"
            assert len(session["reply_choices"]) == 9
            assert {item["group"] for item in session["reply_choices"]} == {"explore", "respond", "negotiate"}
            assert session["conversation_hint"]
            assert len(request("/api/sessions")["sessions"]) == 1
            constructor_checks = ["deterministic read-only preview", "cross-topic goal validation", "configured start and deduplication", "conflicting start rejected", "preview snapshot matches session"]
        else:
            session = request("/api/sessions", {"scenario_id": "scope", "priority": "full_scope", "difficulty": "hard", "mode": "demo"})
        session_id = session["id"]
        path = f"/api/sessions/{session_id}"
        if args.configured:
            short_reply = request(path + "/messages", {"text": "Про сроки", "client_message_id": str(uuid4())})
            assert short_reply["proposal"] is None
            assert short_reply["discovered_interests"] == []
            assert "дат" in short_reply["messages"][-1]["text"]
            assert "₽" not in short_reply["messages"][-1]["text"]
            assert "Не уверен" not in short_reply["messages"][-1]["text"]
            constructor_checks += ["nine contextual reply choices", "short topical reply keeps negotiation state"]
        option_id = "extend_deadline" if args.configured else "paid_change"
        first = request(path + "/proposal", {"option_id": option_id, "client_action_id": str(uuid4())})
        assert first["proposal"]["client_status"] == "rejected"
        message = {"text": "Что для вас важнее всего в этом проекте?", "client_message_id": str(uuid4())}
        spoken = request(path + "/messages", message)
        assert spoken["discovered_interests"]
        assert request(path + "/messages", message) == spoken
        package = {"option_id": option_id, "client_action_id": str(uuid4())}
        accepted = request(path + "/proposal", package)
        assert accepted["proposal"]["client_status"] == "accepted"
        assert request(path + "/proposal", package) == accepted
        result = request(path + "/finish", {"outcome": "agreement"})
        assert result["status"] == "completed"
        assert result["feedback"]["outcome"] == ("agreement" if args.configured else "feasible")
        if args.configured:
            assert result["feedback"]["metrics"] is None
        assert request(path) == result
        if args.configured:
            assert request("/api/training/start", start_body) == result
        request(path, foreign=True, expected=404)
        retry = {"client_action_id": str(uuid4())}
        child = request(path + "/retry", retry)
        assert child["id"] != session_id and child["retry_of"] == session_id
        assert request(path + "/retry", retry) == child
        if args.configured:
            for field in ("scenario", "training_config", "context_key", "max_turns", "generation_method"):
                assert child[field] == session[field]
            assert child["messages"][1]["text"] == session["messages"][1]["text"]
            assert child["turns"] == 0 and child["discovered_interests"] == []
            constructor_checks += ["start recovers completed state", "retry preserves configuration and scenario snapshot"]
        visible = {item["id"] for item in request("/api/sessions")["sessions"]}
        assert {session_id, child["id"]} <= visible
        assert request("/api/sessions", foreign=True)["sessions"] == []
        print(json.dumps({"status": "passed", "url": args.url, "checks": ["homepage", "frontend assets", "health", "scenarios", *constructor_checks, "hard-mode rejection", "interest discovery", "message deduplication", "proposal acceptance and deduplication", "finish and reload", "owner isolation", "retry deduplication", "history"], "qa_sessions": [session_id, child["id"]], "ai_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
