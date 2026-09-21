"""
backend.auth_utils — password hashing and JWT helpers for Story #89.

Kept separate from backend/routers/auth.py so backend/deps.py (which needs
decode_access_token, not the router) doesn't import a router module, and so
these functions are unit-testable without spinning up FastAPI.

JWT_SECRET_KEY must be set in the environment (.env) — there is no default,
so a misconfigured deployment fails loudly at first use instead of signing
tokens with a guessable fallback secret.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from jose import JWTError, jwt
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_DEFAULT_ALGORITHM = "HS256"
_DEFAULT_EXPIRY_HOURS = 8


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain_password, password_hash)


def _get_secret_key() -> str:
    load_dotenv(override=False)
    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set on the server. Set it in .env before "
            "starting the API — refusing to sign or verify tokens with an "
            "unset secret."
        )
    return secret


def _get_algorithm() -> str:
    load_dotenv(override=False)
    return os.environ.get("JWT_ALGORITHM", _DEFAULT_ALGORITHM)


def _get_expiry_hours() -> float:
    load_dotenv(override=False)
    return float(os.environ.get("JWT_EXPIRY_HOURS", _DEFAULT_EXPIRY_HOURS))


def create_access_token(
    *, user_id: int, email: str, role: str, full_name: str, session_id: str | None = None
) -> str:
    """Encodes a JWT carrying user_id (sub), email, role, and full_name,
    expiring after JWT_EXPIRY_HOURS (default 8) — Story #91: sessions must
    expire so an unattended machine isn't an open door. full_name is display
    data only (e.g. the Sidebar's signed-in-as line), never used for
    authorization decisions.

    session_id (claim 'sid') names the user_session row this sign-in opened
    (backend/routers/auth.py), so heartbeats and sign-out update that row.
    Omitted when session tracking is unavailable."""
    expire = datetime.now(timezone.utc) + timedelta(hours=_get_expiry_hours())
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "full_name": full_name,
        "exp": expire,
    }
    if session_id is not None:
        payload["sid"] = session_id
    return jwt.encode(payload, _get_secret_key(), algorithm=_get_algorithm())


class TokenPayload:
    __slots__ = ("user_id", "email", "role", "full_name", "session_id")

    def __init__(
        self, user_id: int, email: str, role: str, full_name: str, session_id: str | None = None
    ) -> None:
        self.user_id = user_id
        self.email = email
        self.role = role
        self.full_name = full_name
        self.session_id = session_id


def decode_access_token(token: str) -> TokenPayload:
    """Decodes and validates a JWT, raising JWTError (caught by the caller)
    on any invalid signature, malformed token, or expiry."""
    payload = jwt.decode(token, _get_secret_key(), algorithms=[_get_algorithm()])
    return TokenPayload(
        user_id=int(payload["sub"]),
        email=payload["email"],
        role=payload["role"],
        # .get(), not [] — tokens issued before full_name existed shouldn't
        # fail to decode; they just display a blank name until re-login.
        full_name=payload.get("full_name", ""),
        # Tokens issued before session tracking (or when it failed) carry no
        # sid; their heartbeats are simply no-ops.
        session_id=payload.get("sid"),
    )


__all__ = [
    "JWTError",
    "TokenPayload",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "verify_password",
]
