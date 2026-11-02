"""Refuse to start on a weak or malformed secret (data governance G8, docs/DATA_GOVERNANCE.md).

Two checks, both run from the lifespan in backend/main.py before the database check. A message names the variable and
the rule, never the value.

  JWT_SECRET_KEY      at least JWT_MIN_LENGTH characters when APP_ENV is production. Local development is not checked.
  MFA_ENCRYPTION_KEY  must parse as a Fernet key whenever it is set, or whenever MFA_ENABLED is true. Unset with MFA
                      off (the local default) is fine.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet
from dotenv import load_dotenv

JWT_MIN_LENGTH = 32
_ON = ("1", "true", "yes", "on")


class StartupConfigError(RuntimeError):
    """A secret is missing or unfit; the server must not start."""


def validate_secrets() -> None:
    load_dotenv(override=False)
    production = os.environ.get("APP_ENV", "").strip().lower() == "production"
    if production and len(os.environ.get("JWT_SECRET_KEY", "")) < JWT_MIN_LENGTH:
        raise StartupConfigError(
            f"JWT_SECRET_KEY must be at least {JWT_MIN_LENGTH} characters when APP_ENV is production; refusing to start.")

    key = os.environ.get("MFA_ENCRYPTION_KEY", "").strip()
    mfa_on = os.environ.get("MFA_ENABLED", "").strip().lower() in _ON
    if key or mfa_on:
        try:
            Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            raise StartupConfigError(
                "MFA_ENCRYPTION_KEY must be a valid Fernet key (32 url-safe base64-encoded bytes) when it is set or "
                "MFA_ENABLED is true; refusing to start.") from None
