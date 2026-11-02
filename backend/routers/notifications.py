"""
backend.routers.notifications - the signed-in user's notification bell (migration 0071), 2026-10-28.

    GET  /notifications                 the newest notifications (limit, default 30), and the unread count
    POST /notifications/{key}/read      mark one read
    POST /notifications/read-all        mark every unread one read

Every route reads and writes the caller's OWN rows only (recipient_user_id = the token's user_id): a key that
belongs to someone else answers 404, as if it did not exist. Marking read sets read_at and nothing else; the
request it points to keeps its state on its own row (the bell's unread count and the Staff Requests tab's pending
count are separate numbers). Rows are written by backend/notifications.py inside the request and decision
transactions. Until migration 0071 is applied, GET answers ready=false with no items and the POSTs answer 503.
There is no live push in this app: the frontend asks again on a timer and when the window regains focus.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import notifications
from backend.api_errors import ApiError
from backend.deps import TokenPayload, get_current_user, get_db
from backend.schemas.recommendations import Notification, NotificationList, NotificationReadResult

router = APIRouter(prefix="/notifications", tags=["notifications"])

NOT_READY = "Notifications are not set up on this server yet (migration 0071)."

# The request each row points to, for its product and its CURRENT state (read, never written, here).
_LIST_SQL = """
    SELECT n.notification_key, n.kind,
           CASE WHEN n.quantity_change_key IS NOT NULL THEN 'quantity_change' ELSE 'dismissal' END AS request_kind,
           COALESCE(n.quantity_change_key, n.dismissal_request_key) AS request_key,
           COALESCE(c.recommendation_key, d.recommendation_key) AS recommendation_key,
           COALESCE(pd.sku_code, pd.category_path) AS sku_code, pd.product_name,
           n.actor_email, au.full_name AS actor_name, n.summary, n.created_at, n.read_at,
           COALESCE(c.state, d.state) AS request_state
    FROM user_notification n
    LEFT JOIN lp_quantity_change c ON c.change_key = n.quantity_change_key
    LEFT JOIN lp_dismissal_request d ON d.request_key = n.dismissal_request_key
    LEFT JOIN lp_recommendation lr ON lr.recommendation_key = COALESCE(c.recommendation_key, d.recommendation_key)
    LEFT JOIN product_dimension pd ON pd.product_key = lr.product_key
    LEFT JOIN users au ON lower(au.email) = lower(n.actor_email)
    WHERE n.recipient_user_id = :me
    ORDER BY n.created_at DESC, n.notification_key DESC
    LIMIT :limit
"""
_UNREAD_SQL = "SELECT COUNT(*) AS n FROM user_notification WHERE recipient_user_id = :me AND read_at IS NULL"
_OWN_SQL = "SELECT read_at FROM user_notification WHERE notification_key = :key AND recipient_user_id = :me"
_READ_ONE_SQL = """
    UPDATE user_notification SET read_at = now()
    WHERE notification_key = :key AND recipient_user_id = :me AND read_at IS NULL
    RETURNING notification_key
"""
_READ_ALL_SQL = """
    UPDATE user_notification SET read_at = now()
    WHERE recipient_user_id = :me AND read_at IS NULL
    RETURNING notification_key
"""


def _unread(db: Session, me: int) -> int:
    row = db.execute(text(_UNREAD_SQL), {"me": me}).mappings().first()
    return int(row["n"]) if row else 0


def _require_ready(db: Session) -> None:
    if not notifications.ready(db):
        raise ApiError(503, NOT_READY, code="notifications_not_ready")


@router.get("", response_model=NotificationList)
def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> NotificationList:
    """The caller's newest notifications and how many are unread. Not set up: ready=false, nothing listed."""
    if not notifications.ready(db):
        return NotificationList(ready=False)
    rows = db.execute(text(_LIST_SQL), {"me": current_user.user_id, "limit": limit}).mappings().all()
    return NotificationList(ready=True, unread_count=_unread(db, current_user.user_id),
                            items=[Notification(**dict(r)) for r in rows])


@router.post("/read-all", response_model=NotificationReadResult)
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> NotificationReadResult:
    _require_ready(db)
    updated = len(db.execute(text(_READ_ALL_SQL), {"me": current_user.user_id}).mappings().all())
    db.commit()
    return NotificationReadResult(updated=updated, unread_count=_unread(db, current_user.user_id))


@router.post("/{notification_key}/read", response_model=NotificationReadResult)
def mark_read(
    notification_key: int,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> NotificationReadResult:
    """Mark one of the caller's notifications read. Someone else's key answers 404. Already read: updated=0."""
    _require_ready(db)
    me = current_user.user_id
    if db.execute(text(_OWN_SQL), {"key": notification_key, "me": me}).mappings().first() is None:
        raise ApiError(404, "Notification not found.", code="notification_not_found")
    updated = len(db.execute(text(_READ_ONE_SQL), {"key": notification_key, "me": me}).mappings().all())
    db.commit()
    return NotificationReadResult(updated=updated, unread_count=_unread(db, me))
