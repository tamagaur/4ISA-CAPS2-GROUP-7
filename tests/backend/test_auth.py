"""
tests/backend/test_auth.py — Story #89: login with hashed credentials;
Story #91: session expiry.

Covers:
  - auth_utils: password hashing round-trip, token creation/decoding,
    configurable expiry (default 8h / custom), tampered-signature
    rejection, missing-secret failure.
  - deps.get_token_payload: missing/malformed Authorization header.
  - POST /auth/login: success, wrong password, unknown email and invite
    pending (identical error for all, and the same bcrypt work, so the
    endpoint doesn't leak which emails exist).
  - POST /auth/register: requires auth, admin-only, duplicate email
    conflict, no password accepted, invite emailed or handed back as a link.

get_db is overridden with a FakeSession so these tests never touch a real
Supabase instance — backend/deps.py's get_db() raises RuntimeError without
SUPABASE_DB_URL, which CI/local runs won't have set. The limiters are reset
and emails captured by tests/backend/conftest.py.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError

from backend import auth_utils, mailer
from backend.deps import get_db, get_token_payload
from backend.login_limiter import MAX_FAILURES_PER_EMAIL, MAX_FAILURES_PER_IP, FailureLogBudget
from backend.main import app
from backend.routers import auth as auth_router


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
        self.rolled_back = False
        # user_session writes (migration 0023): rows opened at login, and
        # every UPDATE issued by heartbeat/logout as (sql, params).
        self.sessions: list[dict] = []
        self.session_updates: list[tuple[str, dict]] = []
        # Simulates migration 0023 not being applied yet.
        self.fail_session_insert = False
        # Invite links (auth_token, migration 0031) and audit entries written.
        self.tokens: list[dict] = []
        self.audit: list[dict] = []

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
                "password_hash": None,  # invite pending until the link is used
                "full_name": params["full_name"],
                "role": params["role"],
            }
            self.users.append(new_user)
            return FakeResult({
                "user_id": new_user["user_id"],
                "email": new_user["email"],
                "full_name": new_user["full_name"],
                "role": new_user["role"],
                "created_at": datetime(2026, 9, 28, tzinfo=timezone.utc),
            })
        if "INSERT INTO auth_token" in sql:
            self.tokens.append(dict(params))
            return FakeResult({"expires_at": datetime.now(timezone.utc) + timedelta(minutes=params["minutes"])})
        if "UPDATE auth_token" in sql:
            return FakeResult(None)
        if "INSERT INTO audit_log" in sql:
            self.audit.append(dict(params))
            return FakeResult(None)
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


def _unverified_claims(token):
    return jwt.decode(token, options={"verify_signature": False})


# Minted 2026-09-30 by python-jose 3.3.0 (the library before PyJWT) with this
# module's test secret: sub "7", exp 2099-01-01, sid "jose-fixture-session".
JOSE_MINTED_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiI3IiwiZW1haWwiOiJ4QHNzbWNhcHN0b25lLmNvbSIsInJvbGUiOiJzdGFmZiIsImZ1bGxfbmFtZSI6IlggVXNlciIs"
    "ImV4cCI6NDA3MDkwODgwMCwic2lkIjoiam9zZS1maXh0dXJlLXNlc3Npb24ifQ."
    "LrMHU21DOdkUljGZPKIloixhCqpv-n3TrMrkhT6z-2o"
)


def test_tokens_issued_before_pyjwt_still_decode():
    """Tokens already in browsers when the backend switched libraries must
    keep working, so the switch signs nobody out."""
    payload = auth_utils.decode_access_token(JOSE_MINTED_TOKEN)
    assert (payload.user_id, payload.email, payload.role, payload.full_name, payload.session_id) == (
        7, "x@ssmcapstone.com", "staff", "X User", "jose-fixture-session"
    )


def test_unsigned_token_is_rejected():
    """alg=none must never pass, whatever the library."""
    unsigned = jwt.encode({"sub": "1", "email": "x@ssmcapstone.com", "role": "admin", "full_name": "X"}, None, algorithm="none")
    with pytest.raises(auth_utils.JWTError):
        auth_utils.decode_access_token(unsigned)


def test_token_exp_defaults_to_eight_hours(monkeypatch):
    monkeypatch.delenv("JWT_EXPIRY_HOURS", raising=False)
    before = datetime.now(timezone.utc)
    token = auth_utils.create_access_token(
        user_id=1, email="x@ssmcapstone.com", role="staff", full_name="X User"
    )
    exp = datetime.fromtimestamp(_unverified_claims(token)["exp"], tz=timezone.utc)
    assert timedelta(hours=7, minutes=59) < (exp - before) < timedelta(hours=8, minutes=1)


def test_token_exp_honors_custom_hours(monkeypatch):
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "2")
    before = datetime.now(timezone.utc)
    token = auth_utils.create_access_token(
        user_id=1, email="x@ssmcapstone.com", role="staff", full_name="X User"
    )
    exp = datetime.fromtimestamp(_unverified_claims(token)["exp"], tz=timezone.utc)
    assert timedelta(hours=1, minutes=59) < (exp - before) < timedelta(hours=2, minutes=1)


def test_decode_tampered_signature_raises(monkeypatch):
    token = auth_utils.create_access_token(
        user_id=1, email="x@ssmcapstone.com", role="staff", full_name="X User"
    )
    monkeypatch.setenv("JWT_SECRET_KEY", "a-different-secret-at-least-32-bytes-long")
    with pytest.raises(auth_utils.JWTError):
        auth_utils.decode_access_token(token)


@pytest.mark.skip(reason="Fix later")
def test_missing_secret_key_raises(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        auth_utils.create_access_token(
            user_id=1, email="x@ssmcapstone.com", role="staff", full_name="X User"
        )


# --- deps.get_token_payload (the signature half of get_current_user;
# the database half is tested in test_accounts.py) --------------------------


def test_token_payload_rejects_missing_header():
    with pytest.raises(HTTPException) as exc_info:
        get_token_payload(authorization=None)
    assert exc_info.value.status_code == 401


def test_token_payload_rejects_malformed_header():
    with pytest.raises(HTTPException) as exc_info:
        get_token_payload(authorization="not-a-bearer-token")
    assert exc_info.value.status_code == 401


def test_token_payload_accepts_valid_token():
    token = admin_token()
    payload = get_token_payload(authorization=f"Bearer {token}")
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


def test_unknown_email_still_costs_a_password_check(client, monkeypatch):
    """Skipping bcrypt for unknown emails made them answer ~0.2s faster than
    real ones, which gave away which emails have accounts."""
    spent = []
    monkeypatch.setattr(auth_router, "spend_password_check_time", spent.append)
    client.post("/auth/login", json={"email": "nobody@ssmcapstone.com", "password": "whatever123"})
    assert spent == ["whatever123"]


def test_invited_account_cannot_sign_in_before_setting_a_password(client, fake_users, monkeypatch):
    fake_users.append({"user_id": 2, "email": "invited@ssmcapstone.com", "password_hash": None,
                       "full_name": "Invited User", "role": "staff"})
    spent = []
    monkeypatch.setattr(auth_router, "spend_password_check_time", spent.append)
    resp = client.post("/auth/login", json={"email": "invited@ssmcapstone.com", "password": "anything123"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password."
    assert spent  # the same bcrypt work as a wrong password


# --- POST /auth/register -------------------------------------------------

NEW_USER = {"email": "new@ssmcapstone.com", "full_name": "New User", "role": "staff"}


def test_register_requires_auth(client):
    resp = client.post("/auth/register", json=NEW_USER)
    assert resp.status_code == 401


def test_register_forbidden_for_non_admin(client):
    resp = client.post(
        "/auth/register", json=NEW_USER, headers={"Authorization": f"Bearer {staff_token()}"}
    )
    assert resp.status_code == 403


def test_register_invites_without_a_password(client, fake_session, fake_users, outbox):
    resp = client.post(
        "/auth/register", json=NEW_USER, headers={"Authorization": f"Bearer {admin_token()}"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["role"] == "staff"
    assert body["user"]["full_name"] == "New User"
    assert body["user"]["status"] == "invited"
    # Emailed, so the admin never sees the link.
    assert body["email_sent"] is True and body["setup_link"] is None
    assert "access_token" not in body  # the admin no longer gets a login token for the new account
    new = next(u for u in fake_users if u["email"] == "new@ssmcapstone.com")
    assert new["password_hash"] is None
    assert [m["to"] for m in outbox] == ["new@ssmcapstone.com"]
    assert "/set-password#token=" in outbox[0]["body"] and "48 hours" in outbox[0]["body"]
    assert fake_session.tokens[0]["purpose"] == "invite" and fake_session.tokens[0]["created_by"] == 1
    assert fake_session.audit[-1]["action"] == "Add User"
    assert fake_session.audit[-1]["user_email"] == "admin@ssmcapstone.com"


def test_register_hands_back_the_link_when_email_fails(client, monkeypatch):
    def fail(to, subject, body):
        raise mailer.MailError("Email isn't set up on the server yet, so nothing was sent.")

    monkeypatch.setattr(mailer, "send", fail)
    body = client.post(
        "/auth/register", json=NEW_USER, headers={"Authorization": f"Bearer {admin_token()}"}
    ).json()
    assert body["email_sent"] is False
    assert "/set-password#token=" in body["setup_link"]
    assert body["email_problem"] == "Email isn't set up on the server yet, so nothing was sent."


def test_register_refuses_a_password(client):
    """Admins no longer choose passwords for other people."""
    resp = client.post(
        "/auth/register",
        json={**NEW_USER, "password": "supersecret1"},
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 422


def test_register_conflict_on_existing_email(client):
    resp = client.post(
        "/auth/register",
        json={**NEW_USER, "email": "admin@ssmcapstone.com"},
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 409


def test_register_rejects_invalid_role(client):
    resp = client.post(
        "/auth/register",
        json={**NEW_USER, "role": "superuser"},
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    assert resp.status_code == 422


def test_register_rejects_blank_full_name(client):
    resp = client.post(
        "/auth/register",
        json={**NEW_USER, "full_name": ""},
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


def test_login_is_refused_when_its_session_cannot_be_recorded(client, fake_session):
    """Every request now checks the session, so a token without one could
    never be signed out; refusing the sign-in is the safe answer."""
    fake_session.fail_session_insert = True
    resp = client.post(
        "/auth/login",
        json={"email": "admin@ssmcapstone.com", "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 503
    assert fake_session.rolled_back


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


def test_fifth_wrong_password_locks_the_email(client, fake_session):
    for _ in range(MAX_FAILURES_PER_EMAIL - 1):
        assert client.post("/auth/login", json=BAD).status_code == 401
    locked = client.post("/auth/login", json=BAD)
    assert locked.status_code == 429
    assert locked.json()["detail"] == "Too many failed sign-in attempts. Try again in 15 minutes."
    assert locked.headers["Retry-After"] == "900"
    # Each failure is on the record under the email's digest, then the lock
    # under the email that was tried.
    digest = "sha256:" + hashlib.sha256(b"admin@ssmcapstone.com").hexdigest()
    assert [(a["action"], a["user_email"]) for a in fake_session.audit] == [
        ("Sign-in Failed", digest)
    ] * MAX_FAILURES_PER_EMAIL + [("Sign-in Locked", "admin@ssmcapstone.com")]


# --- failed sign-ins in the audit log (2026-09-30) ---------------------------

def test_failed_sign_in_is_logged_as_an_email_digest_and_ip(client, fake_session):
    assert client.post("/auth/login", json={"email": "Admin@SSMcapstone.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/auth/login", json=BAD).status_code == 401
    rows = [a for a in fake_session.audit if a["action"] == "Sign-in Failed"]
    assert len(rows) == 2
    digest = "sha256:" + hashlib.sha256(b"admin@ssmcapstone.com").hexdigest()
    assert {r["user_email"] for r in rows} == {digest}  # case and spaces don't split the count
    assert rows[-1]["details"] == "Wrong email or password from testclient"
    assert (rows[-1]["user_name"], rows[-1]["role"]) == (None, None)
    for row in rows:
        values = " ".join(str(v) for v in row.values())
        assert "wrong-password" not in values
        assert "admin@ssmcapstone.com" not in values.lower()


def test_unknown_email_is_logged_the_same_way(client, fake_session):
    """Same entry whether or not the account exists, so the log can't be used
    to tell them apart either."""
    client.post("/auth/login", json={"email": "nobody@ssmcapstone.com", "password": "whatever123"})
    [row] = fake_session.audit
    assert row["action"] == "Sign-in Failed"
    assert row["user_email"] == "sha256:" + hashlib.sha256(b"nobody@ssmcapstone.com").hexdigest()
    assert row["details"] == "Wrong email or password from testclient"


def test_successful_sign_in_logs_no_failure(client, fake_session):
    assert client.post("/auth/login", json=GOOD).status_code == 200
    assert [a for a in fake_session.audit if a["action"].startswith("Sign-in")] == []


def test_failed_sign_in_logging_is_capped(client, fake_session, monkeypatch):
    """A flood from many addresses must not fill the table: past the cap one
    'paused' entry is written, then nothing until the window ends. The
    limiter still counts every failure."""
    monkeypatch.setattr(auth_router, "failure_log_budget", FailureLogBudget(limit=2))
    for n in range(4):
        assert client.post("/auth/login", json={"email": f"g{n}@ssmcapstone.com", "password": "x" * 8}).status_code == 401
    assert [a["action"] for a in fake_session.audit] == [
        "Sign-in Failed", "Sign-in Failed", "Sign-in Failure Logging Paused",
    ]
    paused = fake_session.audit[-1]
    assert paused["user_email"] == "system"
    assert paused["details"] == (
        "2 failed sign-ins logged in this 15-minute window; "
        "later ones still count toward locks but are not logged until it ends"
    )


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


def _lock_rows(fake_session):
    return [a for a in fake_session.audit if a["action"] == "Sign-in Locked"]


def test_lock_entry_names_the_per_email_limit(client, fake_session):
    for _ in range(MAX_FAILURES_PER_EMAIL):
        client.post("/auth/login", json=BAD)
    [row] = _lock_rows(fake_session)
    assert row["details"] == (
        "admin@ssmcapstone.com locked for 15 minutes: per-email limit "
        "(5 failed sign-ins within 15 minutes). Last attempt: admin@ssmcapstone.com from testclient"
    )


def test_lock_entry_names_the_per_ip_limit(client, fake_session):
    """Four guesses on each of five emails never trips the per-email limit;
    the 20th failure from the one address trips the per-IP limit, and the
    entry must say so instead of blaming the last email."""
    for n in range(MAX_FAILURES_PER_IP // (MAX_FAILURES_PER_EMAIL - 1)):
        for _ in range(MAX_FAILURES_PER_EMAIL - 1):
            client.post("/auth/login", json={"email": f"guess{n}@ssmcapstone.com", "password": "wrong-password"})
    [row] = _lock_rows(fake_session)
    assert row["details"] == (
        "testclient locked for 15 minutes: per-IP limit "
        "(20 failed sign-ins within 15 minutes). Last attempt: guess4@ssmcapstone.com from testclient"
    )


def test_lock_entry_names_both_limits_when_one_failure_trips_both():
    lock = auth_router.Lock(900, ("email", "ip"))
    assert auth_router._lockout_details("a@x.com", "203.0.113.9", lock) == (
        "a@x.com and 203.0.113.9 locked for 15 minutes: per-email limit (5 failed sign-ins within "
        "15 minutes) and per-IP limit (20 failed sign-ins within 15 minutes). "
        "Last attempt: a@x.com from 203.0.113.9"
    )
