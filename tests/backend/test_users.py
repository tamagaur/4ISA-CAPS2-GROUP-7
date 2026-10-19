"""
tests/backend/test_users.py — user management (users.manage): GET /users,
PATCH /users/{user_id}, DELETE /users/{user_id}, POST /users/{user_id}/send-link.

Same FakeSession-over-TestClient approach as tests/backend/test_auth.py, so
these never touch a real Supabase instance either. Since 2026-09-28 admins
can't set passwords or change their own role, and a change ends the affected
user's sessions and writes an audit entry — all checked here.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils, mailer
from backend.deps import get_db
from backend.main import app


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


class FakeResult:
    def __init__(self, row=None, rows=None, rowcount=0, scalar=None):
        self._row = row
        self._rows = rows or []
        self.rowcount = rowcount
        self._scalar = scalar

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return self._rows


class FakeSession:
    """Stands in for a SQLAlchemy Session, matching only the query shapes
    backend/routers/users.py actually issues."""

    def __init__(self, users):
        self.users = users
        self.committed = False
        self.revoked: list[int] = []  # user_ids whose sessions were ended
        self.audit: list[dict] = []
        self.tokens: list[dict] = []

    @staticmethod
    def _out(user):
        return {
            **{k: user[k] for k in ("user_id", "email", "full_name", "role", "created_at")},
            "status": "invited" if user["password_hash"] is None else "active",
            # USER_COLUMNS reads it from user_session; None = never signed in.
            "last_sign_in_at": user.get("last_sign_in_at"),
            # USER_COLUMNS reads it from auth_token; invited accounts only.
            "invite_expires_at": user.get("invite_expires_at") if user["password_hash"] is None else None,
        }

    def _find(self, user_id):
        return next((u for u in self.users if u["user_id"] == user_id), None)

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        params = params or {}

        if sql.startswith("SELECT") and sql.endswith("FROM users ORDER BY user_id"):
            return FakeResult(rows=[self._out(u) for u in self.users])

        if sql.startswith("SELECT 1 FROM users WHERE lower(email) = lower(:email) AND user_id != :user_id"):
            exists = any(
                u["email"].lower() == params["email"].lower() and u["user_id"] != params["user_id"]
                for u in self.users
            )
            return FakeResult(row=True if exists else None)

        if "FROM users WHERE role = 'admin' FOR UPDATE" in sql:
            return FakeResult(scalar=sum(u["role"] == "admin" for u in self.users))

        if sql.startswith("SELECT") and sql.endswith("FROM users WHERE user_id = :user_id"):
            user = self._find(params["user_id"])
            return FakeResult(row=self._out(user) if user else None)

        if sql.startswith("UPDATE users SET"):
            user = self._find(params["user_id"])
            for key in ("email", "full_name", "role"):
                if key in params:
                    user[key] = params[key]
            return FakeResult(row=self._out(user))

        if sql == "DELETE FROM users WHERE user_id = :user_id":
            before = len(self.users)
            self.users[:] = [u for u in self.users if u["user_id"] != params["user_id"]]
            return FakeResult(rowcount=before - len(self.users))

        if "end_reason = 'revoked'" in sql:
            self.revoked.append(params["user_id"])
            return FakeResult()

        if sql.startswith("INSERT INTO audit_log"):
            self.audit.append(dict(params))
            return FakeResult()

        if sql.startswith("UPDATE auth_token SET used_at"):
            return FakeResult()

        if sql.startswith("INSERT INTO auth_token"):
            self.tokens.append(dict(params))
            return FakeResult(row={"expires_at": datetime(2026, 9, 30, tzinfo=timezone.utc)})

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
            "full_name": "Admin User",
            "role": "admin",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "user_id": 2,
            "email": "staff@ssmcapstone.com",
            "password_hash": auth_utils.hash_password("staff-password-1"),
            "full_name": "Staff User",
            "role": "staff",
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "user_id": 3,
            "email": "invited@ssmcapstone.com",
            "password_hash": None,
            "full_name": "Invited User",
            "role": "staff",
            "created_at": "2026-01-03T00:00:00+00:00",
        },
    ]


@pytest.fixture
def session(fake_users):
    return FakeSession(fake_users)


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
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


def admin_headers():
    return {"Authorization": f"Bearer {admin_token()}"}


# --- GET /users -----------------------------------------------------------


def test_list_users_requires_auth(client):
    resp = client.get("/users")
    assert resp.status_code == 401


def test_list_users_forbidden_for_non_admin(client):
    resp = client.get("/users", headers={"Authorization": f"Bearer {staff_token()}"})
    assert resp.status_code == 403


def test_list_users_success_for_admin(client):
    resp = client.get("/users", headers=admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert [u["email"] for u in body] == [
        "admin@ssmcapstone.com", "staff@ssmcapstone.com", "invited@ssmcapstone.com",
    ]
    assert [u["status"] for u in body] == ["active", "active", "invited"]
    assert "password_hash" not in body[0]


def test_the_list_shows_each_last_sign_in(client, fake_users):
    """For the security audit: the latest sign-in (date and time) from
    user_session, or null for an account that has never signed in."""
    from backend.routers.users import USER_COLUMNS
    assert "SELECT max(s.started_at) FROM user_session s WHERE s.user_id = users.user_id" in USER_COLUMNS
    fake_users[0]["last_sign_in_at"] = "2026-10-02T13:05:11+00:00"
    body = client.get("/users", headers=admin_headers()).json()
    assert [u["last_sign_in_at"] for u in body] == ["2026-10-02T13:05:11Z", None, None]


def test_the_list_shows_when_an_invite_expires(client, fake_users):
    """The table turns an invite red once its link has expired, so the list
    carries the newest invite's expiry for accounts still without a password."""
    from backend.routers.users import USER_COLUMNS
    assert "t.purpose = 'invite'" in USER_COLUMNS
    assert "CASE WHEN password_hash IS NULL THEN (SELECT max(t.expires_at) FROM auth_token t" in USER_COLUMNS
    fake_users[2]["invite_expires_at"] = "2026-10-17T09:30:00+00:00"
    fake_users[0]["invite_expires_at"] = "2026-10-17T09:30:00+00:00"  # active: never reported
    body = client.get("/users", headers=admin_headers()).json()
    assert [u["invite_expires_at"] for u in body] == [None, None, "2026-10-17T09:30:00Z"]


# --- PATCH /users/{user_id} -------------------------------------------------


def test_update_user_requires_auth(client):
    resp = client.patch("/users/2", json={"full_name": "New Name"})
    assert resp.status_code == 401


def test_update_user_forbidden_for_non_admin(client):
    resp = client.patch(
        "/users/2",
        json={"full_name": "New Name"},
        headers={"Authorization": f"Bearer {staff_token()}"},
    )
    assert resp.status_code == 403


def test_update_user_not_found(client):
    resp = client.patch("/users/999", json={"full_name": "Nobody"}, headers=admin_headers())
    assert resp.status_code == 404


def test_role_change_signs_the_user_out_and_is_audited(client, session, fake_users):
    resp = client.patch(
        "/users/2",
        json={"full_name": "Staff Renamed", "role": "admin"},
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["full_name"] == "Staff Renamed"
    assert body["role"] == "admin"
    assert fake_users[1]["full_name"] == "Staff Renamed"
    assert fake_users[1]["role"] == "admin"
    assert session.revoked == [2]
    (entry,) = session.audit
    assert entry["action"] == "Edit User"
    assert entry["user_email"] == "admin@ssmcapstone.com"
    assert entry["details"] == (
        "staff@ssmcapstone.com: name: Staff User → Staff Renamed; role: staff → admin"
    )


def test_name_change_keeps_the_user_signed_in(client, session):
    resp = client.patch("/users/2", json={"full_name": "Staff Renamed"}, headers=admin_headers())
    assert resp.status_code == 200
    assert session.revoked == []
    assert [a["action"] for a in session.audit] == ["Edit User"]


def test_admins_can_no_longer_set_passwords(client, fake_users):
    """Only the account's owner sets a password, through an emailed link."""
    before = fake_users[1]["password_hash"]
    resp = client.patch("/users/2", json={"password": "brand-new-password"}, headers=admin_headers())
    assert resp.status_code == 422
    assert fake_users[1]["password_hash"] == before


def test_admin_cannot_change_their_own_role(client, session):
    resp = client.patch("/users/1", json={"role": "staff"}, headers=admin_headers())
    assert resp.status_code == 400
    assert session.audit == []


def test_admin_can_still_rename_themselves(client):
    resp = client.patch("/users/1", json={"full_name": "Admin Renamed", "role": "admin"}, headers=admin_headers())
    assert resp.status_code == 200


def test_update_user_email_conflict(client):
    resp = client.patch(
        "/users/2", json={"email": "admin@ssmcapstone.com"}, headers=admin_headers()
    )
    assert resp.status_code == 409


def test_update_user_email_conflict_ignores_capitalisation(client):
    resp = client.patch(
        "/users/2", json={"email": "Admin@SSMcapstone.com"}, headers=admin_headers()
    )
    assert resp.status_code == 409


def test_a_user_may_change_the_case_of_their_own_email(client):
    resp = client.patch(
        "/users/2", json={"email": "Staff@ssmcapstone.com"}, headers=admin_headers()
    )
    assert resp.status_code == 200


def test_update_user_empty_body_rejected(client):
    resp = client.patch("/users/2", json={}, headers=admin_headers())
    assert resp.status_code == 422


def test_update_user_rejects_invalid_role(client):
    resp = client.patch("/users/2", json={"role": "superuser"}, headers=admin_headers())
    assert resp.status_code == 422


# --- DELETE /users/{user_id} ------------------------------------------------


def test_delete_user_requires_auth(client):
    resp = client.delete("/users/2")
    assert resp.status_code == 401


def test_delete_user_forbidden_for_non_admin(client):
    resp = client.delete("/users/1", headers={"Authorization": f"Bearer {staff_token()}"})
    assert resp.status_code == 403


def test_delete_user_rejects_self_delete(client):
    resp = client.delete("/users/1", headers=admin_headers())
    assert resp.status_code == 400


def test_delete_user_not_found(client):
    resp = client.delete("/users/999", headers=admin_headers())
    assert resp.status_code == 404


def test_delete_user_signs_them_out_and_is_audited(client, session, fake_users):
    resp = client.delete("/users/2", headers=admin_headers())
    assert resp.status_code == 204
    assert all(u["user_id"] != 2 for u in fake_users)
    assert session.revoked == [2]
    assert [(a["action"], a["details"]) for a in session.audit] == [
        ("Delete User", "Removed staff@ssmcapstone.com (staff)")
    ]


# --- POST /users/{user_id}/send-link ----------------------------------------


def test_send_link_resends_the_invite_while_it_is_pending(client, session, outbox):
    body = client.post("/users/3/send-link", headers=admin_headers()).json()
    assert body["purpose"] == "invite"
    assert body["email_sent"] is True and body["setup_link"] is None
    assert [m["to"] for m in outbox] == ["invited@ssmcapstone.com"]
    assert "48 hours" in outbox[0]["body"]
    assert session.audit[-1]["action"] == "Invite Resent"


def test_send_link_sends_a_reset_for_an_active_account(client, session, outbox):
    body = client.post("/users/2/send-link", headers=admin_headers()).json()
    assert body["purpose"] == "reset"
    assert "24 hours" in outbox[0]["body"]
    assert session.tokens[0]["purpose"] == "reset"
    assert session.audit[-1]["action"] == "Reset Link Sent"


def test_send_link_hands_back_the_link_when_email_fails(client, monkeypatch):
    def fail(to, subject, body, **_):
        raise mailer.MailError("The email couldn't be sent, so share the link another way.")

    monkeypatch.setattr(mailer, "send", fail)
    body = client.post("/users/2/send-link", headers=admin_headers()).json()
    assert body["email_sent"] is False
    assert "/set-password#token=" in body["setup_link"]
    assert body["email_problem"] == "The email couldn't be sent, so share the link another way."


def test_send_link_forbidden_for_non_admin(client):
    resp = client.post("/users/2/send-link", headers={"Authorization": f"Bearer {staff_token()}"})
    assert resp.status_code == 403


def test_send_link_not_found(client):
    assert client.post("/users/999/send-link", headers=admin_headers()).status_code == 404
