"""
tests/backend/test_avatar_url.py — avatar_url: the full public URL for a
picture, computed from avatar_path and SUPABASE_URL, never stored.

avatar_path alone is a path inside the Supabase Storage "avatars" bucket
(e.g. "1/abc123.webp") -- a frontend <img src> can't load that directly. Both
UserOut (backend/schemas/users.py, the /users routes and POST
/users/me/avatar) and MeResponse (backend/schemas/permissions.py, GET/PATCH
/auth/me) add avatar_url as a pydantic computed_field built from
backend.avatar.public_url(avatar_path), so every response that carries a
path also carries the ready-to-use URL -- additive, avatar_path is unchanged.
The Supabase base comes only from the SUPABASE_URL environment variable
(never hardcoded, never duplicated into a frontend file).
"""
from __future__ import annotations

import re

import pytest

from backend import avatar
from backend.schemas.permissions import MeResponse
from backend.schemas.users import UserOut

SUPABASE_URL = "https://dsdxemtmbbmdtccwxzyk.supabase.co"


@pytest.fixture(autouse=True)
def supabase_url_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)


def _user_out(avatar_path):
    return UserOut(
        user_id=1, email="a@b.com", full_name="A User", role="admin",
        created_at="2026-01-01T00:00:00+00:00", avatar_path=avatar_path,
    )


def _me_response(avatar_path):
    return MeResponse(
        user_id=1, email="a@b.com", full_name="A User", role="admin",
        permissions=[], avatar_path=avatar_path,
    )


def test_public_url_is_none_without_an_object_name():
    assert avatar.public_url(None) is None


def test_public_url_is_well_formed_for_an_object_name():
    url = avatar.public_url("42/deadbeefcafef00d.webp")
    assert url == f"{SUPABASE_URL}/storage/v1/object/public/avatars/42/deadbeefcafef00d.webp"
    assert re.match(r"^https://[^/]+/storage/v1/object/public/avatars/42/deadbeefcafef00d\.webp$", url)


def test_public_url_is_none_when_supabase_url_is_unset(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert avatar.public_url("42/deadbeefcafef00d.webp") is None


def test_user_out_avatar_url_is_null_when_no_picture():
    body = _user_out(None).model_dump()
    assert body["avatar_path"] is None
    assert body["avatar_url"] is None


def test_user_out_avatar_url_is_well_formed_when_a_picture_is_set():
    body = _user_out("7/abc123.webp").model_dump()
    assert body["avatar_path"] == "7/abc123.webp"  # avatar_url is additive, avatar_path unchanged
    assert body["avatar_url"] == f"{SUPABASE_URL}/storage/v1/object/public/avatars/7/abc123.webp"


def test_me_response_avatar_url_is_null_when_no_picture():
    body = _me_response(None).model_dump()
    assert body["avatar_path"] is None
    assert body["avatar_url"] is None


def test_me_response_avatar_url_is_well_formed_when_a_picture_is_set():
    body = _me_response("9/xyz789.webp").model_dump()
    assert body["avatar_path"] == "9/xyz789.webp"
    assert body["avatar_url"] == f"{SUPABASE_URL}/storage/v1/object/public/avatars/9/xyz789.webp"


def test_avatar_url_never_appears_in_the_frontend_source():
    """The URL is built server-side only -- no frontend file should ever
    construct or hardcode the Supabase Storage base itself."""
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    frontend_src = repo_root / "frontend" / "src"
    hits = []
    for path in frontend_src.rglob("*.*"):
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "storage/v1/object" in text or "supabase.co" in text:
            hits.append(str(path.relative_to(repo_root)))
    assert hits == []
