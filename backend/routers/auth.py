"""
backend.routers.auth — sign-in, sessions, invites and password links.

  POST /auth/login            public  email + password -> JWT
  POST /auth/heartbeat        user    keeps the session alive
  POST /auth/logout           user    ends the session
  POST /auth/register         admin   creates an account and its invite link
  GET  /auth/forgot-password  public  whether a reset link can be emailed at all
  POST /auth/forgot-password  public  emails a reset link if the account exists
  POST /auth/link-info        public  who a set-password link is for
  POST /auth/set-password     public  sets the password through a link

Story #89: login with hashed credentials. There is deliberately no public
self-registration; the very first admin is seeded outside the API (see
backend/scripts/seed_admin.py).

SESSIONS (migration 0023, 2026-09-21): login opens a user_session row and
puts its id in the token ('sid'); heartbeat moves last_seen_at while the app
is open and logout closes it. That is what the Audit Log page's
longest-session figure is measured from. Since 2026-09-28 every request
checks that row (backend/deps.py), so a sign-in whose session can't be
recorded is refused (503) instead of let through unmeasured: a token without
a session could never be signed out.

INVITES AND RESETS (2026-09-28, migration 0031): an admin no longer types a
password for a new account. The account starts without one and its owner
sets it through a one-time link (backend/account_links.py), so no admin knows
anyone's password.

FAILED SIGN-INS (2026-09-21): repeated wrong passwords lock the email (5 in
15 min) or the IP address (20 in 15 min) for 15 minutes — see
backend/login_limiter.py for the rules and why they are shaped that way.
Each lock is also written to the audit log, naming the limit that tripped
(per-email or per-IP, 2026-09-30). So is every failed sign-in (2026-09-30):
"Sign-in Failed" with the IP and the sha256 of the lower-cased email, never
the email as typed and never the password, at most
MAX_LOGGED_FAILURES_PER_WINDOW per 15 minutes so a flood can't fill the table.
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend import account_links, audit, mailer
from backend.auth_utils import (
    create_access_token,
    hash_password,
    spend_password_check_time,
    verify_password,
)
from backend.deps import TokenPayload, get_current_user, get_db, require_admin
from backend.login_limiter import (
    MAX_FAILURES_PER_EMAIL,
    MAX_FAILURES_PER_IP,
    WINDOW_SECONDS,
    Lock,
    failure_log_budget,
    login_limiter,
    reset_limiter,
)
from backend.schemas.auth import (
    ForgotPasswordInfo,
    ForgotPasswordRequest,
    InviteResponse,
    LinkInfo,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    RegisterRequest,
    SetPasswordRequest,
    TokenRequest,
)
from backend.schemas.users import UserOut
from backend.sessions import CLOSE_IF_IDLE_SQL, SESSION_IDLE_MINUTES, revoke_user_sessions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

START_SESSION_SQL = """
    INSERT INTO user_session (session_id, user_id, user_email, user_name, role, started_at, last_seen_at)
    VALUES (:session_id, :user_id, :user_email, :user_name, :role, now(), now())
"""
HEARTBEAT_SQL = """
    UPDATE user_session SET last_seen_at = now()
     WHERE session_id = :session_id AND ended_at IS NULL
"""
LOGOUT_SQL = """
    UPDATE user_session SET last_seen_at = now(), ended_at = now(), end_reason = 'logout'
     WHERE session_id = :session_id AND ended_at IS NULL
"""

# The same answer whether or not the email has an account.
FORGOT_PASSWORD_MESSAGE = (
    "If that email has an account, we've sent it a link to set a new password. "
    "The link works once and expires in 30 minutes."
)
# forgot-password answers no sooner than this, so the database work done only
# for real accounts can't be timed to tell which emails exist.
FORGOT_PASSWORD_MIN_SECONDS = 1.0
# Said instead when the server has no email set up, as on the live API: no
# link could reach anyone, so none is made, and every email gets this answer.
FORGOT_PASSWORD_NO_EMAIL_MESSAGE = (
    "Email isn't set up on this server, so we can't send you a reset link. "
    "Ask an administrator to send you one from User Management."
)


def _start_session(db: Session, *, user_id: int, email: str, full_name: str, role: str) -> str | None:
    """Opens this sign-in's user_session row and returns its id, or None if
    the write failed (the caller refuses the sign-in)."""
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
        logger.warning("Could not open a user_session row; refusing the sign-in.", exc_info=True)
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


_LIMITS = {
    "email": ("per-email", MAX_FAILURES_PER_EMAIL),
    "ip": ("per-IP", MAX_FAILURES_PER_IP),
}


def _lockout_details(email: str, client_ip: str, lock: Lock) -> str:
    """What was locked and which limit did it, e.g. '203.0.113.9 locked for 15
    minutes: per-IP limit (20 failed sign-ins within 15 minutes). Last
    attempt: a@x.com from 203.0.113.9'. Before 2026-09-30 every lock read as
    the email's, even when the per-IP limit tripped."""
    minutes = max(1, math.ceil(lock.seconds / 60))
    window = WINDOW_SECONDS // 60
    locked = " and ".join({"email": email, "ip": client_ip}[rule] for rule in lock.limits)
    why = " and ".join(
        f"{label} limit ({count} failed sign-ins within {window} minutes)"
        for label, count in (_LIMITS[rule] for rule in lock.limits)
    )
    return f"{locked} locked for {minutes} minutes: {why}. Last attempt: {email} from {client_ip}"


def _record_lockout(db: Session, email: str, client_ip: str, lock: Lock) -> None:
    """Puts the lock in the audit log. A failure to write it must not turn
    the 429 into a 500."""
    try:
        audit.record(db, "Sign-in Locked", _lockout_details(email, client_ip, lock), email=email)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Could not write the sign-in lock to audit_log.", exc_info=True)


def _email_digest(email: str) -> str:
    """How a failed sign-in names its email: sha256 of the address trimmed
    and lower-cased, the same normalisation as the limiter's key. Repeated
    tries on one account group together, without the log keeping every
    address someone typed."""
    return "sha256:" + hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def _record_failed_sign_in(db: Session, email: str, client_ip: str) -> None:
    """One audit entry per wrong email or password, within failure_log_budget
    (see backend/login_limiter.py). Never the password. A failure to write it
    must not turn the 401 into a 500."""
    decision = failure_log_budget.take()
    if decision == "skip":
        return
    if decision == "log":
        action, who, details = "Sign-in Failed", _email_digest(email), f"Wrong email or password from {client_ip}"
    else:
        action, who = "Sign-in Failure Logging Paused", "system"
        details = (
            f"{failure_log_budget.limit} failed sign-ins logged in this "
            f"{WINDOW_SECONDS // 60}-minute window; later ones still count toward "
            f"locks but are not logged until it ends"
        )
    try:
        audit.record(db, action, details, email=who)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Could not write a failed sign-in to audit_log.", exc_info=True)


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

    # Same error for "no such user", "invite not accepted yet" and "wrong
    # password" — do not reveal which one it was; that would let an attacker
    # enumerate valid emails.
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password.",
    )
    if row is None or row["password_hash"] is None:
        # Still pay for one bcrypt check, so this answer takes as long as a
        # wrong password; skipping it made unknown emails answer ~0.2s faster.
        spend_password_check_time(body.password)
        password_ok = False
    else:
        password_ok = verify_password(body.password, row["password_hash"])
    if not password_ok:
        # Counted the same whether or not the email exists, so the lock
        # can't reveal which emails have accounts either.
        lock = login_limiter.record_failure(body.email, client_ip)
        _record_failed_sign_in(db, body.email, client_ip)
        if lock is not None:
            logger.warning(
                "Sign-in locked (%s limit) for %r from %s after repeated failures.",
                "+".join(lock.limits), body.email, client_ip,
            )
            _record_lockout(db, body.email, client_ip, lock)
            raise _too_many_attempts(lock.seconds)
        raise invalid_credentials
    login_limiter.record_success(body.email)

    session_id = _start_session(
        db, user_id=row["user_id"], email=body.email, full_name=row["full_name"], role=row["role"]
    )
    if session_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Signing in isn't available right now. Please try again in a minute.",
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
    app is visible)."""
    _touch_session(db, current_user.session_id, HEARTBEAT_SQL)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def logout(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> None:
    """Closes the caller's session. The browser discards the token too, but
    closing the session is what makes the server refuse it from now on."""
    _touch_session(db, current_user.session_id, LOGOUT_SQL)


@router.post("/register", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_admin),
) -> InviteResponse:
    existing = db.execute(
        text("SELECT 1 FROM users WHERE email = :email"), {"email": body.email}
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    # No password: the account stays "invite pending" until its owner sets one.
    row = db.execute(
        text(
            "INSERT INTO users (email, password_hash, full_name, role) "
            "VALUES (:email, NULL, :full_name, :role) "
            "RETURNING user_id, email, full_name, role, created_at"
        ),
        {"email": body.email, "full_name": body.full_name, "role": body.role},
    ).mappings().first()
    token, expires_at = account_links.issue(
        db, user_id=row["user_id"], purpose="invite", minutes=account_links.INVITE_MINUTES,
        created_by=current_user.user_id,
    )
    audit.record(db, "Add User", f"Invited {row['email']} as {row['role']}", actor=current_user)
    db.commit()

    # Sent after the commit: an email that fails must not undo the account.
    # The admin gets the link to pass on instead.
    problem = account_links.send_link_email(
        purpose="invite", email=row["email"], full_name=row["full_name"], token=token,
        minutes=account_links.INVITE_MINUTES,
    )
    return InviteResponse(
        user=UserOut(**dict(row), status="invited"),
        email_sent=problem is None,
        setup_link=account_links.link_url(token) if problem else None,
        expires_at=expires_at,
        email_problem=problem,
    )


@router.get("/forgot-password", response_model=ForgotPasswordInfo)
def forgot_password_info() -> ForgotPasswordInfo:
    """Whether "Forgot password?" can email a link, so the page can say to ask
    an administrator up front instead of promising an email that can't come."""
    if mailer.is_configured():
        return ForgotPasswordInfo(email_enabled=True)
    return ForgotPasswordInfo(email_enabled=False, detail=FORGOT_PASSWORD_NO_EMAIL_MESSAGE)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED, response_model=MessageResponse)
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MessageResponse:
    if not mailer.is_configured():
        # The same answer for every email, with no database work to time.
        return MessageResponse(detail=FORGOT_PASSWORD_NO_EMAIL_MESSAGE)
    started = time.monotonic()
    client_ip = request.client.host if request.client else "unknown"
    if reset_limiter.retry_after(body.email, client_ip) is None:
        reset_limiter.record_failure(body.email, client_ip)  # counts requests, see login_limiter.py
        row = db.execute(
            text("SELECT user_id, email, full_name, role FROM users WHERE email = :email"),
            {"email": body.email},
        ).mappings().first()
        if row is not None:
            token, _ = account_links.issue(
                db, user_id=row["user_id"], purpose="reset", minutes=account_links.SELF_RESET_MINUTES
            )
            audit.record(
                db, "Password Reset Requested", None,
                email=row["email"], name=row["full_name"], role=row["role"],
            )
            db.commit()
            # Sent after the response, so the SMTP round trip can't be timed either.
            background.add_task(
                account_links.send_link_email, purpose="reset", email=row["email"],
                full_name=row["full_name"], token=token, minutes=account_links.SELF_RESET_MINUTES,
            )
    remaining = FORGOT_PASSWORD_MIN_SECONDS - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)
    return MessageResponse(detail=FORGOT_PASSWORD_MESSAGE)


@router.post("/link-info", response_model=LinkInfo)
def link_info(body: TokenRequest, db: Session = Depends(get_db)) -> LinkInfo:
    """Who a set-password link is for, so the page can greet them. A POST
    body rather than a GET path keeps the token out of access logs."""
    row = account_links.peek(db, body.token)
    if row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=account_links.LINK_INVALID)
    return LinkInfo(**dict(row))


@router.post("/set-password", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def set_password(body: SetPasswordRequest, db: Session = Depends(get_db)) -> None:
    claimed = account_links.claim(db, body.token)
    if claimed is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=account_links.LINK_INVALID)
    user = db.execute(
        text(
            "UPDATE users SET password_hash = :password_hash WHERE user_id = :user_id "
            "RETURNING email, full_name, role"
        ),
        {"password_hash": hash_password(body.password), "user_id": claimed["user_id"]},
    ).mappings().first()
    # Any other link still open for the account dies with this one, and
    # sessions signed in with the old password end.
    account_links.retire_all(db, claimed["user_id"])
    revoke_user_sessions(db, claimed["user_id"])
    audit.record(
        db, "Password Set" if claimed["purpose"] == "invite" else "Password Reset", None,
        email=user["email"], name=user["full_name"], role=user["role"],
    )
    db.commit()
