"""
backend.schemas.auth — Pydantic models for the /auth routes.

Story #89: login with hashed credentials. 2026-09-28: accounts are created
by invite (the admin sets no password) and passwords are set through
one-time links — see backend/account_links.py.
"""
from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from backend.auth_utils import PASSWORD_MAX_BYTES, PASSWORD_MIN_LENGTH
from backend.schemas.users import UserOut


class LoginRequest(BaseModel):
    email: EmailStr
    # Capped so an absurd body never reaches bcrypt (passlib raises on
    # anything over 4096 characters, which would surface as a 500).
    password: str = Field(max_length=1024)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str


class RegisterRequest(BaseModel):
    """An admin creates the account; its owner sets the password through the
    emailed link. A `password` field is refused (422), not ignored."""
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "staff"] = "staff"


class LinkSent(BaseModel):
    """What an admin gets back after an invite or reset link is made: whether
    it was emailed and, if not, the link to pass on themselves and why."""
    email_sent: bool
    setup_link: str | None = None
    expires_at: datetime.datetime
    email_problem: str | None = None


class InviteResponse(LinkSent):
    user: UserOut


class SendLinkResponse(LinkSent):
    purpose: Literal["invite", "reset"]


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class LinkInfo(BaseModel):
    purpose: Literal["invite", "reset"]
    email: str
    full_name: str
    expires_at: datetime.datetime


class SetPasswordRequest(TokenRequest):
    password: str = Field(min_length=PASSWORD_MIN_LENGTH)

    @field_validator("password")
    @classmethod
    def _fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
            raise ValueError(
                f"Password must be at most {PASSWORD_MAX_BYTES} bytes "
                f"(about {PASSWORD_MAX_BYTES} characters)."
            )
        return value


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class MessageResponse(BaseModel):
    detail: str
