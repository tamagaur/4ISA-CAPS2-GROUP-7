"""
backend.schemas.auth — Pydantic models for POST /auth/login and /auth/register.

Story #89: login with hashed credentials.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: Literal["admin", "staff"] = "staff"
