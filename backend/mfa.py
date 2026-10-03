"""
backend.mfa — two-step sign-in with an authenticator app (Google
Authenticator, Microsoft Authenticator, ...): the TOTP standard, RFC 6238.

HOW IT WORKS
------------
Setup: the server makes a random secret, the person scans it into their app
as a QR code (provisioning_uri), and types one code to prove the app has it.
Only then is two-step sign-in on for the account (enabled_at), and they get
RECOVERY_CODE_COUNT one-time recovery codes for when the phone is lost.

Sign-in: password first (backend/routers/auth.py), then the 6-digit code the
app shows, or one recovery code. A code is accepted for the 30-second step
it belongs to and one step either side (a phone clock ~30 s off still
works), and never twice (last_used_step).

Wrong codes count toward the same lockout as wrong passwords
(backend/login_limiter.py), so a stolen password doesn't buy unlimited
guesses at the code.

STORED (migration 0035, table user_mfa)
---------------------------------------
The secret is encrypted with MFA_ENCRYPTION_KEY (a Fernet key in the
server's environment), so a copy of the table alone can't produce codes.
Recovery codes are stored as sha256 hashes only; a used one is removed.

WHO MUST USE IT
---------------
MFA_REQUIRED_ROLES (comma-separated: "admin" or "admin,staff"; unset = no
one) makes the roles listed set it up at their next sign-in. Anyone else may
turn it on from their account. A required role can't turn it off; an admin
can reset it for someone who lost their phone and their recovery codes
(POST /users/{id}/mfa/reset).

BEFORE MIGRATION 0035 IS APPLIED
--------------------------------
Like backend/permissions.py: mfa_ready() looks the table up (to_regclass,
which never errors). Until it exists, sign-in is password-only exactly as
before, GET /auth/mfa says available: false, and the setup endpoints answer
503 mfa_not_ready. Once applied it switches over within a minute, with no
restart.

Without MFA_ENCRYPTION_KEY: nobody can set it up, and an account that
already has it can't sign in (503) rather than skip the code. A required
role is not enforced while the key is missing, so a missing setting can't
lock every admin out; the server logs a warning instead.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth_utils import _get_secret_key

logger = logging.getLogger(__name__)

ISSUER = "SAN2 Inventory DSS"
DIGITS = 6
STEP_SECONDS = 30
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
# No 0/o, 1/i/l: a code copied from paper is read back unambiguously.
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_RECOVERY_GROUP = 5

# How long the step between password and code may take.
PENDING_MINUTES = 5

ROLES = ("admin", "staff")

NOT_READY = ("Two-step sign-in isn't set up on this server yet "
             "(migration 0035_user_two_factor.sql isn't applied).")
NOT_CONFIGURED = "Two-step sign-in isn't available on this server right now. Ask your administrator."


class MfaUnavailable(Exception):
    """The server can't read authenticator secrets (MFA_ENCRYPTION_KEY unset
    or invalid). Routers answer 503."""


# ── Is the table there yet? ───────────────────────────────────────────────
# Cached like backend/permissions.py: True for good once seen; a False is
# re-checked after a minute, so applying 0035 needs no restart.
_READY_RECHECK_SECONDS = 60
_ready_cache = {"value": False, "checked_at": 0.0}


# PAUSED (Audrey, 2026-10-03): two-step sign-in is switched off everywhere,
# local and live, until the encryption key and recovery codes are sorted out
# on her PC. All the code, the user_mfa table and everyone's stored setup are
# kept; this only makes the app behave as it did before migration 0035:
# sign-in is password-only and Account security says it isn't available.
# To turn it back on, set this to False (and make sure MFA_ENCRYPTION_KEY is
# the same in every .env and on Render).
MFA_PAUSED = True


def mfa_ready(db: Session) -> bool:
    if MFA_PAUSED:
        return False
    if _ready_cache["value"]:
        return True
    now = time.monotonic()
    if now - _ready_cache["checked_at"] < _READY_RECHECK_SECONDS and _ready_cache["checked_at"]:
        return False
    found = db.execute(text("SELECT to_regclass('public.user_mfa') IS NOT NULL")).scalar()
    _ready_cache.update(value=bool(found), checked_at=now)
    return bool(found)


# ── Server settings ────────────────────────────────────────────────────────
def _fernet() -> Fernet:
    load_dotenv(override=False)
    key = os.environ.get("MFA_ENCRYPTION_KEY", "").strip()
    if not key:
        raise MfaUnavailable("MFA_ENCRYPTION_KEY is not set")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise MfaUnavailable("MFA_ENCRYPTION_KEY is not a valid Fernet key") from exc


def encryption_configured() -> bool:
    try:
        _fernet()
    except MfaUnavailable:
        return False
    return True


def required_roles() -> frozenset[str]:
    """The roles that must use two-step sign-in (MFA_REQUIRED_ROLES)."""
    load_dotenv(override=False)
    raw = os.environ.get("MFA_REQUIRED_ROLES", "")
    roles = {part.strip().lower() for part in raw.split(",") if part.strip()}
    unknown = roles - set(ROLES)
    if unknown:
        logger.warning("MFA_REQUIRED_ROLES names unknown roles %s; ignoring them.", sorted(unknown))
    return frozenset(roles & set(ROLES))


def is_required(role: str) -> bool:
    if role not in required_roles():
        return False
    if not encryption_configured():
        logger.warning("MFA_REQUIRED_ROLES includes %r but MFA_ENCRYPTION_KEY is missing or invalid: "
                       "not enforcing two-step sign-in.", role)
        return False
    return True


# ── TOTP (RFC 6238 over RFC 4226 HOTP, SHA-1, 6 digits, 30 s) ─────────────
# SHA-1 / 6 / 30 is what every authenticator app supports; the standard
# library covers it, so no extra dependency.
def new_secret() -> str:
    """160 random bits, base32 without padding (what the apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _secret_bytes(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_secret_bytes(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    """The time step `code` belongs to, within DRIFT_STEPS of now, or None.
    Every candidate is compared in constant time."""
    code = normalize_code(code)
    if len(code) != DIGITS or not code.isdigit():
        return None
    base = current_step(now)
    found = None
    for step in range(base - DRIFT_STEPS, base + DRIFT_STEPS + 1):
        if hmac.compare_digest(code_at(secret, step), code):
            found = step
    return found


def provisioning_uri(secret: str, email: str) -> str:
    """The otpauth:// link the QR code carries; the app shows ISSUER and the
    email as the account's name."""
    label = quote(f"{ISSUER}:{email}")
    query = urlencode({"secret": secret, "issuer": ISSUER, "algorithm": "SHA1",
                       "digits": DIGITS, "period": STEP_SECONDS}, quote_via=quote)
    return f"otpauth://totp/{label}?{query}"


def normalize_code(code: str) -> str:
    """Spaces and dashes don't count: '123 456' and 'abcde-fghjk' are fine."""
    return "".join(ch for ch in code.lower() if ch not in " -\t")


# ── Recovery codes ─────────────────────────────────────────────────────────
def new_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(2 * _RECOVERY_GROUP))
        codes.append(f"{raw[:_RECOVERY_GROUP]}-{raw[_RECOVERY_GROUP:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    # 50 random bits each, looked up by exact hash: sha256 is enough (no
    # bcrypt needed, unlike a password a person chooses).
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()


# ── The step between password and code ────────────────────────────────────
# A short-lived token naming the account whose password was right. It is
# signed with a key derived from JWT_SECRET_KEY, not JWT_SECRET_KEY itself,
# so it can never pass as a sign-in token (and a sign-in token can't pass
# as one of these).
def _pending_key() -> str:
    return hashlib.sha256(f"mfa-pending:{_get_secret_key()}".encode("utf-8")).hexdigest()


def issue_pending_token(user_id: int, step: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=PENDING_MINUTES)
    return jwt.encode({"sub": str(user_id), "step": step, "exp": expire}, _pending_key(), algorithm="HS256")


def read_pending_token(token: str, step: str) -> int | None:
    try:
        payload = jwt.decode(token, _pending_key(), algorithms=["HS256"])
    except JWTError:
        return None
    if payload.get("step") != step:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None


# ── The table ──────────────────────────────────────────────────────────────
# Every write runs in the caller's transaction; the caller commits.
def _row(db: Session, user_id: int):
    return db.execute(
        text("SELECT secret_encrypted, enabled_at, last_used_step, cardinality(recovery_hashes) AS recovery_left "
             "FROM user_mfa WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).mappings().first()


def status(db: Session, user_id: int) -> dict:
    """{'enabled': bool, 'recovery_left': int | None}; not enabled before 0035."""
    row = _row(db, user_id) if mfa_ready(db) else None
    if row is None or row["enabled_at"] is None:
        return {"enabled": False, "recovery_left": None}
    return {"enabled": True, "recovery_left": int(row["recovery_left"] or 0)}


def is_enabled(db: Session, user_id: int) -> bool:
    return status(db, user_id)["enabled"]


def enabled_user_ids(db: Session) -> set[int]:
    if not mfa_ready(db):
        return set()
    rows = db.execute(text("SELECT user_id FROM user_mfa WHERE enabled_at IS NOT NULL")).all()
    return {int(r[0]) for r in rows}


def sign_in_step(db: Session, user_id: int, role: str) -> str | None:
    """What a correct password leads to: None (signed in), 'verify' (enter a
    code) or 'setup' (this role must set it up first)."""
    if not mfa_ready(db):
        return None
    if is_enabled(db, user_id):
        if not encryption_configured():
            raise MfaUnavailable("an enabled account can't be checked without MFA_ENCRYPTION_KEY")
        return "verify"
    if is_required(role):
        return "setup"
    return None


def start_setup(db: Session, user_id: int, email: str) -> tuple[str, str] | None:
    """A fresh secret for an account that doesn't have two-step sign-in on
    yet: (secret, otpauth uri). None if it is already on. Replaces any
    earlier setup that was never confirmed."""
    secret = new_secret()
    encrypted = _fernet().encrypt(secret.encode("ascii")).decode("ascii")
    stored = db.execute(
        text("""
            INSERT INTO user_mfa (user_id, secret_encrypted)
            VALUES (:user_id, :secret_encrypted)
            ON CONFLICT (user_id) DO UPDATE
               SET secret_encrypted = EXCLUDED.secret_encrypted, last_used_step = NULL,
                   recovery_hashes = '{}', created_at = now()
             WHERE user_mfa.enabled_at IS NULL
            RETURNING user_id
        """),
        {"user_id": user_id, "secret_encrypted": encrypted},
    ).first()
    if stored is None:
        return None
    return secret, provisioning_uri(secret, email)


def _decrypt(encrypted: str) -> str:
    try:
        return _fernet().decrypt(encrypted.encode("ascii")).decode("ascii")
    except InvalidToken as exc:
        # The key was changed after this secret was stored.
        raise MfaUnavailable("a stored secret can't be decrypted with the current MFA_ENCRYPTION_KEY") from exc


def confirm_setup(db: Session, user_id: int, code: str) -> list[str] | None:
    """Turns two-step sign-in on if `code` matches the secret being set up.
    Returns the new recovery codes (shown once), or None for a wrong code or
    no setup in progress."""
    row = _row(db, user_id)
    if row is None or row["enabled_at"] is not None:
        return None
    step = matching_step(_decrypt(row["secret_encrypted"]), code)
    if step is None:
        return None
    codes = new_recovery_codes()
    done = db.execute(
        text("""
            UPDATE user_mfa SET enabled_at = now(), last_used_step = :step, recovery_hashes = :hashes
             WHERE user_id = :user_id AND enabled_at IS NULL
            RETURNING user_id
        """),
        {"user_id": user_id, "step": step, "hashes": [hash_recovery_code(c) for c in codes]},
    ).first()
    return codes if done is not None else None


def verify(db: Session, user_id: int, code: str) -> str | None:
    """Checks a sign-in code: 'app' for a code from the authenticator,
    'recovery' for a recovery code (now used up), None otherwise. An app
    code already used, or older than the last one used, is refused."""
    normalized = normalize_code(code)
    if len(normalized) == DIGITS and normalized.isdigit():
        row = _row(db, user_id)
        if row is None or row["enabled_at"] is None:
            return None
        step = matching_step(_decrypt(row["secret_encrypted"]), normalized)
        if step is None:
            return None
        claimed = db.execute(
            text("""
                UPDATE user_mfa SET last_used_step = :step
                 WHERE user_id = :user_id AND enabled_at IS NOT NULL
                   AND (last_used_step IS NULL OR last_used_step < :step)
                RETURNING user_id
            """),
            {"user_id": user_id, "step": step},
        ).first()
        return "app" if claimed is not None else None
    if not normalized:
        return None
    used = db.execute(
        text("""
            UPDATE user_mfa SET recovery_hashes = array_remove(recovery_hashes, :code_hash)
             WHERE user_id = :user_id AND enabled_at IS NOT NULL AND :code_hash = ANY(recovery_hashes)
            RETURNING user_id
        """),
        {"user_id": user_id, "code_hash": hash_recovery_code(normalized)},
    ).first()
    return "recovery" if used is not None else None


def replace_recovery_codes(db: Session, user_id: int) -> list[str]:
    """New recovery codes; every earlier one stops working."""
    codes = new_recovery_codes()
    db.execute(
        text("UPDATE user_mfa SET recovery_hashes = :hashes WHERE user_id = :user_id AND enabled_at IS NOT NULL"),
        {"user_id": user_id, "hashes": [hash_recovery_code(c) for c in codes]},
    )
    return codes


def remove(db: Session, user_id: int) -> bool:
    """Turns two-step sign-in off (deletes the row). True if it was on."""
    row = db.execute(
        text("DELETE FROM user_mfa WHERE user_id = :user_id RETURNING enabled_at"), {"user_id": user_id}
    ).first()
    return row is not None and row[0] is not None
