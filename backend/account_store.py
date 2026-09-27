"""Persistent accounts and opaque login sessions for SQLite and PostgreSQL.

Only password derivations and SHA-256 session-token digests enter the database.
Schema setup is lazy so ordinary guest practice does not depend on accounts.
"""

import base64
from contextlib import contextmanager
import hashlib
import hmac
import re
import secrets
from threading import Lock
import time
import uuid


SESSION_SECONDS = 7 * 24 * 60 * 60
USERNAME_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.@+\-]{2,79}\Z")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
SCRYPT_N, SCRYPT_R, SCRYPT_P = 32768, 8, 3


class DuplicateUsernameError(ValueError):
    pass


def normalize_username(username):
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username.strip()):
        raise ValueError("Логин: от 3 до 80 латинских букв, цифр или символов . _ @ + -.")
    return username.strip().lower()


def validate_password(password):
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise ValueError("Пароль должен содержать от 10 до 128 символов.")


def password_hash(password):
    validate_password(password)
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=128 * 1024 * 1024)
    return "$".join(("scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(derived).decode()))


def verify_password(password, encoded):
    try:
        scheme, n, r, p, salt, expected = encoded.split("$")
        # Bound parameters even if a database record was accidentally corrupted.
        if scheme != "scrypt" or (int(n), int(r), int(p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.urlsafe_b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32, maxmem=128 * 1024 * 1024)
        return hmac.compare_digest(actual, base64.urlsafe_b64decode(expected))
    except (TypeError, ValueError, AttributeError):
        return False


def validate_encoded_password(encoded):
    """Accept only our canonical, bounded scrypt format for server bootstrap."""
    if not isinstance(encoded, str):
        raise ValueError("Некорректная настройка начального администратора.")
    parts = encoded.split("$")
    if len(parts) != 6 or parts[:4] != ["scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P)]:
        raise ValueError("Некорректная настройка начального администратора.")
    for value, length in zip(parts[4:], (16, 32)):
        try:
            decoded = base64.b64decode(value, altchars=b"-_", validate=True)
        except (ValueError, TypeError):
            raise ValueError("Некорректная настройка начального администратора.") from None
        if len(decoded) != length or base64.urlsafe_b64encode(decoded).decode() != value:
            raise ValueError("Некорректная настройка начального администратора.")
    return encoded


def _public(row):
    return {"id": row[0], "username": row[1], "display_name": row[2], "role": row[3]}


class AccountStore:
    def __init__(self, repository, clock=time.time):
        self.repository = repository
        self.sqlite = hasattr(repository, "path")
        self.clock = clock
        self._ready = False
        self._guard = Lock()
        # The unknown-user path performs the same expensive password operation.
        # This is a fixed random-looking salt/digest, not a login credential.
        self._dummy_hash = "scrypt$32768$8$3$bm8tdXNlci1kdW1teS1zYQ==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

    def _sql(self, text):
        return text if self.sqlite else text.replace("?", "%s")

    def _ensure_schema(self):
        if self._ready:
            return
        with self._guard:
            if self._ready:
                return
            with self.repository.connect() as connection:
                if self.sqlite:
                    connection.execute("BEGIN IMMEDIATE")
                else:
                    key = int.from_bytes(hashlib.sha256(b"posle/accounts/schema/v1").digest()[:8], "big", signed=True)
                    connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
                connection.execute("""CREATE TABLE IF NOT EXISTS account_users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'admin')),
                    password_hash TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1))
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS account_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES account_users(id) ON DELETE CASCADE,
                    created_at BIGINT NOT NULL,
                    expires_at BIGINT NOT NULL
                )""")
                connection.execute("CREATE INDEX IF NOT EXISTS account_tokens_user ON account_tokens(user_id)")
                connection.execute("CREATE INDEX IF NOT EXISTS account_tokens_expiry ON account_tokens(expires_at)")
                connection.execute("""CREATE TABLE IF NOT EXISTS account_attempts (
                    bucket TEXT PRIMARY KEY,
                    attempts INTEGER NOT NULL,
                    reset_at BIGINT NOT NULL
                )""")
            self._ready = True

    @contextmanager
    def _connection(self, write=False):
        self._ensure_schema()
        with self.repository.connect() as connection:
            if self.sqlite and write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection

    def create_user(self, username, display_name, password, role="user"):
        username = normalize_username(username)
        display_name = display_name.strip() if isinstance(display_name, str) else ""
        if not 1 <= len(display_name) <= 80:
            raise ValueError("Имя должно содержать от 1 до 80 символов.")
        if role not in ("user", "admin"):
            raise ValueError("Недопустимая роль.")
        encoded = password_hash(password)
        user_id = str(uuid.uuid4())
        with self._connection(write=True) as connection:
            row = connection.execute(self._sql("""INSERT INTO account_users(id, username, display_name, role, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(username) DO NOTHING RETURNING id"""),
                (user_id, username, display_name, role, encoded, int(self.clock())),
            ).fetchone()
        if row is None:
            raise DuplicateUsernameError("Этот логин уже занят. Выберите другой или войдите в аккаунт.")
        return {"id": user_id, "username": username, "display_name": display_name, "role": role}

    def authenticate(self, username, password):
        try:
            username = normalize_username(username)
        except ValueError:
            username = ""
        with self._connection() as connection:
            row = connection.execute(self._sql("SELECT id, username, display_name, role, password_hash, enabled FROM account_users WHERE username = ?"), (username,)).fetchone()
        valid = verify_password(password, row[4] if row else self._dummy_hash)
        return _public(row) if row and row[5] and valid else None

    def provision_initial_admin(self, username, display_name, encoded_hash):
        """Insert an operator-provided admin once; never promote or reset users.

        Return None if a regular/disabled account has reserved this username.
        A valid existing administrator is left unchanged, including its hash.
        """
        username = normalize_username(username)
        display_name = display_name.strip() if isinstance(display_name, str) else ""
        if not 1 <= len(display_name) <= 80:
            raise ValueError("Некорректная настройка начального администратора.")
        encoded_hash = validate_encoded_password(encoded_hash)
        with self._connection(write=True) as connection:
            connection.execute(self._sql("""INSERT INTO account_users(id, username, display_name, role, password_hash, created_at)
                VALUES (?, ?, ?, 'admin', ?, ?) ON CONFLICT(username) DO NOTHING"""),
                (str(uuid.uuid4()), username, display_name, encoded_hash, int(self.clock())),
            )
            row = connection.execute(self._sql("SELECT id, username, display_name, role, enabled FROM account_users WHERE username = ?"), (username,)).fetchone()
        return _public(row) if row and row[3] == "admin" and row[4] == 1 else None

    def issue_token(self, user_id, previous_token=None):
        raw = secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        now = int(self.clock())
        with self._connection(write=True) as connection:
            if previous_token and TOKEN_PATTERN.fullmatch(previous_token):
                connection.execute(self._sql("DELETE FROM account_tokens WHERE token_hash = ?"), (hashlib.sha256(previous_token.encode()).hexdigest(),))
            connection.execute(self._sql("DELETE FROM account_tokens WHERE expires_at <= ?"), (now,))
            connection.execute(self._sql("INSERT INTO account_tokens(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)"), (digest, user_id, now, now + SESSION_SECONDS))
        return raw

    def user_for_token(self, raw_token):
        if not isinstance(raw_token, str) or not TOKEN_PATTERN.fullmatch(raw_token):
            return None
        digest = hashlib.sha256(raw_token.encode()).hexdigest()
        with self._connection() as connection:
            row = connection.execute(self._sql("""SELECT u.id, u.username, u.display_name, u.role
                FROM account_users u JOIN account_tokens t ON t.user_id = u.id
                WHERE t.token_hash = ? AND t.expires_at > ? AND u.enabled = 1"""), (digest, int(self.clock()))).fetchone()
        return _public(row) if row else None

    def revoke_token(self, raw_token):
        if not isinstance(raw_token, str) or not TOKEN_PATTERN.fullmatch(raw_token):
            return
        with self._connection(write=True) as connection:
            connection.execute(self._sql("DELETE FROM account_tokens WHERE token_hash = ?"), (hashlib.sha256(raw_token.encode()).hexdigest(),))

    def revoke_all(self, user_id):
        with self._connection(write=True) as connection:
            connection.execute(self._sql("DELETE FROM account_tokens WHERE user_id = ?"), (user_id,))

    def consume_attempt(self, bucket, limit, window):
        """Reserve a request atomically, including failures, across all workers."""
        key = hashlib.sha256(bucket.encode("utf-8")).hexdigest()
        now = int(self.clock())
        with self._connection(write=True) as connection:
            # ON CONFLICT locks a bucket in PostgreSQL; BEGIN IMMEDIATE does so
            # for SQLite. Concurrent requests cannot all pass the same budget.
            row = connection.execute(self._sql("""INSERT INTO account_attempts(bucket, attempts, reset_at) VALUES (?, 1, ?)
                ON CONFLICT(bucket) DO UPDATE SET
                    attempts = CASE WHEN account_attempts.reset_at <= ? THEN 1 ELSE account_attempts.attempts + 1 END,
                    reset_at = CASE WHEN account_attempts.reset_at <= ? THEN excluded.reset_at ELSE account_attempts.reset_at END
                RETURNING attempts, reset_at"""), (key, now + window, now, now)).fetchone()
            # Retain only active rate-limit windows; no IP addresses are stored.
            connection.execute(self._sql("DELETE FROM account_attempts WHERE reset_at <= ?"), (now,))
        return max(1, row[1] - now) if row[0] > limit else 0

    def clear_attempts(self, bucket):
        key = hashlib.sha256(bucket.encode("utf-8")).hexdigest()
        with self._connection(write=True) as connection:
            connection.execute(self._sql("DELETE FROM account_attempts WHERE bucket = ?"), (key,))
