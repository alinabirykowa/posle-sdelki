#!/usr/bin/env python3
"""Disposable browser QA: save a mutation, then lose its first successful reply.

Run after npm run build: .venv/bin/python scripts/qa_response_loss.py
Visit http://127.0.0.1:8012. The first message, proposal and retry per parent
returns HTTP 503 AFTER saving. Repeating recovers the stored response. This
server uses an isolated temporary database, disables AI and is never deployed.
"""

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Сначала выполните npm run build.")
    import os
    import uvicorn
    from fastapi.responses import JSONResponse

    with tempfile.TemporaryDirectory(prefix="posle-response-loss-") as directory:
        # Set before importing app, which constructs its default repository.
        os.environ["DB_PATH"] = str(Path(directory) / "qa.sqlite3")
        os.environ.pop("LLM_API_KEY", None)
        from backend.app import app

        lost = set()

        @app.middleware("http")
        async def lose_reply(request, call_next):
            response = await call_next(request)
            path = request.url.path
            if (request.method == "POST" and response.status_code == 200
                    and path.startswith("/api/sessions/")
                    and path.rsplit("/", 1)[-1] in {"messages", "proposal", "retry"}
                    and path not in lost):
                lost.add(path)
                return JSONResponse({"detail": "QA: ответ потерян после сохранения. Повторите действие или обновите попытку."}, status_code=503)
            return response

        print("QA: изолированная временная база; первая выдача ответа после записи будет потеряна.")
        uvicorn.run(app, host="127.0.0.1", port=8012)


if __name__ == "__main__":
    main()
