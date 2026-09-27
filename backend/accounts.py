"""First-party account routes; administrative roles cannot be self-assigned."""

import os
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .account_store import AccountStore, DuplicateUsernameError, SESSION_SECONDS, normalize_username
from .storage import StorageError


AUTH_COOKIE = "posle_auth"


class RegisterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        return normalize_username(value)

    @field_validator("display_name")
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Укажите имя.")
        return value


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class LogoutBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def check_same_origin(request):
    """Reject cross-origin browser writes; non-browser tools may omit Origin."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    source = request.headers.get("origin") or request.headers.get("referer")
    if source:
        try:
            expected = urlsplit(str(request.url))
            actual = urlsplit(source)
            same = (actual.scheme.lower(), actual.hostname, actual.port or (443 if actual.scheme == "https" else 80)) == (expected.scheme.lower(), expected.hostname, expected.port or (443 if expected.scheme == "https" else 80))
        except ValueError:
            same = False
        if not same:
            raise HTTPException(403, "Этот запрос должен быть отправлен с сайта «После сделки».")
    elif request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Этот запрос должен быть отправлен с сайта «После сделки».")


def check_auth_write(request):
    check_same_origin(request)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "Ожидается JSON-запрос.")


def require_user(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Войдите в аккаунт, чтобы продолжить.")
    check_same_origin(request)
    return user


def require_admin(request: Request):
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Этот раздел доступен только администратору.")
    return user


class AccountsService:
    def __init__(self, repository):
        self.store = AccountStore(repository)

    def user_for_token(self, raw_token):
        return self.store.user_for_token(raw_token)

    require_user = staticmethod(require_user)
    require_admin = staticmethod(require_admin)

    def request_user(self, request):
        # The app middleware resolves this once, on its DB worker thread.
        if hasattr(request.state, "user"):
            return request.state.user
        return self.user_for_token(request.cookies.get(AUTH_COOKIE))

    def _limit(self, bucket, limit, window):
        retry = self.store.consume_attempt(bucket, limit, window)
        if retry:
            raise HTTPException(429, "Слишком много попыток. Подождите и попробуйте снова.", headers={"Retry-After": str(retry)})

    def throttle(self, request, operation, username):
        # Use the server's resolved client, never an untrusted forwarded header.
        address = request.client.host if request.client else "unknown"
        self._limit(f"{operation}/ip/{address}", 10 if operation == "register" else 40, 3600 if operation == "register" else 900)
        bucket = f"{operation}/name/{username.strip().lower()}"
        self._limit(bucket, 10, 900)
        return bucket

    def set_login(self, response, user, previous_token):
        token = self.store.issue_token(user["id"], previous_token)
        response.set_cookie(AUTH_COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=os.environ.get("COOKIE_SECURE") == "1" or os.environ.get("VERCEL") == "1", samesite="lax", path="/")
        response.headers["Cache-Control"] = "no-store"

    def provision_initial_admin(self, username):
        """Operator-only bootstrap from a password hash, never a public role."""
        names = ("INITIAL_ADMIN_USERNAME", "INITIAL_ADMIN_DISPLAY_NAME", "INITIAL_ADMIN_PASSWORD_HASH")
        values = tuple(os.environ.get(name, "") for name in names)
        if not any(values):
            return
        if not all(values):
            raise StorageError("Начальная учётная запись администратора настроена не полностью.")
        try:
            initial_username = normalize_username(values[0])
            # Other usernames do not trigger writes or process the admin hash.
            if username.strip().lower() != initial_username:
                return
            user = self.store.provision_initial_admin(initial_username, values[1], values[2])
        except ValueError:
            raise StorageError("Некорректная настройка начального администратора.") from None
        if user is None:
            # Do not disclose whether the name already belongs to an account.
            raise HTTPException(401, "Неверный логин или пароль.")


def install_accounts(app, repo):
    service = AccountsService(repo)

    @app.get("/api/auth/me")
    def me(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return {"user": service.request_user(request)}

    @app.post("/api/auth/register", status_code=201)
    def register(body: RegisterBody, request: Request, response: Response):
        check_auth_write(request)
        bucket = service.throttle(request, "register", body.username)
        try:
            user = service.store.create_user(body.username, body.display_name, body.password, role="user")
        except DuplicateUsernameError as error:
            raise HTTPException(409, str(error)) from None
        service.set_login(response, user, request.cookies.get(AUTH_COOKIE))
        service.store.clear_attempts(bucket)
        return {"user": user}

    @app.post("/api/auth/login")
    def login(body: LoginBody, request: Request, response: Response):
        check_auth_write(request)
        bucket = service.throttle(request, "login", body.username)
        service.provision_initial_admin(body.username)
        user = service.store.authenticate(body.username, body.password)
        if not user:
            raise HTTPException(401, "Неверный логин или пароль.")
        service.set_login(response, user, request.cookies.get(AUTH_COOKIE))
        service.store.clear_attempts(bucket)
        return {"user": user}

    @app.post("/api/auth/logout")
    def logout(body: LogoutBody, request: Request, response: Response):
        check_auth_write(request)
        service.store.revoke_token(request.cookies.get(AUTH_COOKIE))
        response.delete_cookie(AUTH_COOKIE, path="/", httponly=True, secure=os.environ.get("COOKIE_SECURE") == "1" or os.environ.get("VERCEL") == "1", samesite="lax")
        response.headers["Cache-Control"] = "no-store"
        return {"user": None}

    return service
