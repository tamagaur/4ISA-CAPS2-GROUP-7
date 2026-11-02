"""
backend.account_links — one-time links for setting a password: an invite
for a new account, or a password reset.

Admins used to type each new user's password, so an admin knew everyone's
password and it travelled over chat. Since 2026-09-28 an account starts
without one (users.password_hash NULL, shown as "invite pending") and the
person sets their own through a link — emailed from the group Gmail
(backend/mailer.py), or copied by the admin when email isn't available.

A link is 32 random bytes. Only its sha256 is stored (auth_token, migration
0031), so reading the table doesn't give anyone a usable link. A link works
once: using it, or issuing a newer one for the same account, retires it. It
travels in the URL fragment (/set-password#token=...), which browsers never
send to a server, so it can't land in an access log.
"""
from __future__ import annotations

import datetime
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import email_templates, mailer
from backend.auth_utils import hash_link_token, new_link_token

logger = logging.getLogger(__name__)

INVITE_MINUTES = 48 * 60
# An admin-sent reset can sit in an inbox for a while; a self-service one was
# asked for by someone waiting at the sign-in page.
ADMIN_RESET_MINUTES = 24 * 60
SELF_RESET_MINUTES = 30

LINK_INVALID = "This link has expired or has already been used."

RETIRE_SQL = """
    UPDATE auth_token SET used_at = now()
     WHERE user_id = :user_id AND used_at IS NULL
"""
ISSUE_SQL = """
    INSERT INTO auth_token (token_hash, user_id, purpose, expires_at, created_by)
    VALUES (:token_hash, :user_id, :purpose, now() + make_interval(mins => :minutes), :created_by)
    RETURNING expires_at
"""
PEEK_SQL = """
    SELECT t.purpose, t.expires_at, u.email, u.full_name
      FROM auth_token t JOIN users u ON u.user_id = t.user_id
     WHERE t.token_hash = :token_hash AND t.used_at IS NULL AND t.expires_at > now()
"""
# The account's password now, read before the link is used up, so a refused
# new password (the same as the current one) leaves the link working.
CURRENT_HASH_SQL = """
    SELECT u.password_hash
      FROM auth_token t JOIN users u ON u.user_id = t.user_id
     WHERE t.token_hash = :token_hash AND t.used_at IS NULL AND t.expires_at > now()
"""
# Marks the link used and returns it in one statement, so two requests
# carrying the same link can't both succeed.
CLAIM_SQL = """
    UPDATE auth_token SET used_at = now()
     WHERE token_hash = :token_hash AND used_at IS NULL AND expires_at > now()
    RETURNING user_id, purpose
"""


def issue(
    db: Session, *, user_id: int, purpose: str, minutes: int, created_by: int | None = None
) -> tuple[str, datetime.datetime]:
    """Retires the account's open links and creates a new one, in the
    caller's transaction. Returns (token, expires_at); the token exists only
    in this return value and the link built from it."""
    db.execute(text(RETIRE_SQL), {"user_id": user_id})
    token, token_hash = new_link_token()
    row = db.execute(
        text(ISSUE_SQL),
        {"token_hash": token_hash, "user_id": user_id, "purpose": purpose,
         "minutes": minutes, "created_by": created_by},
    ).mappings().first()
    return token, row["expires_at"]


def peek(db: Session, token: str):
    """The open link's purpose/expiry and account, or None. Uses nothing up."""
    return db.execute(text(PEEK_SQL), {"token_hash": hash_link_token(token)}).mappings().first()


def current_password_hash(db: Session, token: str) -> str | None:
    """The password hash of the account an open link is for: None for an
    invite (no password yet) or a dead link. Uses nothing up."""
    row = db.execute(text(CURRENT_HASH_SQL), {"token_hash": hash_link_token(token)}).mappings().first()
    return row["password_hash"] if row else None


def claim(db: Session, token: str):
    """Uses the link up and returns its user_id/purpose, or None when it is
    unknown, used or expired."""
    return db.execute(text(CLAIM_SQL), {"token_hash": hash_link_token(token)}).mappings().first()


def retire_all(db: Session, user_id: int) -> None:
    db.execute(text(RETIRE_SQL), {"user_id": user_id})


def link_url(token: str) -> str:
    """Raises mailer.FrontendUrlMissing in production when FRONTEND_URL is unset."""
    return mailer.app_link(f"/set-password#token={token}")


def link_url_or_none(token: str) -> str | None:
    """The link for the admin to pass on, or None when none can be built
    (the response then carries email_problem saying why)."""
    try:
        return link_url(token)
    except mailer.FrontendUrlMissing:
        return None


def _valid_for(minutes: int) -> str:
    return f"{minutes // 60} hours" if minutes >= 120 and minutes % 60 == 0 else f"{minutes} minutes"


def send_link_email(
    *, purpose: str, email: str, full_name: str, token: str, minutes: int,
    expires_at: datetime.datetime | None = None, invited_by: str | None = None, role: str | None = None,
) -> str | None:
    """Emails the link, as a designed HTML email with the same words in plain
    text (backend/email_templates.py). An invite names who sent it, the role
    and the exact expiry, so the person can tell it's genuine. Returns None
    when it was sent, otherwise the reason it wasn't — shown to the admin,
    who then gets the link to pass on."""
    valid = _valid_for(minutes)
    try:
        # All three on FRONTEND_URL: the link, the sign-in page and the hosted
        # hero illustration (frontend/public/email/warehouse.png).
        link = link_url(token)
        sign_in_url = mailer.app_link("/login")
        hero_url = mailer.app_link(email_templates.HERO_IMAGE_PATH)
    except mailer.FrontendUrlMissing as exc:
        logger.warning("Email to %s not sent: %s", email, exc)
        return str(exc)
    if purpose == "invite":
        from backend import mfa  # imports this module's neighbours; kept local

        subject, body, html = email_templates.invite_email(
            full_name=full_name, email=email, link=link, valid=valid, sign_in_url=sign_in_url,
            expires_at=expires_at, invited_by=invited_by, role=role,
            two_step_required=bool(role) and mfa.is_required(role), hero_url=hero_url,
        )
    else:
        subject, body, html = email_templates.reset_email(
            full_name=full_name, email=email, link=link, valid=valid, expires_at=expires_at, hero_url=hero_url,
        )
    try:
        mailer.send(email, subject, body, html=html,
                    inline_images=email_templates.inline_images_for(html) or None)
    except mailer.MailError as exc:
        return str(exc)
    return None
