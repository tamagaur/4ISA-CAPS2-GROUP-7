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
    # What an earlier sign-in with "Remember me" ticked gave this browser
    # (backend/mfa.py, REMEMBER_DAYS). A valid one skips the code step; any
    # other is ignored, never an error.
    remember_token: str | None = Field(default=None, max_length=2000)


class LoginResponse(BaseModel):
    """A sign-in token, or, when a second step is needed (backend/mfa.py),
    mfa_step and mfa_token instead: 'verify' = enter the code from the
    authenticator app; 'setup' = this role must use two-step sign-in and the
    account hasn't set it up yet. remember_token comes with the sign-in token
    when the code step was passed with "Remember me" ticked. Fields left
    empty are omitted."""
    access_token: str | None = None
    token_type: str = "bearer"
    role: str | None = None
    full_name: str | None = None
    mfa_step: Literal["verify", "setup"] | None = None
    mfa_token: str | None = None
    remember_token: str | None = None


class MfaCodeRequest(BaseModel):
    # A 6-digit app code or a recovery code; spaces and dashes are ignored.
    code: str = Field(min_length=1, max_length=40)


class MfaLoginRequest(MfaCodeRequest):
    mfa_token: str = Field(min_length=20, max_length=2000)


class MfaVerifyRequest(MfaLoginRequest):
    # "Remember me": don't ask this browser for the code for REMEMBER_DAYS.
    remember_device: bool = False


class MfaPendingRequest(BaseModel):
    mfa_token: str = Field(min_length=20, max_length=2000)


class MfaSetupResponse(BaseModel):
    """What the setup screen shows: the QR code carries otpauth_uri, and
    secret is the same key for typing into the app by hand."""
    secret: str
    otpauth_uri: str


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class MfaSetupDoneResponse(LoginResponse):
    """Setup finished during sign-in: the recovery codes to save, and the
    sign-in token."""
    recovery_codes: list[str]


class MfaStatus(BaseModel):
    """GET /auth/mfa. available is false until migration 0035 is applied and
    the server has MFA_ENCRYPTION_KEY."""
    available: bool
    enabled: bool
    required: bool
    required_roles: list[str]
    recovery_codes_left: int | None = None


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


class ForgotPasswordInfo(BaseModel):
    """GET /auth/forgot-password: false when the server has no email set up,
    and then `detail` says to ask an administrator instead."""
    email_enabled: bool
    detail: str | None = None


class MessageResponse(BaseModel):
    detail: str
