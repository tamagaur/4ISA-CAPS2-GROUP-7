"""backend.schemas.audit_log — Pydantic models for GET /audit-log. Entries
are written by the server itself (backend/audit.py); there is no POST."""
from __future__ import annotations

import datetime

from pydantic import BaseModel


class AuditLogEntry(BaseModel):
    audit_log_key: int
    user_email: str
    user_name: str | None = None
    role: str | None = None
    action: str
    details: str | None = None
    created_at: datetime.datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogEntry]
    count: int


class AuditUserSummary(BaseModel):
    """One user's row on the Audit Log page (GET /audit-log/users)."""
    user_email: str
    user_name: str | None = None
    role: str | None = None
    login_count: int
    # Sign-ins with a measured length. Lower than login_count when some
    # sign-ins predate session tracking (backfilled from audit_log).
    timed_session_count: int
    # None when none of this user's sessions has a measured length yet.
    longest_session_seconds: float | None = None
    longest_session_started_at: datetime.datetime | None = None
    last_login_at: datetime.datetime | None = None


class AuditUserSummaryResponse(BaseModel):
    items: list[AuditUserSummary]
    count: int
