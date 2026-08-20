"""
backend.schemas.users — Pydantic models for GET/PATCH/DELETE /users
(admin-only user management).

UserCreate mirrors RegisterRequest (backend/schemas/auth.py) rather than
importing it — POST /auth/register stays the create path (Story #89), this
module only covers list/update.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class UserOut(BaseModel):
    user_id: int
    email: EmailStr
    full_name: str
    role: str
    created_at: datetime


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1)
    role: Literal["admin", "staff"] | None = None
    password: str | None = Field(default=None, min_length=8)
