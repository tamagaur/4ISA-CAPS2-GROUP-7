"""backend.schemas.audit_log — Pydantic models for GET/POST /audit-log."""
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


class AuditLogCreate(BaseModel):
    action: str
    details: str | None = None
