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

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


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

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        if "SELECT user_id, password_hash, role FROM Users" in sql:
            row = next((u for u in self.users if u["email"] == params["email"]), None)
            return FakeResult(row)
        if "SELECT 1 FROM Users" in sql:
            exists = any(u["email"] == params["email"] for u in self.users)
            return FakeResult(True if exists else None)
        if "INSERT INTO Users" in sql:
            new_user = {
                "user_id": len(self.users) + 1,
                "email": params["email"],
                "password_hash": params["password_hash"],
                "role": params["role"],
            }
            self.users.append(new_user)
            return FakeResult({"user_id": new_user["user_id"], "role": new_user["role"]})
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def commit(self):
        self.committed = True

    def close(self):
        pass


@pytest.fixture
def fake_users():
    return [
        {
            "user_id": 1,
            "email": "admin@ssmcapstone.com",
            "password_hash": auth_utils.hash_password("correct-horse-battery-staple"),
            "role": "admin",
        }
    ]


@pytest.fixture
def client(fake_users):
    session = FakeSession(fake_users)
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def admin_token():
    return auth_utils.create_access_token(user_id=1, email="admin@ssmcapstone.com", role="admin")


def staff_token():
    return auth_utils.create_access_token(user_id=2, email="staff@ssmcapstone.com", role="staff")


# --- auth_utils -------------------------------------------------------


def test_hash_and_verify_password_roundtrip():
    hashed = auth_utils.hash_password("s3cret-pw")
    assert hashed != "s3cret-pw"
    assert auth_utils.verify_password("s3cret-pw", hashed)
    assert not auth_utils.verify_password("wrong-pw", hashed)


def test_decode_access_token_roundtrip():
    token = auth_utils.create_access_token(user_id=7, email="x@ssmcapstone.com", role="staff")
    payload = auth_utils.decode_access_token(token)
    assert payload.user_id == 7
    assert payload.email == "x@ssmcapstone.com"
    assert payload.role == "staff"


def test_decode_expired_token_raises(monkeypatch):
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "-1")
    token = auth_utils.create_access_token(user_id=1, email="x@ssmcapstone.com", role="staff")
    with pytest.raises(auth_utils.JWTError):
        auth_utils.decode_access_token(token)


def test_token_exp_defaults_to_eight_hours(monkeypatch):
    monkeypatch.delenv("JWT_EXPIRY_HOURS", raising=False)
    before = datetime.now(timezone.utc)
    token = auth_utils.create_access_token(user_id=1, email="x@ssmcapstone.com", role="staff")
    exp = datetime.fromtimestamp(jwt.get_unverified_claims(token)["exp"], tz=timezone.utc)
    assert timedelta(hours=7, minutes=59) < (exp - before) < timedelta(hours=8, minutes=1)


def test_token_exp_honors_custom_hours(monkeypatch):
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "2")
    before = datetime.now(timezone.utc)
    token = auth_utils.create_access_token(user_id=1, email="x@ssmcapstone.com", role="staff")
    exp = datetime.fromtimestamp(jwt.get_unverified_claims(token)["exp"], tz=timezone.utc)
    assert timedelta(hours=1, minutes=59) < (exp - before) < timedelta(hours=2, minutes=1)


def test_decode_tampered_signature_raises(monkeypatch):
    token = auth_utils.create_access_token(user_id=1, email="x@ssmcapstone.com", role="staff")
    monkeypatch.setenv("JWT_SECRET_KEY", "a-different-secret")
    with pytest.raises(auth_utils.JWTError):
        auth_utils.decode_access_token(token)


def test_missing_secret_key_raises(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        auth_utils.create_access_token(user_id=1, email="x@ssmcapstone.com", role="staff")


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
    decoded = auth_utils.decode_access_token(body["access_token"])
    assert decoded.email == "admin@ssmcapstone.com"


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
        "/auth/register", json={"email": "new@ssmcapstone.com", "password": "supersecret1"}
    )
    assert resp.status_code == 401


def test_register_forbidden_for_non_admin(client):
    resp = client.post(
        "/auth/register",
        json={"email": "new@ssmcapstone.com", "password": "supersecret1"},
        headers={"Authorization": f"Bearer {staff_token()}"},
    )
    assert resp.status_code == 403


def test_register_success_for_admin(client, fake_users):
    resp = client.post(
        "/auth/register",
        json={"email": "new@ssmcapstone.com", "password": "supersecret1", "role": "staff"},
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "staff"
    assert any(u["email"] == "new@ssmcapstone.com" for u in fake_users)


def test_register_conflict_on_existing_email(client):
    resp = client.post(
        "/auth/register",
        json={"email": "admin@ssmcapstone.com", "password": "supersecret1"},
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 409


def test_register_rejects_invalid_role(client):
    resp = client.post(
        "/auth/register",
        json={"email": "new@ssmcapstone.com", "password": "supersecret1", "role": "superuser"},
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 422


def test_register_rejects_short_password(client):
    resp = client.post(
        "/auth/register",
        json={"email": "new@ssmcapstone.com", "password": "short"},
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 422
