"""
tests/backend/test_users.py — admin-only user management: GET /users,
PATCH /users/{user_id}, DELETE /users/{user_id}.

Same FakeSession-over-TestClient approach as tests/backend/test_auth.py, so
these never touch a real Supabase instance either.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_db
from backend.main import app


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


class FakeResult:
    def __init__(self, row=None, rows=None, rowcount=0):
        self._row = row
        self._rows = rows or []
        self.rowcount = rowcount

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

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}

        if "SELECT user_id, email, full_name, role, created_at FROM users ORDER BY user_id" in sql:
            return FakeResult(rows=list(self.users))

        if "SELECT user_id FROM users WHERE user_id = :user_id" in sql:
            row = next((u for u in self.users if u["user_id"] == params["user_id"]), None)
            return FakeResult(row={"user_id": row["user_id"]} if row else None)

        if "SELECT 1 FROM users WHERE email = :email AND user_id != :user_id" in sql:
            exists = any(
                u["email"] == params["email"] and u["user_id"] != params["user_id"]
                for u in self.users
            )
            return FakeResult(row=True if exists else None)

        if sql.startswith("UPDATE users SET"):
            user = next(u for u in self.users if u["user_id"] == params["user_id"])
            for key in ("email", "full_name", "role", "password_hash"):
                if key in params:
                    user[key] = params[key]
            return FakeResult(row=dict(user))

        if sql.strip() == "DELETE FROM users WHERE user_id = :user_id":
            before = len(self.users)
            self.users[:] = [u for u in self.users if u["user_id"] != params["user_id"]]
            return FakeResult(rowcount=before - len(self.users))

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
    ]


@pytest.fixture
def client(fake_users):
    session = FakeSession(fake_users)
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
    assert len(body) == 2
    assert {u["email"] for u in body} == {"admin@ssmcapstone.com", "staff@ssmcapstone.com"}
    assert "password_hash" not in body[0]


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


def test_update_user_full_name_and_role(client, fake_users):
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


def test_update_user_password_is_hashed(client, fake_users):
    resp = client.patch(
        "/users/2", json={"password": "brand-new-password"}, headers=admin_headers()
    )
    assert resp.status_code == 200
    assert fake_users[1]["password_hash"] != "brand-new-password"
    assert auth_utils.verify_password("brand-new-password", fake_users[1]["password_hash"])


def test_update_user_email_conflict(client):
    resp = client.patch(
        "/users/2", json={"email": "admin@ssmcapstone.com"}, headers=admin_headers()
    )
    assert resp.status_code == 409


def test_update_user_empty_body_rejected(client):
    resp = client.patch("/users/2", json={}, headers=admin_headers())
    assert resp.status_code == 422


def test_update_user_rejects_invalid_role(client):
    resp = client.patch("/users/2", json={"role": "superuser"}, headers=admin_headers())
    assert resp.status_code == 422


def test_update_user_rejects_short_password(client):
    resp = client.patch("/users/2", json={"password": "short"}, headers=admin_headers())
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


def test_delete_user_success(client, fake_users):
    resp = client.delete("/users/2", headers=admin_headers())
    assert resp.status_code == 204
    assert all(u["user_id"] != 2 for u in fake_users)
