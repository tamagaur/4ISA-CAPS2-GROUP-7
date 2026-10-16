"""
tests/backend/test_profile.py — PATCH /auth/me (the My profile page):
display name and picture, with and without migration 0058's column.

Same FakeSession-over-TestClient approach as tests/backend/test_users.py;
tests/backend/conftest.py trusts signed tokens, so no session row is read.
"""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils, profile
from backend.deps import get_db
from backend.main import app

TINY_PNG = "data:image/png;base64," + base64.b64encode(
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
).decode()


class FakeResult:
    def __init__(self, row=None, scalar=None):
        self._row = row
        self._scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self._row

    def scalar(self):
        return self._scalar


class FakeSession:
    """Only the query shapes PATCH /auth/me and GET /auth/me issue."""

    def __init__(self, users, pictures):
        self.users = users
        self.pictures = pictures  # migration 0058 applied?
        self.committed = False
        self.audit: list[dict] = []
        self.info: dict = {}

    def _find(self, user_id):
        return next((u for u in self.users if u["user_id"] == user_id), None)

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        params = params or {}
        if "to_regclass('user_permission_override')" in sql:
            return FakeResult(scalar=True)
        if "information_schema.columns" in sql and "avatar_data_url" in sql:
            return FakeResult(scalar=1 if self.pictures else None)
        if sql.startswith("SELECT avatar_data_url FROM users WHERE user_id = :user_id"):
            user = self._find(params["user_id"])
            return FakeResult(row={"avatar_data_url": user.get("avatar")} if user else None)
        if sql.startswith("UPDATE users SET"):
            user = self._find(params["user_id"])
            if "full_name" in params:
                user["full_name"] = params["full_name"]
            if "avatar" in params:
                user["avatar"] = params["avatar"]
            return FakeResult()
        if sql.startswith("INSERT INTO audit_log"):
            self.audit.append(dict(params))
            return FakeResult()
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _fresh_probe(monkeypatch):
    monkeypatch.setattr(profile, "_ready_cache", {"value": False, "checked_at": 0.0})


@pytest.fixture
def users():
    return [{"user_id": 1, "email": "admin@ssmcapstone.com", "full_name": "Admin User", "role": "admin", "avatar": None}]


def make_client(session):
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


@pytest.fixture
def with_pictures(users):
    session = FakeSession(users, pictures=True)
    with make_client(session) as c:
        yield c, session
    app.dependency_overrides.clear()


@pytest.fixture
def without_pictures(users):
    session = FakeSession(users, pictures=False)
    with make_client(session) as c:
        yield c, session
    app.dependency_overrides.clear()


def headers():
    token = auth_utils.create_access_token(
        user_id=1, email="admin@ssmcapstone.com", role="admin", full_name="Admin User"
    )
    return {"Authorization": f"Bearer {token}"}


def test_requires_auth(with_pictures):
    client, _ = with_pictures
    assert client.patch("/auth/me", json={"full_name": "X"}).status_code == 401


def test_me_says_pictures_unavailable_without_the_migration(without_pictures):
    client, _ = without_pictures
    body = client.get("/auth/me", headers=headers()).json()
    assert body["profile_pictures"] is False and body["avatar_data_url"] is None


def test_me_says_pictures_available_with_the_migration(with_pictures):
    client, _ = with_pictures
    body = client.get("/auth/me", headers=headers()).json()
    assert body["profile_pictures"] is True and body["avatar_data_url"] is None


def test_rename_trims_saves_and_is_audited(without_pictures):
    client, session = without_pictures
    resp = client.patch("/auth/me", json={"full_name": "  Audrey   Bugayong "}, headers=headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["full_name"] == "Audrey Bugayong"
    assert session.users[0]["full_name"] == "Audrey Bugayong"
    assert session.committed
    assert session.audit[0]["action"] == "Edit Profile"
    assert "Admin User" in session.audit[0]["details"] and "Audrey Bugayong" in session.audit[0]["details"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_bad_names_are_refused(without_pictures, name):
    client, session = without_pictures
    assert client.patch("/auth/me", json={"full_name": name}, headers=headers()).status_code == 422
    assert session.users[0]["full_name"] == "Admin User"


def test_nothing_to_change_and_unknown_fields_are_refused(without_pictures):
    client, _ = without_pictures
    assert client.patch("/auth/me", json={}, headers=headers()).status_code == 422
    assert client.patch("/auth/me", json={"email": "new@x.com"}, headers=headers()).status_code == 422


def test_picture_needs_the_migration(without_pictures):
    client, session = without_pictures
    resp = client.patch("/auth/me", json={"avatar_data_url": TINY_PNG}, headers=headers())
    assert resp.status_code == 503
    assert resp.json()["code"] == "profile_pictures_not_ready"
    assert session.users[0]["avatar"] is None


def test_picture_saved_then_removed(with_pictures):
    client, session = with_pictures
    resp = client.patch("/auth/me", json={"avatar_data_url": TINY_PNG}, headers=headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["avatar_data_url"] == TINY_PNG
    assert session.users[0]["avatar"] == TINY_PNG
    assert "Picture changed" in session.audit[-1]["details"]
    assert client.get("/auth/me", headers=headers()).json()["avatar_data_url"] == TINY_PNG
    resp = client.patch("/auth/me", json={"avatar_data_url": None}, headers=headers())
    assert resp.status_code == 200
    assert session.users[0]["avatar"] is None
    assert "Picture removed" in session.audit[-1]["details"]


@pytest.mark.parametrize("bad", [
    pytest.param("data:text/plain;base64,QUJD", id="not_an_image"),
    pytest.param("data:image/png;base64,not*base64", id="bad_base64"),
    pytest.param("https://example.com/me.png", id="a_link"),
    pytest.param("data:image/png;base64," + "A" * profile.MAX_AVATAR_CHARS, id="too_long"),
])
def test_bad_pictures_are_refused(with_pictures, bad):
    client, session = with_pictures
    assert client.patch("/auth/me", json={"avatar_data_url": bad}, headers=headers()).status_code == 422
    assert session.users[0]["avatar"] is None
