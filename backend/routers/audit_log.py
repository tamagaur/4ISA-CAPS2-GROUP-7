"""
backend.routers.audit_log — GET /audit-log, GET /audit-log/users

Reads the application audit trail from Supabase. Requires
analytics/db/migrations/0003_add_audit_log.sql to have been applied.

Entries are written by the endpoints that make each change, in the same
transaction (backend/audit.py). POST /audit-log, which let the browser file
entries itself, was removed 2026-09-28: a change made by calling the API
directly left no entry, and any signed-in user could post any text.

GET /audit-log/users (2026-09-21) is what the Audit Log page shows: one row
per user — sign-in count and longest session — instead of one row per
sign-in. It reads user_session (migration 0023), not audit_log.

Reading the log (both GETs) is admin-only — staff never need it.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.schemas.audit_log import (
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
               MIN(started_at) AS first_login_at,
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
           s.last_login_at,
           s.first_login_at
    FROM users u
    FULL OUTER JOIN s ON s.user_email = u.email
    ORDER BY s.longest_session_seconds DESC NULLS LAST, COALESCE(s.login_count, 0) DESC,
             COALESCE(u.email, s.user_email)
"""


@router.get("/users", response_model=AuditUserSummaryResponse)
def get_audit_user_summary(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("audit_log.view")),
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
    # The span the sign-in counts cover (2026-10-03): a count with no period
    # read as "ever", while it only goes back to the first recorded sign-in.
    firsts = [i.first_login_at for i in items if i.first_login_at is not None]
    lasts = [i.last_login_at for i in items if i.last_login_at is not None]
    return AuditUserSummaryResponse(
        items=items,
        count=len(items),
        first_login_at=min(firsts) if firsts else None,
        last_login_at=max(lasts) if lasts else None,
    )


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
    current_user: TokenPayload = Depends(require_permission("audit_log.view")),
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

    # A failed read is a 503, not an empty list: an empty list reads as
    # "nobody has changed anything", the same trap the sign-ins summary
    # above avoids (2026-10-02).
    try:
        rows = db.execute(text(query), params).mappings().all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="The audit log couldn't be read right now. Try again in a moment.",
        ) from exc
    items = [AuditLogEntry(**dict(r)) for r in rows]
    return AuditLogListResponse(items=items, count=len(items))
