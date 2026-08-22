"""
backend.routers.audit_log — GET/POST /audit-log

Persists the application audit trail to Supabase, replacing the previous
localStorage-only implementation (frontend/src/utils/auditLogger.js), which
never left the reporting browser. Requires
analytics/db/migrations/0003_add_audit_log.sql to have been applied.

user_email/user_name/role are taken from the caller's JWT, never from the
request body — an audit log entry can't be filed under a different user's
name than whoever is actually authenticated.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.schemas.audit_log import AuditLogCreate, AuditLogEntry, AuditLogListResponse

router = APIRouter(prefix="/audit-log", tags=["audit-log"])


@router.get("", response_model=AuditLogListResponse)
def get_audit_log(
    action: str | None = Query(None, description="Filter to an exact action string. Omit for all."),
    user_email: str | None = Query(None, description="Filter to an exact user email. Omit for all."),
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> AuditLogListResponse:
    query = "SELECT * FROM Audit_Log WHERE 1=1"
    params: dict = {}
    if action:
        query += " AND action = :action"
        params["action"] = action
    if user_email:
        query += " AND user_email = :user_email"
        params["user_email"] = user_email
    query += " ORDER BY created_at DESC LIMIT :limit"
    params["limit"] = limit

    rows = db.execute(text(query), params).mappings().all()
    items = [AuditLogEntry(**dict(r)) for r in rows]
    return AuditLogListResponse(items=items, count=len(items))


@router.post("", response_model=AuditLogEntry, status_code=201)
def create_audit_log_entry(
    payload: AuditLogCreate,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> AuditLogEntry:
    row = db.execute(
        text("""
            INSERT INTO Audit_Log (user_email, user_name, role, action, details)
            VALUES (:user_email, :user_name, :role, :action, :details)
            RETURNING *
        """),
        {
            "user_email": current_user.email,
            "user_name": current_user.full_name or None,
            "role": current_user.role,
            "action": payload.action,
            "details": payload.details,
        },
    ).mappings().first()
    db.commit()
    return AuditLogEntry(**dict(row))
