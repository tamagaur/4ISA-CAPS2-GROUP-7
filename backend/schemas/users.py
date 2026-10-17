"""
backend.schemas.users — Pydantic models for the admin-only /users routes.

Creating an account goes through POST /auth/register (backend/schemas/auth.py
RegisterRequest); this module covers list/update.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    user_id: int
    email: EmailStr
    full_name: str
    role: str
    # 'invited' until the person sets a password through their invite link.
    status: Literal["active", "invited"] = "active"
    created_at: datetime
    # Path inside the Supabase Storage "avatars" bucket; null when there is no
    # picture, so the frontend shows its initials fallback instead of a
    # placeholder image or an empty string (migration 0059).
    avatar_path: str | None = None
    # Two-step sign-in on (backend/mfa.py). Always false before migration 0035.
    mfa_enabled: bool = False
    # Latest sign-in, from user_session (backend/routers/users.py
    # USER_COLUMNS). None = never signed in.
    last_sign_in_at: datetime | None = None


class UserUpdate(BaseModel):
    """Admins change name, email and role. Since 2026-09-28 only the account's
    owner sets its password, through an emailed link (POST
    /users/{id}/send-link), so a `password` field is refused (422)."""
    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Literal["admin", "staff"] | None = None
