"""
tests/backend/test_avatar.py — POST /users/me/avatar (backend/avatar.py).

Same FakeSession-over-TestClient approach as tests/backend/test_users.py.
backend.avatar.upload (the Supabase Storage PUT) is monkeypatched in every
test here, so nothing touches a real Storage bucket; its calls are captured
instead so a test can inspect what would have been uploaded.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import auth_utils
from backend.deps import get_db
from backend.main import app


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


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
    """Stands in for a SQLAlchemy Session, matching only the one UPDATE
    backend/routers/users.py's upload_avatar issues."""

    def __init__(self, users):
        self.users = users
        self.committed = False

    def _out(self, user):
        return {
            "user_id": user["user_id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "created_at": user["created_at"],
            "avatar_path": user["avatar_path"],
            "status": "invited" if user["password_hash"] is None else "active",
        }

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        params = params or {}
        if sql.startswith("SELECT avatar_path FROM users WHERE user_id"):
            user = next(u for u in self.users if u["user_id"] == params["user_id"])
            return FakeResult(scalar=user["avatar_path"])
        if sql.startswith("UPDATE users SET avatar_path"):
            user = next(u for u in self.users if u["user_id"] == params["user_id"])
            user["avatar_path"] = params["avatar_path"]
            return FakeResult(row=self._out(user))
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def commit(self):
        self.committed = True

    def close(self):
        pass


@pytest.fixture
def fake_users():
    return [
        {
            "user_id": 1, "email": "admin@ssmcapstone.com",
            "password_hash": auth_utils.hash_password("correct-horse-battery-staple"),
            "full_name": "Admin User", "role": "admin",
            "created_at": "2026-01-01T00:00:00+00:00", "avatar_path": None,
        },
        {
            "user_id": 2, "email": "staff@ssmcapstone.com",
            "password_hash": auth_utils.hash_password("staff-password-1"),
            "full_name": "Staff User", "role": "staff",
            "created_at": "2026-01-02T00:00:00+00:00", "avatar_path": None,
        },
    ]


@pytest.fixture
def session(fake_users):
    return FakeSession(fake_users)


@pytest.fixture
def uploads(monkeypatch):
    """Captures backend.avatar.upload calls instead of hitting Storage."""
    from backend import avatar

    calls: list[tuple[str, bytes]] = []
    monkeypatch.setattr(avatar, "upload", lambda object_name, data: calls.append((object_name, data)))
    return calls


@pytest.fixture
def deletes(monkeypatch):
    """Captures backend.avatar.delete calls instead of hitting Storage."""
    from backend import avatar

    calls: list[str] = []
    monkeypatch.setattr(avatar, "delete", lambda object_name: calls.append(object_name))
    return calls


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def staff_token():
    return auth_utils.create_access_token(
        user_id=2, email="staff@ssmcapstone.com", role="staff", full_name="Staff User"
    )


def admin_token():
    return auth_utils.create_access_token(
        user_id=1, email="admin@ssmcapstone.com", role="admin", full_name="Admin User"
    )


def staff_headers():
    return {"Authorization": f"Bearer {staff_token()}"}


def _valid_image_bytes(size=(300, 200), color=(255, 0, 0)) -> bytes:
    img = Image.new("RGB", size, color)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _huge_dimension_png(width: int, height: int) -> bytes:
    """A hand-built PNG whose IHDR declares `width`x`height` with no actual
    pixel data behind it -- a few dozen bytes on the wire, but a decoder
    that trusts the header would try to allocate a width*height buffer.
    Pillow determines .size from IHDR before touching IDAT, so this is
    enough to exercise the dimension check without ever decoding anything."""
    import struct
    import zlib

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB, no interlace
    idat = zlib.compress(b"")  # empty, valid deflate stream; never decoded in this test
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_oversize_upload_rejected(client, uploads):
    oversize = b"x" * (2 * 1024 * 1024 + 1)
    resp = client.post(
        "/users/me/avatar",
        files={"file": ("photo.jpg", oversize, "image/jpeg")},
        headers=staff_headers(),
    )
    assert resp.status_code == 413
    assert uploads == []  # never got far enough to re-encode or upload


def test_non_image_with_image_content_type_rejected(client, uploads):
    not_an_image = b"this is definitely not image data, just plain text bytes"
    resp = client.post(
        "/users/me/avatar",
        files={"file": ("photo.jpg", not_an_image, "image/jpeg")},
        headers=staff_headers(),
    )
    assert resp.status_code == 400
    assert uploads == []


def test_successful_upload_produces_128x128_webp(client, uploads, deletes, session, fake_users):
    resp = client.post(
        "/users/me/avatar",
        files={"file": ("photo.png", _valid_image_bytes(), "image/png")},
        headers=staff_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == 2
    assert body["avatar_path"] is not None
    assert fake_users[1]["avatar_path"] == body["avatar_path"]

    assert len(uploads) == 1
    object_name, data = uploads[0]
    assert object_name.startswith("2/") and object_name.endswith(".webp")
    out_img = Image.open(io.BytesIO(data))
    assert out_img.size == (128, 128)
    assert out_img.format == "WEBP"

    # No prior avatar on this account -- nothing to clean up.
    assert deletes == []


def test_replacing_avatar_deletes_old_object(client, uploads, deletes, fake_users):
    fake_users[1]["avatar_path"] = "2/old-object.webp"
    resp = client.post(
        "/users/me/avatar",
        files={"file": ("photo.png", _valid_image_bytes(), "image/png")},
        headers=staff_headers(),
    )
    assert resp.status_code == 200
    new_object_name, _ = uploads[0]
    assert deletes == ["2/old-object.webp"]
    assert new_object_name != "2/old-object.webp"  # the new path never collides with the old one


def test_huge_declared_dimensions_rejected(client, uploads):
    """A small file declaring an enormous image must be rejected before any
    pixel buffer is allocated for it."""
    bomb = _huge_dimension_png(100_000, 100_000)  # 10 billion declared pixels, well under 1 KB on the wire
    assert len(bomb) < 1024
    resp = client.post(
        "/users/me/avatar",
        files={"file": ("photo.png", bomb, "image/png")},
        headers=staff_headers(),
    )
    assert resp.status_code == 400
    assert uploads == []


def test_user_cannot_set_another_users_avatar(client, uploads, fake_users):
    """There is no user_id in the request at all — the target is always the
    signed-in account from the auth dependency. Confirms a staff upload never
    touches another account's row, even if one is suggested in the form."""
    resp = client.post(
        "/users/me/avatar",
        data={"user_id": "1"},  # not a real field the endpoint reads
        files={"file": ("photo.png", _valid_image_bytes(), "image/png")},
        headers=staff_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == 2
    assert fake_users[0]["avatar_path"] is None  # admin's row (user_id 1) untouched
    assert fake_users[1]["avatar_path"] is not None  # only the caller's own row changed


def test_upload_requires_auth(client, uploads):
    resp = client.post(
        "/users/me/avatar",
        files={"file": ("photo.png", _valid_image_bytes(), "image/png")},
    )
    assert resp.status_code == 401
    assert uploads == []
