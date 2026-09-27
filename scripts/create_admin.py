"""Create an administrator with a hidden password; no default credentials.

Run from the project root: .venv/bin/python scripts/create_admin.py --username your-login
The optional --password-stdin is intended for a secure pipe, never a CLI argument.
"""

import argparse
import getpass
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from backend.account_store import AccountStore
from backend.storage import StorageError, create_repository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", default="Администратор")
    parser.add_argument("--db-path", help="Явный путь SQLite для локальной базы (игнорирует DATABASE_URL).")
    parser.add_argument("--password-stdin", action="store_true", help="Прочитать пароль из защищённого pipe без вывода.")
    args = parser.parse_args()
    try:
        if args.password_stdin:
            if os.isatty(0):
                parser.exit(1, "Используйте скрытый интерактивный ввод без --password-stdin.\n")
            password = sys.stdin.readline(1024).rstrip("\r\n")
        else:
            if not os.isatty(0):
                parser.exit(1, "Запустите команду в терминале для скрытого ввода пароля.\n")
            password = getpass.getpass("Пароль администратора (10–128 символов): ")
            if password != getpass.getpass("Повторите пароль: "):
                parser.exit(1, "Пароли не совпадают. Аккаунт не создан.\n")
        load_dotenv(ROOT / "backend" / ".env", override=False)
        store = AccountStore(create_repository(args.db_path))
        user = store.create_user(args.username, args.display_name, password, role="admin")
    except (ValueError, StorageError) as error:
        parser.exit(1, str(error) + "\n")
    except (KeyboardInterrupt, EOFError):
        parser.exit(1, "\nСоздание отменено.\n")
    except Exception:
        parser.exit(1, "Не удалось создать аккаунт. Проверьте доступ к базе; пароль не выводится.\n")
    print(f"Администратор {user['username']} создан. Войдите через обычную форму входа.")


if __name__ == "__main__":
    main()
