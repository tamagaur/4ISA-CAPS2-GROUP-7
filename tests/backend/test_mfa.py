"""
tests/backend/test_mfa.py — two-step sign-in with an authenticator app
(backend/mfa.py, backend/routers/auth.py's second step,
backend/routers/two_factor.py, POST /users/{id}/mfa/reset).

Covers:
  - the code maths against RFC 6238's own test vectors, clock drift, and
    recovery codes;
  - the 5-minute token between password and code can't be used as a sign-in
    token, nor the other way round;
  - sign-in: no second step without it; code required with it; a code works
    once; wrong codes lock like wrong passwords, and a right password doesn't
    clear the count; a recovery code works once;
  - a required role sets it up at sign-in; without MFA_ENCRYPTION_KEY a
    required role isn't enforced but an account that has it can't skip it;
  - your own: set up, confirm, new recovery codes, turn off (needs a code,
    refused for a required role);
  - the admin reset, and the User Management list's mfa_enabled;
  - before migration 0035 nothing changes.

get_db is a FakeSession holding users, user_mfa rows, sessions and audit
entries, matching only the query shapes these routes issue.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from jose import JWTError, jwt

from backend import auth_utils, mfa
from backend.deps import get_db
from backend.login_limiter import MAX_FAILURES_PER_EMAIL
from backend.main import app

pytestmark = pytest.mark.real_mfa

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def mfa_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    # Empty, not deleted: load_dotenv(override=False) would fill a missing one from .env.
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "")
    monkeypatch.setitem(mfa._ready_cache, "value", True)


# ── The fake database ─────────────────────────────────────────────────────
class FakeResult:
    def __init__(self, row=None, rows=None, scalar=None):
        self._row, self._rows, self._scalar = row, rows or [], scalar

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class FakeSession:
    def __init__(self):
        self.users = {
            1: {"user_id": 1, "email": "admin@ssmcapstone.com", "full_name": "Ana Admin", "role": "admin",
                "password_hash": auth_utils.hash_password(PASSWORD)},
            2: {"user_id": 2, "email": "staff@ssmcapstone.com", "full_name": "Sam Staff", "role": "staff",
                "password_hash": auth_utils.hash_password(PASSWORD)},
        }
        self.mfa: dict[int, dict] = {}
        self.sessions: list[dict] = []
        self.revoked: list[int] = []
        self.audit: list[dict] = []
        self.commits = 0

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = params or {}
        if sql.startswith("SELECT user_id, password_hash, role, full_name FROM users WHERE email"):
            user = next((u for u in self.users.values() if u["email"] == p["email"]), None)
            return FakeResult(user)
        if sql.startswith("SELECT user_id, email, full_name, role FROM users WHERE user_id"):
            user = self.users.get(p["user_id"])
            return FakeResult(None if user is None else {k: user[k] for k in ("user_id", "email", "full_name", "role")})
        if "CASE WHEN password_hash IS NULL" in sql:
            rows = [self._user_out(u) for u in self.users.values()]
            if "WHERE user_id = :user_id" in sql:
                return FakeResult(next((r for r in rows if r["user_id"] == p["user_id"]), None))
            return FakeResult(rows=rows)
        if sql.startswith("SELECT secret_encrypted, enabled_at, last_used_step"):
            row = self.mfa.get(p["user_id"])
            if row is None:
                return FakeResult(None)
            return FakeResult({**row, "recovery_left": len(row["recovery_hashes"])})
        if sql.startswith("SELECT user_id FROM user_mfa WHERE enabled_at IS NOT NULL"):
            return FakeResult(rows=[(uid,) for uid, r in self.mfa.items() if r["enabled_at"] is not None])
        if sql.startswith("INSERT INTO user_mfa"):
            row = self.mfa.get(p["user_id"])
            if row is not None and row["enabled_at"] is not None:
                return FakeResult(None)
            self.mfa[p["user_id"]] = {"secret_encrypted": p["secret_encrypted"], "enabled_at": None,
                                      "last_used_step": None, "recovery_hashes": []}
            return FakeResult((p["user_id"],))
        if sql.startswith("UPDATE user_mfa SET enabled_at = now()"):
            row = self.mfa.get(p["user_id"])
            if row is None or row["enabled_at"] is not None:
                return FakeResult(None)
            row.update(enabled_at=datetime.now(timezone.utc), last_used_step=p["step"],
                       recovery_hashes=list(p["hashes"]))
            return FakeResult((p["user_id"],))
        if sql.startswith("UPDATE user_mfa SET last_used_step"):
            row = self.mfa.get(p["user_id"])
            if row is None or row["enabled_at"] is None:
                return FakeResult(None)
            if row["last_used_step"] is not None and row["last_used_step"] >= p["step"]:
                return FakeResult(None)
            row["last_used_step"] = p["step"]
            return FakeResult((p["user_id"],))
        if sql.startswith("UPDATE user_mfa SET recovery_hashes = array_remove"):
            row = self.mfa.get(p["user_id"])
            if row is None or row["enabled_at"] is None or p["code_hash"] not in row["recovery_hashes"]:
                return FakeResult(None)
            row["recovery_hashes"].remove(p["code_hash"])
            return FakeResult((p["user_id"],))
        if sql.startswith("UPDATE user_mfa SET recovery_hashes = :hashes"):
            row = self.mfa.get(p["user_id"])
            if row is not None and row["enabled_at"] is not None:
                row["recovery_hashes"] = list(p["hashes"])
            return FakeResult(None)
        if sql.startswith("DELETE FROM user_mfa"):
            row = self.mfa.pop(p["user_id"], None)
            return FakeResult(None if row is None else (row["enabled_at"],))
        if sql.startswith("INSERT INTO user_session"):
            self.sessions.append(dict(p))
            return FakeResult(None)
        if "end_reason = 'revoked'" in sql:
            self.revoked.append(p["user_id"])
            return FakeResult(None)
        if sql.startswith("UPDATE user_session"):
            return FakeResult(None)
        if sql.startswith("INSERT INTO audit_log"):
            self.audit.append(dict(p))
            return FakeResult(None)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def _user_out(self, u):
        return {"user_id": u["user_id"], "email": u["email"], "full_name": u["full_name"], "role": u["role"],
                "created_at": datetime(2026, 9, 28, tzinfo=timezone.utc),
                "status": "invited" if u["password_hash"] is None else "active"}

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def db():
    return FakeSession()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def turn_on(db, user_id: int) -> tuple[str, list[str]]:
    """Gives an account two-step sign-in directly: (secret, recovery codes)."""
    secret = mfa.new_secret()
    codes = mfa.new_recovery_codes()
    db.mfa[user_id] = {
        "secret_encrypted": mfa._fernet().encrypt(secret.encode()).decode(),
        "enabled_at": datetime.now(timezone.utc),
        "last_used_step": None,
        "recovery_hashes": [mfa.hash_recovery_code(c) for c in codes],
    }
    return secret, codes


def now_code(secret: str, offset: int = 0) -> str:
    return mfa.code_at(secret, mfa.current_step() + offset)


def password_step(client, email="admin@ssmcapstone.com"):
    return client.post("/auth/login", json={"email": email, "password": PASSWORD})


def bearer(user: dict) -> dict:
    token = auth_utils.create_access_token(user_id=user["user_id"], email=user["email"], role=user["role"],
                                           full_name=user["full_name"], session_id="s-1")
    return {"Authorization": f"Bearer {token}"}


# ── The code maths ─────────────────────────────────────────────────────────
RFC6238_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # ASCII "12345678901234567890"


@pytest.mark.parametrize("unix_time, eight_digits", [
    (59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
    (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130"),
])
def test_codes_match_rfc_6238(unix_time, eight_digits):
    # The RFC lists 8-digit codes; a 6-digit code is the same number mod 10^6.
    assert mfa.code_at(RFC6238_SECRET, unix_time // 30) == eight_digits[-6:]


def test_a_phone_clock_one_step_off_still_works():
    secret, now = mfa.new_secret(), 1_800_000_000.0
    step = mfa.current_step(now)
    for offset in (-1, 0, 1):
        assert mfa.matching_step(secret, mfa.code_at(secret, step + offset), now) == step + offset
    assert mfa.matching_step(secret, mfa.code_at(secret, step + 2), now) is None
    assert mfa.matching_step(secret, mfa.code_at(secret, step - 2), now) is None


def test_spaces_in_a_code_are_ignored_and_junk_is_refused():
    secret, now = mfa.new_secret(), 1_800_000_000.0
    code = mfa.code_at(secret, mfa.current_step(now))
    assert mfa.matching_step(secret, f"{code[:3]} {code[3:]}", now) is not None
    assert mfa.matching_step(secret, "abcdef", now) is None
    assert mfa.matching_step(secret, "12345", now) is None


def test_the_qr_link_names_the_app_and_the_account():
    uri = mfa.provisioning_uri("ABCDEF234567", "ana@ssm.test")
    assert uri.startswith("otpauth://totp/SAN2%20Inventory%20DSS%3Aana%40ssm.test?")
    assert "secret=ABCDEF234567" in uri and "issuer=SAN2%20Inventory%20DSS" in uri
    assert "digits=6" in uri and "period=30" in uri


def test_recovery_codes_are_unique_readable_and_matched_loosely():
    codes = mfa.new_recovery_codes()
    assert len(codes) == mfa.RECOVERY_CODE_COUNT == len(set(codes))
    for code in codes:
        assert len(code) == 11 and code[5] == "-"
        assert not set(code.replace("-", "")) & set("01ilo")
    assert mfa.hash_recovery_code(codes[0]) == mfa.hash_recovery_code(codes[0].upper().replace("-", " "))


# ── The token between password and code ───────────────────────────────────
def test_the_pending_token_is_not_a_sign_in_token_and_vice_versa():
    pending = mfa.issue_pending_token(1, "verify")
    with pytest.raises(JWTError):
        auth_utils.decode_access_token(pending)
    access = auth_utils.create_access_token(user_id=1, email="a@b.c", role="admin", full_name="A", session_id="s")
    assert mfa.read_pending_token(access, "verify") is None
    assert mfa.read_pending_token(pending, "verify") == 1
    assert mfa.read_pending_token(pending, "setup") is None


def test_an_expired_pending_token_is_refused():
    expired = jwt.encode({"sub": "1", "step": "verify", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
                         mfa._pending_key(), algorithm="HS256")
    assert mfa.read_pending_token(expired, "verify") is None


def test_the_pending_token_does_not_open_a_page(client):
    pending = mfa.issue_pending_token(1, "verify")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {pending}"}).status_code == 401


# ── Sign-in ────────────────────────────────────────────────────────────────
def test_without_two_step_sign_in_the_password_is_enough(client, db):
    res = password_step(client)
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"] and "mfa_step" not in body and "mfa_token" not in body
    assert len(db.sessions) == 1


def test_with_it_the_password_alone_opens_no_session(client, db):
    turn_on(db, 1)
    res = password_step(client)
    assert res.status_code == 200
    body = res.json()
    assert body["mfa_step"] == "verify" and body["mfa_token"]
    assert "access_token" not in body
    assert db.sessions == []


def test_the_right_code_signs_in_and_works_only_once(client, db):
    secret, _ = turn_on(db, 1)
    token = password_step(client).json()["mfa_token"]
    code = now_code(secret)
    res = client.post("/auth/login/verify", json={"mfa_token": token, "code": code})
    assert res.status_code == 200
    assert res.json()["role"] == "admin" and res.json()["access_token"]
    assert len(db.sessions) == 1

    again = client.post("/auth/login/verify", json={"mfa_token": token, "code": code})
    assert again.status_code == 401
    assert len(db.sessions) == 1


def test_wrong_codes_lock_like_wrong_passwords(client, db):
    turn_on(db, 1)
    token = password_step(client).json()["mfa_token"]
    for _ in range(MAX_FAILURES_PER_EMAIL - 1):
        res = client.post("/auth/login/verify", json={"mfa_token": token, "code": "000000"})
        assert res.status_code == 401
        assert res.json()["detail"] == "That code didn't work. Check the app and try again."
    locked = client.post("/auth/login/verify", json={"mfa_token": token, "code": "000000"})
    assert locked.status_code == 429 and "Retry-After" in locked.headers
    assert any(a["action"] == "Sign-in Locked" for a in db.audit)
    # The lock covers the password step too.
    assert password_step(client).status_code == 429


def test_a_right_password_does_not_reset_the_wrong_code_count(client, db):
    turn_on(db, 1)
    for _ in range(MAX_FAILURES_PER_EMAIL - 1):
        token = password_step(client).json()["mfa_token"]
        assert client.post("/auth/login/verify", json={"mfa_token": token, "code": "000000"}).status_code == 401
    token = password_step(client).json()["mfa_token"]
    assert client.post("/auth/login/verify", json={"mfa_token": token, "code": "000000"}).status_code == 429


def test_a_recovery_code_signs_in_once(client, db):
    _, codes = turn_on(db, 1)
    token = password_step(client).json()["mfa_token"]
    res = client.post("/auth/login/verify", json={"mfa_token": token, "code": codes[0].upper()})
    assert res.status_code == 200
    assert len(db.mfa[1]["recovery_hashes"]) == mfa.RECOVERY_CODE_COUNT - 1
    used = [a for a in db.audit if a["action"] == "Recovery Code Used"]
    assert used and used[0]["details"] == "9 recovery codes left"

    token = password_step(client).json()["mfa_token"]
    assert client.post("/auth/login/verify", json={"mfa_token": token, "code": codes[0]}).status_code == 401


def test_a_bad_or_wrong_step_token_goes_back_to_the_password(client, db):
    secret, _ = turn_on(db, 1)
    for token in ("x" * 40, mfa.issue_pending_token(1, "setup")):
        res = client.post("/auth/login/verify", json={"mfa_token": token, "code": now_code(secret)})
        assert res.status_code == 401
        assert res.json()["code"] == "mfa_expired"


def test_an_account_with_it_cannot_sign_in_without_the_key(client, db, monkeypatch):
    turn_on(db, 1)
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", "")
    res = password_step(client)
    assert res.status_code == 503
    assert db.sessions == []


# ── A role that must use it ────────────────────────────────────────────────
def test_a_required_role_sets_it_up_at_sign_in(client, db, monkeypatch):
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "admin")
    body = password_step(client).json()
    assert body["mfa_step"] == "setup" and "access_token" not in body

    setup = client.post("/auth/login/setup", json={"mfa_token": body["mfa_token"]})
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")
    assert db.mfa[1]["enabled_at"] is None
    assert db.sessions == []

    wrong = client.post("/auth/login/setup/confirm", json={"mfa_token": body["mfa_token"], "code": "000000"})
    assert wrong.status_code == 401
    done = client.post("/auth/login/setup/confirm", json={"mfa_token": body["mfa_token"], "code": now_code(secret)})
    assert done.status_code == 200
    assert len(done.json()["recovery_codes"]) == mfa.RECOVERY_CODE_COUNT
    assert done.json()["access_token"]
    assert db.mfa[1]["enabled_at"] is not None and len(db.sessions) == 1
    assert any(a["action"] == "Two-Step Sign-In On" for a in db.audit)

    # Next time: the code, not setup.
    assert password_step(client).json()["mfa_step"] == "verify"


def test_other_roles_are_not_asked(client, db, monkeypatch):
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "admin")
    assert password_step(client, "staff@ssmcapstone.com").json()["access_token"]


def test_a_required_role_is_not_enforced_without_the_key(client, db, monkeypatch):
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "admin")
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", "")
    assert password_step(client).json()["access_token"]


# ── Your own ───────────────────────────────────────────────────────────────
def test_status_setup_and_confirm(client, db):
    admin = db.users[1]
    status = client.get("/auth/mfa", headers=bearer(admin)).json()
    assert status == {"available": True, "enabled": False, "required": False, "required_roles": [],
                      "recovery_codes_left": None}

    setup = client.post("/auth/mfa/setup", headers=bearer(admin))
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert client.post("/auth/mfa/confirm", json={"code": "000000"}, headers=bearer(admin)).status_code == 400
    done = client.post("/auth/mfa/confirm", json={"code": now_code(secret)}, headers=bearer(admin))
    assert done.status_code == 200 and len(done.json()["recovery_codes"]) == 10

    status = client.get("/auth/mfa", headers=bearer(admin)).json()
    assert status["enabled"] is True and status["recovery_codes_left"] == 10
    assert client.post("/auth/mfa/setup", headers=bearer(admin)).status_code == 409


def test_new_recovery_codes_replace_the_old_ones(client, db):
    admin = db.users[1]
    secret, old = turn_on(db, 1)
    assert client.post("/auth/mfa/recovery-codes", json={"code": "000000"}, headers=bearer(admin)).status_code == 400
    res = client.post("/auth/mfa/recovery-codes", json={"code": now_code(secret)}, headers=bearer(admin))
    assert res.status_code == 200
    new = res.json()["recovery_codes"]
    assert set(new).isdisjoint(old)
    assert mfa.hash_recovery_code(old[0]) not in db.mfa[1]["recovery_hashes"]
    assert any(a["action"] == "Recovery Codes Replaced" for a in db.audit)


def test_turning_it_off_needs_a_code(client, db):
    admin = db.users[1]
    secret, _ = turn_on(db, 1)
    assert client.post("/auth/mfa/disable", json={"code": "000000"}, headers=bearer(admin)).status_code == 400
    assert 1 in db.mfa
    assert client.post("/auth/mfa/disable", json={"code": now_code(secret)}, headers=bearer(admin)).status_code == 204
    assert 1 not in db.mfa
    assert any(a["action"] == "Two-Step Sign-In Off" for a in db.audit)


def test_a_required_role_cannot_turn_it_off(client, db, monkeypatch):
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "admin")
    admin = db.users[1]
    secret, _ = turn_on(db, 1)
    res = client.post("/auth/mfa/disable", json={"code": now_code(secret)}, headers=bearer(admin))
    assert res.status_code == 409
    assert 1 in db.mfa


def test_wrong_codes_on_your_account_count_toward_the_lock(client, db):
    admin = db.users[1]
    turn_on(db, 1)
    for _ in range(MAX_FAILURES_PER_EMAIL - 1):
        assert client.post("/auth/mfa/disable", json={"code": "000000"}, headers=bearer(admin)).status_code == 400
    assert client.post("/auth/mfa/disable", json={"code": "000000"}, headers=bearer(admin)).status_code == 429


# ── The admin reset and User Management ────────────────────────────────────
def test_an_admin_resets_someone_elses(client, db):
    turn_on(db, 2)
    res = client.post("/users/2/mfa/reset", headers=bearer(db.users[1]))
    assert res.status_code == 204
    assert 2 not in db.mfa
    assert db.revoked == [2]
    reset = [a for a in db.audit if a["action"] == "Two-Step Sign-In Reset"]
    assert reset and reset[0]["details"] == "staff@ssmcapstone.com"


def test_the_reset_is_refused_for_yourself_for_staff_and_when_it_is_off(client, db):
    turn_on(db, 1)
    assert client.post("/users/1/mfa/reset", headers=bearer(db.users[1])).status_code == 400
    assert client.post("/users/1/mfa/reset", headers=bearer(db.users[2])).status_code == 403
    assert client.post("/users/2/mfa/reset", headers=bearer(db.users[1])).status_code == 409
    assert 1 in db.mfa


def test_the_user_list_shows_who_has_it(client, db):
    turn_on(db, 2)
    users = {u["user_id"]: u for u in client.get("/users", headers=bearer(db.users[1])).json()}
    assert users[1]["mfa_enabled"] is False and users[2]["mfa_enabled"] is True


# ── Before migration 0035 ──────────────────────────────────────────────────
def test_before_the_migration_nothing_changes(client, db, monkeypatch):
    monkeypatch.setattr(mfa, "mfa_ready", lambda db: False)
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "admin,staff")
    assert password_step(client).json()["access_token"]
    status = client.get("/auth/mfa", headers=bearer(db.users[1])).json()
    assert status["available"] is False and status["enabled"] is False
    res = client.post("/auth/mfa/setup", headers=bearer(db.users[1]))
    assert res.status_code == 503 and res.json()["code"] == "mfa_not_ready"
