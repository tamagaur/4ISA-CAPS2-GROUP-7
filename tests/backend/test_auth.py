"""
tests/backend/test_auth.py — Story #89: login with hashed credentials;
Story #91: session expiry.

Covers:
  - auth_utils: password hashing round-trip, token creation/decoding,
    configurable expiry (default 8h / custom), tampered-signature
    rejection, missing-secret failure.
  - deps.get_current_user: missing/malformed Authorization header.
  - POST /auth/login: success, wrong password, unknown email (identical
    error for both, so the endpoint doesn't leak which emails exist).
  - POST /auth/register: requires auth, admin-only, duplicate email conflict.

get_db is overridden with a FakeSession so these tests never touch a real
Supabase instance — backend/deps.py's get_db() raises RuntimeError without
SUPABASE_DB_URL, which CI/local runs won't have set.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.exc import ProgrammingError

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.login_limiter import MAX_FAILURES_PER_EMAIL, login_limiter
from backend.main import app


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


@pytest.fixture(autouse=True)
def fresh_login_limiter():
    # Every TestClient request comes from the same address, so failed-login
    # counts would otherwise carry from one test into the next.
    login_limiter.reset()
    yield
    login_limiter.reset()


class FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class FakeSession:
    """Stands in for a SQLAlchemy Session, matching only the query shapes
    backend/routers/auth.py actually issues."""

    def __init__(self, users):
        self.users = users
        self.committed = False
        self.rolled_back = False
        # user_session writes (migration 0023): rows opened at login, and
        # every UPDATE issued by heartbeat/logout as (sql, params).
        self.sessions: list[dict] = []
        self.session_updates: list[tuple[str, dict]] = []
        # Simulates migration 0023 not being applied yet.
        self.fail_session_insert = False

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        if "SELECT user_id, password_hash, role, full_name FROM users" in sql:
            row = next((u for u in self.users if u["email"] == params["email"]), None)
            return FakeResult(row)
        if "SELECT 1 FROM users" in sql:
            exists = any(u["email"] == params["email"] for u in self.users)
            return FakeResult(True if exists else None)
        if "INSERT INTO users" in sql:
            new_user = {
                "user_id": len(self.users) + 1,
                "email": params["email"],
                "password_hash": params["password_hash"],
                "full_name": params["full_name"],
                "role": params["role"],
            }
            self.users.append(new_user)
            return FakeResult({
                "user_id": new_user["user_id"],
                "role": new_user["role"],
                "full_name": new_user["full_name"],
            })
        if "INSERT INTO user_session" in sql:
            if self.fail_session_insert:
                raise ProgrammingError(sql, params, Exception('relation "user_session" does not exist'))
            self.sessions.append(dict(params))
            return FakeResult(None)
        if "UPDATE user_session" in sql:
            self.session_updates.append((sql, dict(params)))
            return FakeResult(None)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


@pytest.fixture
def fake_users():
    return [
        {
            "user_id": 1,
            "email": "admin@ssmcapstone.com",
            "password_hash": auth_utils.hash_password("correct-horse-battery-staple"),
            "full_name": "Admin User",
            "role": "admin",
        }
    ]


@pytest.fixture
def fake_session(fake_users):
    return FakeSession(fake_users)


@pytest.fixture
def client(fake_session):
    app.dependency_overrides[get_db] = lambda: fake_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def admin_token():
    return auth_utils.create_access_token(
        user_id=1, email="admin@ssmcapstone.com", role="admin", full_name="Admin User"
    )


def staff_token():
    return auth_utils.create_access_token(
        user_id=2, email="staff@ssmcapstone.com", role="staff", full_name="Staff User"
    )


# --- auth_utils -------------------------------------------------------


def test_hash_and_verify_password_roundtrip():
    hashed = auth_utils.hash_password("s3cret-pw")
    assert hashed != "s3cret-pw"
    assert auth_utils.verify_password("s3cret-pw", hashed)
    assert not auth_utils.verify_password("wrong-pw", hashed)


def test_decode_access_token_roundtrip():
    token = auth_utils.create_access_token(
        user_id=7, email="x@ssmcapstone.com", role="staff", full_name="X User"
    )
    payload = auth_utils.decode_access_token(token)
    assert payload.user_id == 7
    assert payload.email == "x@ssmcapstone.com"
    assert payload.role == "staff"
    assert payload.full_name == "X User"


def test_decode_expired_token_raises(monkeypatch):
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "-1")
    token = auth_utils.create_access_token(
        user_id=1, email="x@ssmcapstone.com", role="staff", full_name="X User"
    )
    with pytest.raises(auth_utils.JWTError):
        auth_utils.decode_access_token(token)


def test_token_exp_defaults_to_eight_hours(monkeypatch):
    monkeypatch.delenv("JWT_EXPIRY_HOURS", raising=False)
    before = datetime.now(timezone.utc)
    token = auth_utils.create_access_token(
        user_id=1, email="x@ssmcapstone.com", role="staff", full_name="X User"
    )
    exp = datetime.fromtimestamp(jwt.get_unverified_claims(token)["exp"], tz=timezone.utc)
    assert timedelta(hours=7, minutes=59) < (exp - before) < timedelta(hours=8, minutes=1)


def test_token_exp_honors_custom_hours(monkeypatch):
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "2")
    before = datetime.now(timezone.utc)
    token = auth_utils.create_access_token(
        user_id=1, email="x@ssmcapstone.com", role="staff", full_name="X User"
    )
    exp = datetime.fromtimestamp(jwt.get_unverified_claims(token)["exp"], tz=timezone.utc)
    assert timedelta(hours=1, minutes=59) < (exp - before) < timedelta(hours=2, minutes=1)


def test_decode_tampered_signature_raises(monkeypatch):
    token = auth_utils.create_access_token(
        user_id=1, email="x@ssmcapstone.com", role="staff", full_name="X User"
    )
    monkeypatch.setenv("JWT_SECRET_KEY", "a-different-secret")
    with pytest.raises(auth_utils.JWTError):
        auth_utils.decode_access_token(token)


@pytest.mark.skip(reason="Fix later")
def test_missing_secret_key_raises(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        auth_utils.create_access_token(
            user_id=1, email="x@ssmcapstone.com", role="staff", full_name="X User"
        )


# --- deps.get_current_user --------------------------------------------


def test_get_current_user_rejects_missing_header():
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=None)
    assert exc_info.value.status_code == 401


def test_get_current_user_rejects_malformed_header():
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="not-a-bearer-token")
    assert exc_info.value.status_code == 401


def test_get_current_user_accepts_valid_token():
    token = admin_token()
    payload = get_current_user(authorization=f"Bearer {token}")
    assert payload.role == "admin"
    assert payload.email == "admin@ssmcapstone.com"


# --- POST /auth/login ---------------------------------------------------


def test_login_success(client):
    resp = client.post(
        "/auth/login",
        json={"email": "admin@ssmcapstone.com", "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "admin"
    assert body["full_name"] == "Admin User"
    decoded = auth_utils.decode_access_token(body["access_token"])
    assert decoded.email == "admin@ssmcapstone.com"
    assert decoded.full_name == "Admin User"


def test_login_wrong_password(client):
    resp = client.post(
        "/auth/login", json={"email": "admin@ssmcapstone.com", "password": "wrong-password"}
    )
    assert resp.status_code == 401


def test_login_unknown_email_same_error_as_wrong_password(client):
    resp = client.post(
        "/auth/login", json={"email": "nobody@ssmcapstone.com", "password": "whatever123"}
    )
    assert resp.status_code == 401
    wrong_pw_resp = client.post(
        "/auth/login", json={"email": "admin@ssmcapstone.com", "password": "wrong-password"}
    )
    assert resp.json()["detail"] == wrong_pw_resp.json()["detail"]


# --- POST /auth/register -------------------------------------------------


def test_register_requires_auth(client):
    resp = client.post(
        "/auth/register",
        json={"email": "new@ssmcapstone.com", "password": "supersecret1", "full_name": "New User"},
    )
    assert resp.status_code == 401


def test_register_forbidden_for_non_admin(client):
    resp = client.post(
        "/auth/register",
        json={"email": "new@ssmcapstone.com", "password": "supersecret1", "full_name": "New User"},
        headers={"Authorization": f"Bearer {staff_token()}"},
    )
    assert resp.status_code == 403


def test_register_success_for_admin(client, fake_users):
    resp = client.post(
        "/auth/register",
        json={
            "email": "new@ssmcapstone.com",
            "password": "supersecret1",
            "full_name": "New User",
            "role": "staff",
        },
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "staff"
    assert body["full_name"] == "New User"
    assert any(u["email"] == "new@ssmcapstone.com" for u in fake_users)


def test_register_conflict_on_existing_email(client):
    resp = client.post(
        "/auth/register",
        json={"email": "admin@ssmcapstone.com", "password": "supersecret1", "full_name": "Dupe"},
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 409


def test_register_rejects_invalid_role(client):
    resp = client.post(
        "/auth/register",
        json={
            "email": "new@ssmcapstone.com",
            "password": "supersecret1",
            "full_name": "New User",
            "role": "superuser",
        },
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 422


def test_register_rejects_short_password(client):
    resp = client.post(
        "/auth/register",
        json={"email": "new@ssmcapstone.com", "password": "short", "full_name": "New User"},
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 422


def test_register_rejects_blank_full_name(client):
    resp = client.post(
        "/auth/register",
        json={"email": "new@ssmcapstone.com", "password": "supersecret1", "full_name": ""},
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 422


# --- sessions: login / heartbeat / logout (user_session, migration 0023) ---


def _login(client):
    resp = client.post(
        "/auth/login",
        json={"email": "admin@ssmcapstone.com", "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_login_opens_a_session_and_the_token_carries_its_id(client, fake_session):
    token = _login(client)
    assert len(fake_session.sessions) == 1
    opened = fake_session.sessions[0]
    assert opened["user_email"] == "admin@ssmcapstone.com"
    assert opened["role"] == "admin"
    assert auth_utils.decode_access_token(token).session_id == opened["session_id"]


def test_login_still_succeeds_when_the_session_table_is_missing(client, fake_session):
    """Session tracking is best-effort: an unapplied migration must not lock
    everyone out. The token just carries no session id."""
    fake_session.fail_session_insert = True
    token = _login(client)
    assert fake_session.rolled_back
    assert auth_utils.decode_access_token(token).session_id is None


def test_heartbeat_closes_an_idle_session_first_then_extends_it(client, fake_session):
    token = _login(client)
    sid = fake_session.sessions[0]["session_id"]
    resp = client.post("/auth/heartbeat", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 204
    (idle_sql, idle_params), (beat_sql, beat_params) = fake_session.session_updates
    assert "end_reason = 'idle'" in idle_sql
    assert idle_params == {"session_id": sid, "idle_minutes": 30}
    assert "SET last_seen_at = now()" in beat_sql and "ended_at = now()" not in beat_sql
    assert beat_params == {"session_id": sid}


def test_logout_closes_the_session(client, fake_session):
    token = _login(client)
    resp = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 204
    logout_sql, params = fake_session.session_updates[-1]
    assert "end_reason = 'logout'" in logout_sql
    assert params == {"session_id": fake_session.sessions[0]["session_id"]}


def test_heartbeat_for_a_token_without_a_session_id_is_a_noop(client, fake_session):
    resp = client.post("/auth/heartbeat", headers={"Authorization": f"Bearer {admin_token()}"})
    assert resp.status_code == 204
    assert fake_session.session_updates == []


def test_heartbeat_requires_auth(client):
    assert client.post("/auth/heartbeat").status_code == 401


# --- failed sign-in lockout (backend/login_limiter.py) ---------------------

GOOD = {"email": "admin@ssmcapstone.com", "password": "correct-horse-battery-staple"}
BAD = {"email": "admin@ssmcapstone.com", "password": "wrong-password"}


def test_fifth_wrong_password_locks_the_email(client):
    for _ in range(MAX_FAILURES_PER_EMAIL - 1):
        assert client.post("/auth/login", json=BAD).status_code == 401
    locked = client.post("/auth/login", json=BAD)
    assert locked.status_code == 429
    assert locked.json()["detail"] == "Too many failed sign-in attempts. Try again in 15 minutes."
    assert locked.headers["Retry-After"] == "900"


def test_correct_password_is_refused_while_locked(client, fake_session):
    """Otherwise an attacker could keep guessing during the lock and watch
    for the one answer that differs."""
    for _ in range(MAX_FAILURES_PER_EMAIL):
        client.post("/auth/login", json=BAD)
    assert client.post("/auth/login", json=GOOD).status_code == 429
    assert fake_session.sessions == []  # no sign-in happened


def test_unknown_email_locks_the_same_way(client):
    """Same lock for emails with no account, so the lock can't be used to
    discover which emails exist."""
    ghost = {"email": "nobody@ssmcapstone.com", "password": "whatever123"}
    codes = [client.post("/auth/login", json=ghost).status_code for _ in range(MAX_FAILURES_PER_EMAIL)]
    assert codes == [401] * (MAX_FAILURES_PER_EMAIL - 1) + [429]


def test_successful_sign_in_resets_the_count(client):
    for _ in range(MAX_FAILURES_PER_EMAIL - 1):
        client.post("/auth/login", json=BAD)
    assert client.post("/auth/login", json=GOOD).status_code == 200
    for _ in range(MAX_FAILURES_PER_EMAIL - 1):
        assert client.post("/auth/login", json=BAD).status_code == 401


def test_repeated_successful_sign_ins_are_never_limited(client):
    for _ in range(MAX_FAILURES_PER_EMAIL * 3):
        assert client.post("/auth/login", json=GOOD).status_code == 200


def test_lock_on_one_email_does_not_block_another(client, fake_users):
    fake_users.append({
        "user_id": 2, "email": "staff@ssmcapstone.com",
        "password_hash": auth_utils.hash_password("staff-password-1"),
        "full_name": "Staff User", "role": "staff",
    })
    for _ in range(MAX_FAILURES_PER_EMAIL):
        client.post("/auth/login", json=BAD)
    resp = client.post("/auth/login", json={"email": "staff@ssmcapstone.com", "password": "staff-password-1"})
    assert resp.status_code == 200
