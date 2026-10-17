"""The signed-in person's own profile: display name and picture
(PATCH /auth/me, backend/routers/auth.py; the My profile page).

The picture itself never touches a column (migration 0060 retired
app.users.avatar_data_url — see that file for why). This module only turns
the data URL the browser sends into raw bytes; backend/avatar.py does
everything after that — the SAME validation, resize and Supabase Storage
upload as POST /users/me/avatar — so the two entry points never run two
copies of that logic. What is stored here is avatar_path (migration 0059),
exactly like the other route.

Until migration 0059 is applied the column isn't there: names can still be
changed, and a picture answers 503 profile_pictures_not_ready. The probe is
cached like backend/permissions.permissions_ready, so it costs one query a
minute until the column is seen and none after.
"""
from __future__ import annotations

import base64
import binascii
import re
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import avatar
from backend.api_errors import ApiError

# What the browser sends: ProfilePage.jsx squares and shrinks the picture
# before upload, as a data URL. Parsing that into raw bytes is the one job
# specific to this entry point; avatar.py's own MAX_AVATAR_BYTES cap (applied
# to the DECODED bytes below) is the same ceiling the multipart route uses,
# not a second number to keep in step with it.
AVATAR_DATA_URL_PATTERN = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+=*)$")
# Bounds the base64 TEXT before it is decoded, so a client can't make the
# server spend effort decoding an arbitrarily huge string. base64 expands
# bytes by 4/3; a little headroom for the data: prefix and padding.
MAX_AVATAR_DATA_URL_CHARS = (avatar.MAX_AVATAR_BYTES * 4 // 3) + 100
MAX_NAME_CHARS = 200

NOT_READY = "Profile pictures aren't available on this server yet (migration 0059 is not applied)."
AVATAR_INVALID = "The picture must be a PNG, JPEG or WebP image."
AVATAR_TOO_BIG = "That picture is too large. Choose a smaller one."
NAME_BLANK = "Enter a display name."
NAME_TOO_LONG = f"The display name is at most {MAX_NAME_CHARS} characters."

READY_SQL = (
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = 'app' AND table_name = 'users' AND column_name = 'avatar_path'"
)
_READY_RECHECK_SECONDS = 60
_ready_cache = {"value": False, "checked_at": 0.0}

READ_AVATAR_PATH_SQL = "SELECT avatar_path FROM users WHERE user_id = :user_id"


def pictures_ready(db: Session) -> bool:
    """True once app.users has the picture column (migration 0059)."""
    if _ready_cache["value"]:
        return True
    now = time.monotonic()
    if _ready_cache["checked_at"] and now - _ready_cache["checked_at"] < _READY_RECHECK_SECONDS:
        return False
    found = db.execute(text(READY_SQL)).scalar()
    _ready_cache.update(value=bool(found), checked_at=now)
    return bool(found)


def read_avatar_path(db: Session, user_id: int) -> str | None:
    """The account's picture path, or None (no picture, or no column yet)."""
    if not pictures_ready(db):
        return None
    row = db.execute(text(READ_AVATAR_PATH_SQL), {"user_id": user_id}).mappings().first()
    return row["avatar_path"] if row else None


def clean_name(full_name: str) -> str:
    """The display name as it will be stored: trimmed, inner runs of
    spaces collapsed; 422 if blank or too long."""
    name = " ".join(full_name.split())
    if not name:
        raise ApiError(422, NAME_BLANK, code="name_blank")
    if len(name) > MAX_NAME_CHARS:
        raise ApiError(422, NAME_TOO_LONG, code="name_too_long")
    return name


def decode_avatar_data_url(data_url: str) -> bytes:
    """Turns a "data:image/...;base64,..." string into raw image bytes, so
    it can run through the exact same validation, resize and Storage upload
    as a multipart upload (backend/avatar.py.to_avatar_webp, new_object_name,
    upload). 422 for anything that isn't image/png|jpeg|webp base64 that
    actually decodes, or for base64 text long enough that decoding it could
    not possibly stay under avatar.MAX_AVATAR_BYTES; 413 if it decodes to
    something over that cap after all."""
    if len(data_url) > MAX_AVATAR_DATA_URL_CHARS:
        raise ApiError(422, AVATAR_TOO_BIG, code="avatar_too_big")
    match = AVATAR_DATA_URL_PATTERN.match(data_url)
    if not match:
        raise ApiError(422, AVATAR_INVALID, code="avatar_invalid")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError(422, AVATAR_INVALID, code="avatar_invalid") from exc
    if len(raw) > avatar.MAX_AVATAR_BYTES:
        raise ApiError(422, AVATAR_TOO_BIG, code="avatar_too_big")
    return raw


def update(db: Session, user_id: int, *, full_name: str | None, avatar_path: str | None, set_avatar: bool) -> None:
    """Writes the given fields in the caller's transaction (the caller
    commits). `set_avatar` says whether the picture changes at all;
    `avatar_path` None with it set means "remove the picture"."""
    sets = []
    params: dict = {"user_id": user_id}
    if full_name is not None:
        sets.append("full_name = :full_name")
        params["full_name"] = full_name
    if set_avatar:
        if not pictures_ready(db):
            raise ApiError(503, NOT_READY, code="profile_pictures_not_ready")
        sets.append("avatar_path = :avatar_path")
        params["avatar_path"] = avatar_path
    if not sets:
        return
    db.execute(text(f"UPDATE users SET {', '.join(sets)} WHERE user_id = :user_id"), params)
