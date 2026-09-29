"""
tests/backend/test_accounts.py — the 2026-09-28 account changes:

  - deps.get_current_user's database check on every request: a signed-out,
    revoked or idle session stops working at once, and the role comes from
    the database rather than the token
  - one-time links: POST /auth/link-info, /auth/set-password,
    /auth/forgot-password
  - backend.mailer setting its own Date and Message-ID headers

FakeDB keeps users, links and audit entries in memory and answers only the
query shapes those routes issue, like the other backend tests' FakeSessions.
Emails land in the `outbox` fixture (tests/backend/conftest.py).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import auth_utils, deps, mailer
from backend.account_links import LINK_INVALID
from backend.auth_utils import TokenPayload, hash_link_token
from backend.deps import get_db
from backend.login_limiter import MAX_FAILURES_PER_EMAIL
from backend.main import app
from backend.routers import auth as auth_router

# conftest.py swaps mailer.send for the outbox in every test; keep the real one.
REAL_SEND = mailer.send


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


class FakeResult:
    def __init__(self, row=None):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class FakeDB:
    def __init__(self, users):
        self.users = users
        self.tokens: list[dict] = []  # auth_token rows
        self.audit: list[dict] = []
        self.revoked: list[int] = []
        self.idle_closed = False
        self.commits = 0
        self.principal_row = None  # what deps.ACTIVE_PRINCIPAL_SQL returns

    def user(self, **match):
        return next((u for u in self.users if all(u[k] == v for k, v in match.items())), None)

    def _open_token(self, token_hash, now):
        return next(
            (t for t in self.tokens
             if t["token_hash"] == token_hash and t["used_at"] is None and t["expires_at"] > now),
            None,
        )

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = params or {}
        now = datetime.now(timezone.utc)
        if "FROM users u LEFT JOIN user_session s" in sql:
            return FakeResult(self.principal_row)
        if sql.startswith("SELECT 1 FROM users WHERE email = :email"):
            return FakeResult(True if self.user(email=p["email"]) else None)
        if sql.startswith("SELECT user_id, password_hash, role, full_name FROM users"):
            return FakeResult(self.user(email=p["email"]))
        if sql.startswith("SELECT user_id, email, full_name, role FROM users WHERE email"):
            u = self.user(email=p["email"])
            return FakeResult({k: u[k] for k in ("user_id", "email", "full_name", "role")} if u else None)
        if sql.startswith("INSERT INTO users"):
            u = {"user_id": max(x["user_id"] for x in self.users) + 1, "email": p["email"],
                 "password_hash": None, "full_name": p["full_name"], "role": p["role"], "created_at": now}
            self.users.append(u)
            return FakeResult({k: u[k] for k in ("user_id", "email", "full_name", "role", "created_at")})
        if sql.startswith("UPDATE auth_token SET used_at = now() WHERE user_id"):
            for t in self.tokens:
                if t["user_id"] == p["user_id"] and t["used_at"] is None:
                    t["used_at"] = now
            return FakeResult()
        if sql.startswith("INSERT INTO auth_token"):
            t = {"token_hash": p["token_hash"], "user_id": p["user_id"], "purpose": p["purpose"],
                 "expires_at": now + timedelta(minutes=p["minutes"]), "used_at": None}
            self.tokens.append(t)
            return FakeResult({"expires_at": t["expires_at"]})
        if sql.startswith("SELECT t.purpose, t.expires_at, u.email, u.full_name FROM auth_token"):
            t = self._open_token(p["token_hash"], now)
            if t is None:
                return FakeResult(None)
            u = self.user(user_id=t["user_id"])
            return FakeResult({"purpose": t["purpose"], "expires_at": t["expires_at"],
                               "email": u["email"], "full_name": u["full_name"]})
        if sql.startswith("UPDATE auth_token SET used_at = now() WHERE token_hash"):
            t = self._open_token(p["token_hash"], now)
            if t is None:
                return FakeResult(None)
            t["used_at"] = now
            return FakeResult({"user_id": t["user_id"], "purpose": t["purpose"]})
        if sql.startswith("UPDATE users SET password_hash"):
            u = self.user(user_id=p["user_id"])
            u["password_hash"] = p["password_hash"]
            return FakeResult({k: u[k] for k in ("email", "full_name", "role")})
        if "end_reason = 'revoked'" in sql:
            self.revoked.append(p["user_id"])
            return FakeResult()
        if "end_reason = 'idle'" in sql:
            self.idle_closed = True
            return FakeResult()
        if sql.startswith("INSERT INTO audit_log"):
            self.audit.append(dict(p))
            return FakeResult()
        raise AssertionError(f"Unexpected query in FakeDB: {sql}")

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def db():
    return FakeDB([
        {"user_id": 1, "email": "admin@ssmcapstone.com", "full_name": "Admin User", "role": "admin",
         "password_hash": auth_utils.hash_password("admin-password-1")},
        {"user_id": 2, "email": "staff@ssmcapstone.com", "full_name": "Staff User", "role": "staff",
         "password_hash": auth_utils.hash_password("staff-password-1")},
    ])


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(auth_router, "FORGOT_PASSWORD_MIN_SECONDS", 0)


def admin_headers(session_id="sid-1"):
    token = auth_utils.create_access_token(
        user_id=1, email="admin@ssmcapstone.com", role="admin", full_name="Admin User",
        session_id=session_id,
    )
    return {"Authorization": f"Bearer {token}"}


def link_token(email):
    return re.search(r"/set-password#token=([\w-]+)", email["body"]).group(1)


def invite(client, outbox, email="new@ssmcapstone.com"):
    resp = client.post(
        "/auth/register", json={"email": email, "full_name": "New User", "role": "staff"},
        headers=admin_headers(),
    )
    assert resp.status_code == 201
    return link_token(outbox[-1])


# --- the check every request passes (deps.get_current_user) ----------------

LIVE = {"email": "admin@ssmcapstone.com", "full_name": "Admin User", "role": "admin",
        "session_id": "sid-1", "ended_at": None, "idle": False}


def signed(session_id="sid-1", role="admin"):
    return TokenPayload(user_id=1, email="admin@ssmcapstone.com", role=role,
                        full_name="Admin User", session_id=session_id)


@pytest.mark.real_session_check
def test_a_live_session_passes_with_the_role_the_database_has_now(db):
    db.principal_row = {**LIVE, "role": "staff"}
    user = deps.get_current_user(payload=signed(role="admin"), db=db)
    assert user.role == "staff"  # a demotion applies before the token expires


@pytest.mark.real_session_check
@pytest.mark.parametrize("row", [
    None,                                           # account deleted
    {**LIVE, "session_id": None},                   # no such session for this account
    {**LIVE, "ended_at": datetime(2026, 9, 28, tzinfo=timezone.utc)},  # signed out / revoked
], ids=["deleted", "unknown-session", "ended"])
def test_a_deleted_account_or_ended_session_is_refused(db, row):
    db.principal_row = row
    with pytest.raises(HTTPException) as exc:
        deps.get_current_user(payload=signed(), db=db)
    assert exc.value.status_code == 401


@pytest.mark.real_session_check
def test_a_token_without_a_session_is_refused(db):
    with pytest.raises(HTTPException) as exc:
        deps.get_current_user(payload=signed(session_id=None), db=db)
    assert exc.value.status_code == 401


@pytest.mark.real_session_check
def test_an_idle_session_is_closed_and_refused(db):
    db.principal_row = {**LIVE, "idle": True}
    with pytest.raises(HTTPException) as exc:
        deps.get_current_user(payload=signed(), db=db)
    assert exc.value.status_code == 401
    assert db.idle_closed and db.commits == 1


@pytest.mark.real_session_check
def test_a_demoted_admin_is_refused_admin_pages_straight_away(client, db):
    db.principal_row = {**LIVE, "role": "staff"}
    assert client.get("/users", headers=admin_headers()).status_code == 403


@pytest.mark.real_session_check
def test_a_signed_out_token_is_refused(client, db):
    db.principal_row = {**LIVE, "ended_at": datetime(2026, 9, 28, tzinfo=timezone.utc)}
    assert client.get("/users", headers=admin_headers()).status_code == 401


# --- invites and one-time links ---------------------------------------------


def test_an_invite_link_lets_the_new_user_set_their_own_password(client, db, outbox):
    token = invite(client, outbox)
    info = client.post("/auth/link-info", json={"token": token}).json()
    assert info["purpose"] == "invite" and info["email"] == "new@ssmcapstone.com"

    assert client.post("/auth/set-password", json={"token": token, "password": "a-new-password"}).status_code == 204
    new = db.user(email="new@ssmcapstone.com")
    assert auth_utils.verify_password("a-new-password", new["password_hash"])
    assert new["user_id"] in db.revoked
    assert (db.audit[-1]["action"], db.audit[-1]["user_email"]) == ("Password Set", "new@ssmcapstone.com")
    # Only the hash was stored: the database can't be read for a usable link.
    assert [t["token_hash"] for t in db.tokens] == [hash_link_token(token)]
    assert token not in repr(db.tokens)


def test_a_link_works_only_once(client, outbox):
    token = invite(client, outbox)
    assert client.post("/auth/set-password", json={"token": token, "password": "a-new-password"}).status_code == 204
    again = client.post("/auth/set-password", json={"token": token, "password": "another-password"})
    assert again.status_code == 400 and again.json()["detail"] == LINK_INVALID
    assert client.post("/auth/link-info", json={"token": token}).status_code == 400


def test_an_expired_link_is_refused(client, db, outbox):
    token = invite(client, outbox)
    db.tokens[-1]["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert client.post("/auth/set-password", json={"token": token, "password": "a-new-password"}).status_code == 400


def test_a_newer_link_retires_the_older_one(client, outbox, no_wait):
    first = invite(client, outbox)
    client.post("/auth/forgot-password", json={"email": "new@ssmcapstone.com"})
    second = link_token(outbox[-1])
    assert client.post("/auth/link-info", json={"token": first}).status_code == 400
    assert client.post("/auth/link-info", json={"token": second}).json()["purpose"] == "reset"


@pytest.mark.parametrize("password", ["short", "x" * 73, "é" * 37], ids=["too-short", "73-bytes", "74-bytes-utf8"])
def test_passwords_must_be_8_characters_to_72_bytes(client, outbox, password):
    """bcrypt reads only the first 72 bytes, so longer passwords are refused
    rather than silently cut."""
    token = invite(client, outbox)
    assert client.post("/auth/set-password", json={"token": token, "password": password}).status_code == 422
    # A refused password doesn't use the link up.
    assert client.post("/auth/set-password", json={"token": token, "password": "x" * 72}).status_code == 204


# --- forgot password ---------------------------------------------------------


def test_forgot_password_answers_the_same_for_unknown_emails(client, outbox, no_wait):
    known = client.post("/auth/forgot-password", json={"email": "staff@ssmcapstone.com"})
    unknown = client.post("/auth/forgot-password", json={"email": "nobody@ssmcapstone.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [m["to"] for m in outbox] == ["staff@ssmcapstone.com"]
    assert "30 minutes" in outbox[0]["body"]


def test_a_reset_link_replaces_the_old_password(client, db, outbox, no_wait):
    client.post("/auth/forgot-password", json={"email": "staff@ssmcapstone.com"})
    token = link_token(outbox[-1])
    assert client.post("/auth/set-password", json={"token": token, "password": "brand-new-pass"}).status_code == 204
    staff = db.user(email="staff@ssmcapstone.com")
    assert not auth_utils.verify_password("staff-password-1", staff["password_hash"])
    assert auth_utils.verify_password("brand-new-pass", staff["password_hash"])
    assert [a["action"] for a in db.audit] == ["Password Reset Requested", "Password Reset"]
    assert db.revoked == [2]  # other browsers signed in with the old password are signed out


def test_forgot_password_emails_are_rate_limited(client, outbox, no_wait):
    for _ in range(MAX_FAILURES_PER_EMAIL + 3):
        assert client.post("/auth/forgot-password", json={"email": "staff@ssmcapstone.com"}).status_code == 202
    assert len(outbox) == MAX_FAILURES_PER_EMAIL


def test_forgot_password_takes_a_fixed_minimum_time(client, monkeypatch):
    monkeypatch.setattr(auth_router, "FORGOT_PASSWORD_MIN_SECONDS", 0.3)
    started = time.monotonic()
    client.post("/auth/forgot-password", json={"email": "nobody@ssmcapstone.com"})
    assert time.monotonic() - started >= 0.3


def test_forgot_password_offers_the_email_when_it_is_set_up(client):
    assert client.get("/auth/forgot-password").json() == {"email_enabled": True, "detail": None}


def test_without_email_forgot_password_says_to_ask_an_admin(client, db, outbox, monkeypatch):
    """The live API has no email set up: the page says so up front, and a
    request makes no link, since no one could receive it."""
    monkeypatch.setattr(mailer, "is_configured", lambda: False)
    assert client.get("/auth/forgot-password").json() == {
        "email_enabled": False, "detail": auth_router.FORGOT_PASSWORD_NO_EMAIL_MESSAGE,
    }
    for email in ("staff@ssmcapstone.com", "nobody@ssmcapstone.com"):
        resp = client.post("/auth/forgot-password", json={"email": email})
        assert resp.status_code == 202
        assert resp.json() == {"detail": auth_router.FORGOT_PASSWORD_NO_EMAIL_MESSAGE}
    assert outbox == [] and db.tokens == [] and db.audit == []


# --- backend.mailer ----------------------------------------------------------


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        pass

    def login(self, user, password):
        FakeSMTP.login_args = (user, password)

    def send_message(self, msg, from_addr=None, to_addrs=None):
        FakeSMTP.sent.append((msg, from_addr, to_addrs))


def _smtp_env(monkeypatch, smtp_from):
    settings = {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587", "SMTP_USER": "sender@gmail.com",
                "SMTP_PASSWORD": "abcd efgh ijkl mnop", "SMTP_FROM": smtp_from}
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    FakeSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)


def test_mailer_sets_its_own_date_and_message_id(monkeypatch):
    """Without them Gmail adds both after signing and the email bounces
    (550 5.7.30, DKIM) — what happened to the first test email."""
    _smtp_env(monkeypatch, "SSM Dashboard <sender@gmail.com>")
    REAL_SEND("someone@example.com", "Subject", "Body")

    ((msg, _, _),) = FakeSMTP.sent
    assert msg["Date"]
    assert msg["Message-ID"].endswith("@gmail.com>")
    assert FakeSMTP.login_args == ("sender@gmail.com", "abcdefghijklmnop")


@pytest.mark.parametrize("smtp_from", [
    "SSM Dashboard <sender@gmail.com>",
    "SSM Dashboard sender@gmail.com",  # the brackets left out, as in .env on 2026-09-28
    '"SSM Dashboard" <sender@gmail.com>',
])
def test_mailer_always_sends_as_the_signed_in_account(monkeypatch, smtp_from):
    """SMTP_FROM without <...> once went out verbatim as the envelope sender
    (not an address), and the invite to another Gmail account never arrived."""
    _smtp_env(monkeypatch, smtp_from)
    REAL_SEND("someone@example.com", "Subject", "Body")

    ((msg, from_addr, to_addrs),) = FakeSMTP.sent
    assert msg["From"] == "SSM Dashboard <sender@gmail.com>"
    assert (from_addr, to_addrs) == ("sender@gmail.com", ["someone@example.com"])
