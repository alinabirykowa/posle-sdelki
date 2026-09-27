"""Save a Groq key locally without echoing it or putting it in shell history.

Run manually in a terminal: .venv/bin/python scripts/setup_groq.py
This script does not call Groq or Vercel, create keys, or change billing.
"""

import argparse
import getpass
import os
from pathlib import Path
import re
import tempfile


ENV_PATH = Path(__file__).resolve().parents[1] / "backend" / ".env"
DEFAULT_MODEL = "qwen/qwen3.8-27b"


def save_configuration(path, key, model):
    if not re.fullmatch(r"gsk_[A-Za-z0-9_-]{16,}", key):
        raise ValueError("Нужен полный ключ Groq, начинающийся с gsk_. Значение не сохранено.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,150}", model):
        raise ValueError("Недопустимый идентификатор модели.")
    if path.is_symlink():
        raise ValueError("Файл настроек не должен быть символической ссылкой.")
    updates = {
        "LLM_PROVIDER": "groq",
        "GROQ_API_KEY": key,
        "LLM_MODEL": model,
        "LLM_REPLY_MODE": "generated",
    }
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = []
    for line in original.splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match is None or match.group(1) not in updates:
            lines.append(line)
    lines.extend(f"{name}={value}" for name, value in updates.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    # The temporary file is private before any key bytes are written. Atomic
    # replacement prevents a partial .env from breaking the existing database.
    fd, temporary = tempfile.mkstemp(prefix=".groq-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Модель из Groq Console, доступная вашему Free-аккаунту")
    args = parser.parse_args()
    print("Настройка локального AI-собеседника. Платные услуги не подключаются.")
    print("Ключ вводится скрыто, сохраняется только в backend/.env и не отправляется в чат.")
    print("Модель:", args.model)
    if not os.isatty(0):
        parser.exit(1, "Запустите команду в обычном терминале, чтобы ключ не отображался при вводе.\n")
    try:
        key = getpass.getpass("Вставьте ключ Groq (ввод не отображается): ").strip()
        save_configuration(ENV_PATH, key, args.model)
    except (KeyboardInterrupt, EOFError):
        parser.exit(1, "\nНастройка отменена.\n")
    except ValueError as error:
        parser.exit(1, str(error) + "\n")
    except OSError:
        parser.exit(1, "Не удалось сохранить настройки. Содержимое ключа не выводится.\n")
    print("Настройки сохранены. Перезапустите npm run dev. Доступ к модели ещё нужно проверить.")
    print("Для публичного сайта эти же четыре переменные добавляются отдельно в настройки Vercel.")


if __name__ == "__main__":
    main()
