"""
backend.routers.audit_log — GET/POST /audit-log

Persists the application audit trail to Supabase, replacing the previous
localStorage-only implementation (frontend/src/utils/auditLogger.js), which
never left the reporting browser. Requires
analytics/db/migrations/0003_add_audit_log.sql to have been applied.

user_email/user_name/role are taken from the caller's JWT, never from the
request body — an audit log entry can't be filed under a different user's
name than whoever is actually authenticated.

GET /audit-log/users (2026-09-21) is what the Audit Log page shows: one row
per user — sign-in count and longest session — instead of one row per
sign-in. It reads user_session (migration 0023), not audit_log.

Reading the log (both GETs) is admin-only — staff never need it. POST stays
open to any signed-in user so the app can record what they do.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db, require_admin
from backend.schemas.audit_log import (
    AuditLogCreate,
    AuditLogEntry,
    AuditLogListResponse,
    AuditUserSummary,
    AuditUserSummaryResponse,
)

router = APIRouter(prefix="/audit-log", tags=["audit-log"])

# FULL OUTER JOIN so the page lists every account — one that has never
# signed in shows 0 — and still keeps the history of an account since
# deleted. Name and role come from users when the account still exists,
# else from its most recent sign-in. Longest session first.
USER_SUMMARY_SQL = """
    WITH s AS (
        SELECT user_email,
               COUNT(*) AS login_count,
               COUNT(COALESCE(ended_at, last_seen_at)) AS timed_session_count,
               MAX(EXTRACT(EPOCH FROM COALESCE(ended_at, last_seen_at) - started_at)) AS longest_session_seconds,
               (ARRAY_AGG(started_at ORDER BY COALESCE(ended_at, last_seen_at) - started_at DESC NULLS LAST))[1]
                   AS longest_session_started_at,
               MAX(started_at) AS last_login_at,
               (ARRAY_AGG(user_name ORDER BY started_at DESC))[1] AS user_name,
               (ARRAY_AGG(role ORDER BY started_at DESC))[1] AS role
        FROM user_session
        GROUP BY user_email
    )
    SELECT COALESCE(u.email, s.user_email) AS user_email,
           COALESCE(u.full_name, s.user_name) AS user_name,
           COALESCE(u.role, s.role) AS role,
           COALESCE(s.login_count, 0) AS login_count,
           COALESCE(s.timed_session_count, 0) AS timed_session_count,
           s.longest_session_seconds,
           CASE WHEN s.longest_session_seconds IS NOT NULL THEN s.longest_session_started_at END
               AS longest_session_started_at,
           s.last_login_at
    FROM users u
    FULL OUTER JOIN s ON s.user_email = u.email
    ORDER BY s.longest_session_seconds DESC NULLS LAST, COALESCE(s.login_count, 0) DESC,
             COALESCE(u.email, s.user_email)
"""


@router.get("/users", response_model=AuditUserSummaryResponse)
def get_audit_user_summary(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_admin),
) -> AuditUserSummaryResponse:
    try:
        rows = db.execute(text(USER_SUMMARY_SQL)).mappings().all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Session history is not available — migration 0023 (user_session) has not been applied.",
        ) from exc
    items = [AuditUserSummary(**dict(r)) for r in rows]
    return AuditUserSummaryResponse(items=items, count=len(items))


@router.get("", response_model=AuditLogListResponse)
def get_audit_log(
    action: str | None = Query(None, description="Filter to an exact action string. Omit for all."),
    exclude_action: list[str] | None = Query(
        None,
        description="Leave out these exact actions; repeatable. The Audit Log page's Recent changes "
        "list passes Login and Logout, which the per-user summary already covers.",
    ),
    user_email: str | None = Query(None, description="Filter to an exact user email. Omit for all."),
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_admin),
) -> AuditLogListResponse:
    query = "SELECT * FROM audit_log WHERE 1=1"
    params: dict = {}
    if action:
        query += " AND action = :action"
        params["action"] = action
    if exclude_action:
        query += " AND action <> ALL(:exclude_action)"
        params["exclude_action"] = exclude_action
    if user_email:
        query += " AND user_email = :user_email"
        params["user_email"] = user_email
    query += " ORDER BY created_at DESC LIMIT :limit"
    params["limit"] = limit

    try:
        rows = db.execute(text(query), params).mappings().all()
        items = [AuditLogEntry(**dict(r)) for r in rows]
    except Exception:
        db.rollback()
        items = []
    return AuditLogListResponse(items=items, count=len(items))


@router.post("", response_model=AuditLogEntry, status_code=201)
def create_audit_log_entry(
    payload: AuditLogCreate,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> AuditLogEntry:
    try:
        row = db.execute(
            text("""
                INSERT INTO audit_log (user_email, user_name, role, action, details)
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
    except Exception:
        db.rollback()
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Audit log table not available.")
