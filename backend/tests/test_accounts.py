from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest
from starlette.concurrency import run_in_threadpool

from backend.account_store import AccountStore, DuplicateUsernameError, SESSION_SECONDS, password_hash, validate_encoded_password, verify_password
from backend.accounts import AUTH_COOKIE, install_accounts
from backend.repository import Repository
from backend.tests.test_postgres_integration import postgres_factory


PASSWORD = "A-test-only-password-27"


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    for name in ("INITIAL_ADMIN_USERNAME", "INITIAL_ADMIN_DISPLAY_NAME", "INITIAL_ADMIN_PASSWORD_HASH"):
        monkeypatch.delenv(name, raising=False)
    repository = Repository(tmp_path / "accounts.sqlite3")
    app = FastAPI()
    service = install_accounts(app, repository)

    @app.middleware("http")
    async def resolve_user(request, call_next):
        request.state.user = await run_in_threadpool(service.user_for_token, request.cookies.get(AUTH_COOKIE))
        request.state.owner = "account:" + request.state.user["id"] if request.state.user else "guest"
        return await call_next(request)

    @app.get("/private")
    def private(request: Request):
        user = service.require_user(request)
        return {"user": user, "owner": request.state.owner}

    @app.get("/admin")
    def admin(request: Request):
        return service.require_admin(request)

    return app, service, repository


def signup(client, username="alice", **overrides):
    return client.post("/api/auth/register", json={"username": username, "display_name": "Алиса", "password": PASSWORD, **overrides})


def test_password_is_salted_and_verifies_without_plaintext():
    first, second = password_hash(PASSWORD), password_hash(PASSWORD)
    assert first != second
    assert PASSWORD not in first
    assert verify_password(PASSWORD, first)
    assert not verify_password("incorrect-password", first)
    assert not verify_password(PASSWORD, "corrupt")
    assert not verify_password(PASSWORD, first.replace("32768", "2147483648"))


def test_register_login_me_logout_and_server_side_revocation(accounts):
    app, service, repo = accounts
    with TestClient(app) as browser:
        assert browser.get("/api/auth/me").json() == {"user": None}
        response = signup(browser, "ALICE")
        assert response.status_code == 201
        user = response.json()["user"]
        assert user["username"] == "alice"
        assert user["role"] == "user"
        assert set(user) == {"id", "username", "display_name", "role"}
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
        old_token = browser.cookies.get(AUTH_COOKIE)
        with repo.connect() as conn:
            record = conn.execute("SELECT password_hash FROM account_users").fetchone()[0]
            digest = conn.execute("SELECT token_hash FROM account_tokens").fetchone()[0]
        assert PASSWORD not in record
        assert digest == hashlib.sha256(old_token.encode()).hexdigest()
        assert digest != old_token
        assert browser.get("/api/auth/me").json()["user"] == user
        assert browser.post("/api/auth/logout", json={}).json() == {"user": None}
        assert AUTH_COOKIE not in browser.cookies
        assert service.user_for_token(old_token) is None
        assert browser.post("/api/auth/login", json={"username": "alice", "password": "incorrect-password"}).status_code == 401
        assert browser.post("/api/auth/login", json={"username": "ALICE", "password": PASSWORD}).json()["user"] == user
        new_token = browser.cookies.get(AUTH_COOKIE)
        assert new_token != old_token
        assert browser.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 200
        assert service.user_for_token(new_token) is None


def test_secure_cookie_in_production(accounts, monkeypatch):
    app, _, _ = accounts
    monkeypatch.setenv("VERCEL", "1")
    with TestClient(app, base_url="https://testserver") as browser:
        assert "Secure" in signup(browser).headers["set-cookie"]
        assert browser.get("/api/auth/me").json()["user"]["username"] == "alice"
        assert "Secure" in browser.post("/api/auth/logout", json={}).headers["set-cookie"]


def test_roles_are_server_enforced_and_registration_cannot_promote(accounts):
    app, service, _ = accounts
    admin = service.store.create_user("manager", "Менеджер", PASSWORD, role="admin")
    with TestClient(app) as browser:
        assert browser.get("/admin").status_code == 401
        assert signup(browser, role="admin").status_code == 422
        assert signup(browser).status_code == 201
        assert browser.get("/admin").status_code == 403
        assert browser.post("/api/auth/login", json={"username": "manager", "password": PASSWORD}).status_code == 200
        assert browser.get("/admin").json() == admin


def test_expiry_revocation_and_reloading_store(accounts):
    _, service, repo = accounts
    now = [10000]
    store = AccountStore(repo, clock=lambda: now[0])
    user = store.create_user("alice", "Алиса", PASSWORD)
    token = store.issue_token(user["id"])
    reloaded = AccountStore(Repository(repo.path), clock=lambda: now[0])
    assert reloaded.user_for_token(token) == user
    now[0] += SESSION_SECONDS
    assert reloaded.user_for_token(token) is None
    token = store.issue_token(user["id"])
    store.revoke_all(user["id"])
    assert reloaded.user_for_token(token) is None
    assert service.user_for_token("invalid-token") is None


@pytest.mark.parametrize("header,value", [("Origin", "https://evil.example"), ("Origin", "null"), ("Referer", "https://evil.example/login"), ("Sec-Fetch-Site", "cross-site")])
def test_cross_origin_signup_rejected(accounts, header, value):
    app, _, _ = accounts
    with TestClient(app) as browser:
        response = browser.post("/api/auth/register", json={"username": "alice", "display_name": "Алиса", "password": PASSWORD}, headers={header: value})
        assert response.status_code == 403


def test_same_origin_and_logout_csrf(accounts):
    app, _, _ = accounts
    with TestClient(app) as browser:
        response = browser.post("/api/auth/register", json={"username": "alice", "display_name": "Алиса", "password": PASSWORD}, headers={"Origin": "http://testserver"})
        assert response.status_code == 201
        assert browser.post("/api/auth/logout", json={}, headers={"Origin": "http://evil.example"}).status_code == 403
        assert browser.get("/api/auth/me").json()["user"]["username"] == "alice"
        assert browser.post("/api/auth/logout", content="{}", headers={"Content-Type": "application/problem+json"}).status_code == 415


def test_two_accounts_get_distinct_stable_owners(accounts):
    app, _, _ = accounts
    with TestClient(app) as alice, TestClient(app) as bob:
        alice_user = signup(alice).json()["user"]
        bob_user = signup(bob, "bob").json()["user"]
        assert alice.get("/private").json()["owner"] == "account:" + alice_user["id"]
        assert bob.get("/private").json()["owner"] == "account:" + bob_user["id"]
        assert alice_user["id"] != bob_user["id"]
        alice.post("/api/auth/logout", json={})
        assert alice.get("/private").status_code == 401
        alice.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
        assert alice.get("/private").json()["owner"] == "account:" + alice_user["id"]


def test_concurrent_duplicate_signup_creates_one_user(accounts):
    _, service, repo = accounts

    def create(_):
        try:
            return service.store.create_user("alice", "Алиса", PASSWORD)["id"]
        except DuplicateUsernameError:
            return None

    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(create, range(3)))
    assert sum(value is not None for value in ids) == 1
    with repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM account_users").fetchone()[0] == 1


def test_persistent_rate_limit_is_atomic_and_expires(accounts):
    _, _, repo = accounts
    now = [10000]
    store = AccountStore(repo, clock=lambda: now[0])
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.consume_attempt("login/test", limit=4, window=60), range(12)))
    assert results.count(0) == 4
    restarted = AccountStore(repo, clock=lambda: now[0])
    assert restarted.consume_attempt("login/test", limit=4, window=60) == 60
    now[0] += 60
    assert restarted.consume_attempt("login/test", limit=4, window=60) == 0


def test_failed_logins_are_throttled_across_clients(accounts):
    app, _, _ = accounts
    for _ in range(10):
        with TestClient(app) as browser:
            response = browser.post("/api/auth/login", json={"username": "missing", "password": PASSWORD})
            assert response.status_code == 401
    with TestClient(app) as browser:
        response = browser.post("/api/auth/login", json={"username": "missing", "password": PASSWORD})
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) > 0


@pytest.mark.parametrize("field,value", [("username", "a"), ("username", "Иван"), ("password", "short"), ("password", "x" * 129), ("display_name", "   ")])
def test_invalid_signup(accounts, field, value):
    app, _, _ = accounts
    with TestClient(app) as browser:
        assert signup(browser, **{field: value}).status_code == 422


def test_no_schema_or_connection_for_anonymous_token(tmp_path):
    repo = Repository(tmp_path / "anonymous.sqlite3")
    store = AccountStore(repo)
    assert store.user_for_token(None) is None
    with sqlite3.connect(repo.path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'account_users'").fetchone() is None


def test_real_app_account_sessions_are_private_and_survive_new_browser(tmp_path):
    from backend.app import create_app

    app = create_app(tmp_path / "integrated.sqlite3")
    with TestClient(app) as alice, TestClient(app) as bob:
        assert signup(alice).status_code == 201
        assert signup(bob, "bob").status_code == 201
        response = alice.post("/api/sessions", json={"scenario_id": "scope", "priority": "deadline", "mode": "demo"})
        assert response.status_code == 200
        session_id = response.json()["id"]
        assert bob.get(f"/api/sessions/{session_id}").status_code == 404
        assert bob.get("/api/sessions").json()["sessions"] == []
    with TestClient(create_app(tmp_path / "integrated.sqlite3")) as new_browser:
        assert new_browser.get(f"/api/sessions/{session_id}").status_code == 404
        assert new_browser.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 200
        assert new_browser.get(f"/api/sessions/{session_id}").status_code == 200
        assert new_browser.get("/api/sessions").json()["sessions"][0]["id"] == session_id
        assert new_browser.post("/api/auth/logout", json={}).status_code == 200
        assert new_browser.get(f"/api/sessions/{session_id}").status_code == 404


def test_role_change_and_disabled_account_take_effect_on_existing_token(accounts):
    _, service, repo = accounts
    user = service.store.create_user("manager", "Менеджер", PASSWORD, role="admin")
    token = service.store.issue_token(user["id"])
    with repo.connect() as connection:
        connection.execute("UPDATE account_users SET role = 'user' WHERE id = ?", (user["id"],))
    assert service.user_for_token(token)["role"] == "user"
    with repo.connect() as connection:
        connection.execute("UPDATE account_users SET enabled = 0 WHERE id = ?", (user["id"],))
    assert service.user_for_token(token) is None


def test_admin_cli_reads_pipe_without_echoing_password(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "create_admin.py"
    path = tmp_path / "admin.sqlite3"
    result = subprocess.run([sys.executable, str(script), "--username", "operator", "--db-path", str(path), "--password-stdin"], input=PASSWORD + "\n", text=True, capture_output=True, timeout=20)
    assert result.returncode == 0
    assert PASSWORD not in result.stdout + result.stderr
    user = AccountStore(Repository(path)).authenticate("operator", PASSWORD)
    assert user["role"] == "admin"


def test_account_postgres_durability_and_limits(postgres_factory):
    first = AccountStore(postgres_factory())
    user = first.create_user("alice", "Алиса", PASSWORD)
    token = first.issue_token(user["id"])
    second = AccountStore(postgres_factory())
    assert second.user_for_token(token) == user
    assert second.authenticate("ALICE", PASSWORD) == user
    with pytest.raises(DuplicateUsernameError):
        second.create_user("Alice", "Другое имя", PASSWORD)
    assert first.consume_attempt("shared-bucket", 1, 60) == 0
    assert second.consume_attempt("shared-bucket", 1, 60) > 0
    second.revoke_all(user["id"])
    assert first.user_for_token(token) is None


def test_initial_admin_bootstrap_is_atomic_and_does_not_reset_existing_admin(accounts):
    _, service, repo = accounts
    encoded = password_hash(PASSWORD)
    stores = [AccountStore(Repository(repo.path)) for _ in range(3)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        users = list(pool.map(lambda store: store.provision_initial_admin("operator", "Администратор", encoded), stores))
    assert len({user["id"] for user in users}) == 1
    assert users[0]["role"] == "admin"
    replacement = password_hash("Another-test-only-password")
    unchanged = service.store.provision_initial_admin("OPERATOR", "Другое имя", replacement)
    assert unchanged == users[0]
    assert service.store.authenticate("operator", PASSWORD) == users[0]
    assert service.store.authenticate("operator", "Another-test-only-password") is None
    with repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM account_users").fetchone()[0] == 1
        assert connection.execute("SELECT password_hash FROM account_users").fetchone()[0] == encoded


def test_initial_admin_cannot_promote_or_replace_regular_user(accounts):
    _, service, _ = accounts
    user = service.store.create_user("operator", "Пользователь", PASSWORD)
    assert service.store.provision_initial_admin("operator", "Администратор", password_hash("Different-test-password")) is None
    assert service.store.authenticate("operator", PASSWORD) == user
    assert user["role"] == "user"


@pytest.mark.parametrize("encoded", [
    PASSWORD,
    "scrypt$32768$8$3$AA==$AA==",
    "scrypt$65536$8$3$bm8tdXNlci1kdW1teS1zYQ==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "scrypt$32768$8$3$bm8tdXNlci1kdW1teS1zYQ==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA!=",
    "scrypt$32768$8$3$bm8tdXNlci1kdW1teS1zYQ=$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "scrypt$32768$8$3$bm8tdXNlci1kdW1teS1zYQ==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=$extra",
])
def test_bootstrap_rejects_plaintext_or_noncanonical_hashes(accounts, encoded):
    _, service, _ = accounts
    with pytest.raises(ValueError, match="Некорректная"):
        service.store.provision_initial_admin("operator", "Администратор", encoded)


def test_env_bootstrap_runs_only_on_matching_login(accounts, monkeypatch):
    app, service, _ = accounts
    encoded = password_hash(PASSWORD)
    assert validate_encoded_password(encoded) == encoded
    monkeypatch.setenv("INITIAL_ADMIN_USERNAME", "operator")
    monkeypatch.setenv("INITIAL_ADMIN_DISPLAY_NAME", "Администратор")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD_HASH", encoded)
    with TestClient(app) as browser:
        assert browser.get("/api/auth/me").json() == {"user": None}
        assert service.store.authenticate("operator", PASSWORD) is None
        assert browser.post("/api/auth/login", json={"username": "someone", "password": PASSWORD}).status_code == 401
        assert service.store.authenticate("operator", PASSWORD) is None
        response = browser.post("/api/auth/login", json={"username": "operator", "password": PASSWORD})
        assert response.status_code == 200
        assert response.json()["user"]["role"] == "admin"
        assert encoded not in response.text and PASSWORD not in response.text
        assert browser.get("/admin").status_code == 200


def test_bootstrap_username_collision_returns_generic_401(accounts, monkeypatch):
    app, service, _ = accounts
    service.store.create_user("operator", "Пользователь", PASSWORD)
    monkeypatch.setenv("INITIAL_ADMIN_USERNAME", "operator")
    monkeypatch.setenv("INITIAL_ADMIN_DISPLAY_NAME", "Администратор")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD_HASH", password_hash(PASSWORD))
    with TestClient(app) as browser:
        response = browser.post("/api/auth/login", json={"username": "operator", "password": PASSWORD})
        assert response.status_code == 401
        assert response.json() == {"detail": "Неверный логин или пароль."}
        assert service.store.authenticate("operator", PASSWORD)["role"] == "user"


@pytest.mark.parametrize("complete", [False, True])
def test_misconfigured_bootstrap_fails_safely(tmp_path, monkeypatch, complete):
    from backend.app import create_app

    monkeypatch.setenv("INITIAL_ADMIN_USERNAME", "operator")
    monkeypatch.setenv("INITIAL_ADMIN_DISPLAY_NAME", "Администратор")
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD_HASH", raising=False)
    if complete:
        monkeypatch.setenv("INITIAL_ADMIN_PASSWORD_HASH", "invalid-secret-hash-must-not-leak")
    with TestClient(create_app(tmp_path / "invalid-bootstrap.sqlite3")) as browser:
        response = browser.post("/api/auth/login", json={"username": "operator", "password": PASSWORD})
        assert response.status_code == 503
        assert "invalid-secret-hash" not in response.text
        assert PASSWORD not in response.text


@pytest.mark.parametrize("url", ["http://127.0.0.1:5174", "https://posle-sdelki.vercel.app"])
def test_same_origin_uses_actual_host_not_untrusted_forwarded_headers(accounts, url):
    app, _, _ = accounts
    with TestClient(app, base_url=url) as browser:
        response = browser.post("/api/auth/register", json={"username": "alice", "display_name": "Алиса", "password": PASSWORD}, headers={
            "Origin": url, "X-Forwarded-Host": "internal-proxy:8011", "X-Forwarded-Proto": "http",
        })
        assert response.status_code == 201
        assert browser.post("/api/auth/logout", json={}, headers={
            "Origin": "https://evil.example", "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https",
        }).status_code == 403
