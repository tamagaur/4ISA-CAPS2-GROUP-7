"""
backend.audit — the server writes the audit trail itself.

Until 2026-09-28 the browser posted each entry after the action it described
(frontend/src/utils/auditLogger.js -> POST /audit-log). A change made by
calling the API directly left no entry, and any signed-in user could post any
text under their own name. Now the endpoint that makes a change records it in
the same transaction: no change without its entry, and no entry without the
change. POST /audit-log is gone.

Actions: Add User, Edit User, Delete User, Invite Resent, Reset Link Sent,
Change Access (a user's role and permission boxes, PUT
/admin/users/{id}/permissions), Password Reset Requested, Password Set,
Password Reset, Sign-in Locked, Sign-in Failed, Sign-in Failure Logging
Paused, Add SKU, Edit SKU, Reorder Recommendation Accepted / Dismissed,
Two-Step Sign-In On / Off / Reset, Recovery Codes Replaced, Recovery Code
Used, Device Remembered, Two-Step Code Skipped (backend/mfa.py).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth_utils import TokenPayload

INSERT_SQL = """
    INSERT INTO audit_log (user_email, user_name, role, action, details)
    VALUES (:user_email, :user_name, :role, :action, :details)
"""


def record(
    db: Session,
    action: str,
    details: str | None = None,
    *,
    actor: TokenPayload | None = None,
    email: str | None = None,
    name: str | None = None,
    role: str | None = None,
) -> None:
    """Adds one entry in the caller's transaction (the caller commits).
    `actor` is the signed-in user who acted. Without one — a password set
    through an emailed link, a sign-in lockout — pass the account's
    email/name/role instead."""
    if actor is not None:
        email, name, role = actor.email, actor.full_name or None, actor.role
    db.execute(
        text(INSERT_SQL),
        {"user_email": email, "user_name": name, "role": role, "action": action, "details": details},
    )
