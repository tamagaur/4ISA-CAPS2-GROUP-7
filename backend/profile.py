"""The signed-in person's own profile: display name and picture
(PATCH /auth/me, backend/routers/auth.py; the My profile page).

The picture is a small data URL kept on the account row (migration 0058,
app.users.avatar_data_url). Until that migration is applied the column
isn't there: names can still be changed, and a picture answers 503
profile_pictures_not_ready. The probe is cached like
backend/permissions.permissions_ready, so it costs one query a minute
until the column is seen and none after.
"""
from __future__ import annotations

import base64
import binascii
import re
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.api_errors import ApiError

# What the browser sends: ProfilePage.jsx squares and shrinks the picture to
# 192 x 192 before upload, so a real one is 10-30 KB. The ceiling leaves
# room for a PNG with detail, and keeps a stray multi-megabyte upload out.
MAX_AVATAR_CHARS = 200_000
MAX_AVATAR_BYTES = 150_000
AVATAR_PATTERN = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+=*)$")
MAX_NAME_CHARS = 200

NOT_READY = "Profile pictures aren't available on this server yet (migration 0058 is not applied)."
AVATAR_INVALID = "The picture must be a PNG, JPEG or WebP image."
AVATAR_TOO_BIG = "That picture is too large. Choose a smaller one."
NAME_BLANK = "Enter a display name."
NAME_TOO_LONG = f"The display name is at most {MAX_NAME_CHARS} characters."

READY_SQL = (
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = 'app' AND table_name = 'users' AND column_name = 'avatar_data_url'"
)
_READY_RECHECK_SECONDS = 60
_ready_cache = {"value": False, "checked_at": 0.0}

READ_AVATAR_SQL = "SELECT avatar_data_url FROM users WHERE user_id = :user_id"


def pictures_ready(db: Session) -> bool:
    """True once app.users has the picture column (migration 0058)."""
    if _ready_cache["value"]:
        return True
    now = time.monotonic()
    if _ready_cache["checked_at"] and now - _ready_cache["checked_at"] < _READY_RECHECK_SECONDS:
        return False
    found = db.execute(text(READY_SQL)).scalar()
    _ready_cache.update(value=bool(found), checked_at=now)
    return bool(found)


def read_avatar(db: Session, user_id: int) -> str | None:
    """The account's picture, or None (no picture, or no column yet)."""
    if not pictures_ready(db):
        return None
    row = db.execute(text(READ_AVATAR_SQL), {"user_id": user_id}).mappings().first()
    return row["avatar_data_url"] if row else None


def clean_name(full_name: str) -> str:
    """The display name as it will be stored: trimmed, inner runs of
    spaces collapsed; 422 if blank or too long."""
    name = " ".join(full_name.split())
    if not name:
        raise ApiError(422, NAME_BLANK, code="name_blank")
    if len(name) > MAX_NAME_CHARS:
        raise ApiError(422, NAME_TOO_LONG, code="name_too_long")
    return name


def check_avatar(avatar_data_url: str) -> str:
    """The picture as it will be stored; 422 unless it is a small PNG, JPEG
    or WebP data URL whose base64 actually decodes."""
    if len(avatar_data_url) > MAX_AVATAR_CHARS:
        raise ApiError(422, AVATAR_TOO_BIG, code="avatar_too_big")
    match = AVATAR_PATTERN.match(avatar_data_url)
    if not match:
        raise ApiError(422, AVATAR_INVALID, code="avatar_invalid")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError(422, AVATAR_INVALID, code="avatar_invalid") from exc
    if len(raw) > MAX_AVATAR_BYTES:
        raise ApiError(422, AVATAR_TOO_BIG, code="avatar_too_big")
    return avatar_data_url


def update(db: Session, user_id: int, *, full_name: str | None, avatar: str | None, set_avatar: bool) -> None:
    """Writes the given fields in the caller's transaction (the caller
    commits). `set_avatar` says whether the picture changes at all;
    `avatar` None with it set means "remove the picture"."""
    sets = []
    params: dict = {"user_id": user_id}
    if full_name is not None:
        sets.append("full_name = :full_name")
        params["full_name"] = full_name
    if set_avatar:
        if not pictures_ready(db):
            raise ApiError(503, NOT_READY, code="profile_pictures_not_ready")
        sets.append("avatar_data_url = :avatar")
        params["avatar"] = avatar
    if not sets:
        return
    db.execute(text(f"UPDATE users SET {', '.join(sets)} WHERE user_id = :user_id"), params)
