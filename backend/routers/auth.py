"""
backend.routers.auth — POST /auth/login, POST /auth/register.

Story #89: login with hashed credentials.

POST /auth/login is public (no Depends(get_current_user) — that would be
circular: you need a token to get a token).
POST /auth/register requires an existing admin token (Depends(get_current_user)
+ a role check) — there is deliberately no public self-registration route,
per the story's "admin-only" requirement. The very first admin account is
seeded once, outside the API (see backend/scripts/seed_admin.py), not
created through this endpoint.

SESSIONS (migration 0023, 2026-09-21): login opens a user_session row and
puts its id in the token ('sid'); POST /auth/heartbeat moves last_seen_at
while the app is open and POST /auth/logout closes it. That is what the
Audit Log page's longest-session figure is measured from. All three are
best-effort: if the table is missing or a write fails, signing in and out
still work — the session just goes unmeasured.

FAILED SIGN-INS (2026-09-21): repeated wrong passwords lock the email (5 in
15 min) or the IP address (20 in 15 min) for 15 minutes — see
backend/login_limiter.py for the rules and why they are shaped that way.
"""
from __future__ import annotations

import logging
import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.auth_utils import create_access_token, hash_password, verify_password
from backend.deps import TokenPayload, get_current_user, get_db
from backend.login_limiter import login_limiter
from backend.schemas.auth import LoginRequest, LoginResponse, RegisterRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# A session with no heartbeat for this long is over: it is closed at its last
# activity, and later activity on the same token no longer extends it. Without
# this, a tab left open overnight (tokens last 8h) would read as an 8-hour
# session. The frontend beats every 60s while the page is visible.
SESSION_IDLE_MINUTES = 30

START_SESSION_SQL = """
    INSERT INTO user_session (session_id, user_id, user_email, user_name, role, started_at, last_seen_at)
    VALUES (:session_id, :user_id, :user_email, :user_name, :role, now(), now())
"""
# Runs before every heartbeat/logout: closes the session at its last
# activity if it has been idle too long, so the statements after it match
# nothing and the idle gap is never counted.
CLOSE_IF_IDLE_SQL = """
    UPDATE user_session
       SET ended_at = last_seen_at, end_reason = 'idle'
     WHERE session_id = :session_id AND ended_at IS NULL
       AND last_seen_at < now() - make_interval(mins => :idle_minutes)
"""
HEARTBEAT_SQL = """
    UPDATE user_session SET last_seen_at = now()
     WHERE session_id = :session_id AND ended_at IS NULL
"""
LOGOUT_SQL = """
    UPDATE user_session SET last_seen_at = now(), ended_at = now(), end_reason = 'logout'
     WHERE session_id = :session_id AND ended_at IS NULL
"""


def _start_session(db: Session, *, user_id: int, email: str, full_name: str, role: str) -> str | None:
    """Opens this sign-in's user_session row and returns its id, or None if
    the write failed — a failure here must never stop anyone signing in."""
    session_id = str(uuid.uuid4())
    try:
        db.execute(
            text(START_SESSION_SQL),
            {"session_id": session_id, "user_id": user_id, "user_email": email,
             "user_name": full_name, "role": role},
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Could not open a user_session row; sign-in continues unmeasured.", exc_info=True)
        return None
    return session_id


def _touch_session(db: Session, session_id: str | None, final_sql: str) -> None:
    """Idle check, then `final_sql` (heartbeat or logout), in one commit."""
    if session_id is None:
        return
    params = {"session_id": session_id, "idle_minutes": SESSION_IDLE_MINUTES}
    try:
        db.execute(text(CLOSE_IF_IDLE_SQL), params)
        db.execute(text(final_sql), {"session_id": session_id})
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Could not update user_session %s.", session_id, exc_info=True)


def _too_many_attempts(seconds: int) -> HTTPException:
    minutes = max(1, math.ceil(seconds / 60))
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many failed sign-in attempts. Try again in {minutes} minute{'' if minutes == 1 else 's'}.",
        headers={"Retry-After": str(seconds)},
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    client_ip = request.client.host if request.client else "unknown"
    # Checked before the password so that nothing about a locked account's
    # password can be learned while the lock lasts.
    wait = login_limiter.retry_after(body.email, client_ip)
    if wait is not None:
        raise _too_many_attempts(wait)

    row = db.execute(
        text("SELECT user_id, password_hash, role, full_name FROM users WHERE email = :email"),
        {"email": body.email},
    ).mappings().first()

    # Same error for "no such user" and "wrong password" — do not reveal
    # which one it was; that would let an attacker enumerate valid emails.
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password.",
    )
    if row is None or not verify_password(body.password, row["password_hash"]):
        # Counted the same whether or not the email exists, so the lock
        # can't reveal which emails have accounts either.
        locked_for = login_limiter.record_failure(body.email, client_ip)
        if locked_for is not None:
            logger.warning("Sign-in locked for %r from %s after repeated failures.", body.email, client_ip)
            raise _too_many_attempts(locked_for)
        raise invalid_credentials
    login_limiter.record_success(body.email)

    session_id = _start_session(
        db, user_id=row["user_id"], email=body.email, full_name=row["full_name"], role=row["role"]
    )
    token = create_access_token(
        user_id=row["user_id"], email=body.email, role=row["role"], full_name=row["full_name"],
        session_id=session_id,
    )
    return LoginResponse(access_token=token, role=row["role"], full_name=row["full_name"])


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def heartbeat(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> None:
    """Marks the caller's session as still active (sent every 60s while the
    app is visible). A token without a session id is a no-op."""
    _touch_session(db, current_user.session_id, HEARTBEAT_SQL)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def logout(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> None:
    """Closes the caller's session. The token itself stays valid until it
    expires — the browser discards it; this only records when the session
    ended."""
    _touch_session(db, current_user.session_id, LOGOUT_SQL)


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> LoginResponse:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin may register new users.",
        )

    existing = db.execute(
        text("SELECT 1 FROM users WHERE email = :email"), {"email": body.email}
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    password_hash = hash_password(body.password)
    row = db.execute(
        text(
            "INSERT INTO users (email, password_hash, full_name, role) "
            "VALUES (:email, :password_hash, :full_name, :role) "
            "RETURNING user_id, role, full_name"
        ),
        {"email": body.email, "password_hash": password_hash, "full_name": body.full_name, "role": body.role},
    ).mappings().first()
    db.commit()

    token = create_access_token(
        user_id=row["user_id"], email=body.email, role=row["role"], full_name=row["full_name"]
    )
    return LoginResponse(access_token=token, role=row["role"], full_name=row["full_name"])
