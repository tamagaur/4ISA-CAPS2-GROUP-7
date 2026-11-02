"""
backend.notifications - the notification bell's rows (migration 0071, user_notification), 2026-10-28.

Written by the request and decision endpoints, in their own transaction, just before they commit:
    a staff member asks (quantity change, dismissal)  -> one row for every admin except the requester
    an admin approves or rejects it                    -> one row for the requester
Read and marked read by backend/routers/notifications.py, each user their own rows only.

A notification is a pointer to a request, never the request: reading one sets read_at and nothing else, so the
unread count and the pending count are separate numbers. The summary is built from the request's own fields (SKU,
quantities), never from free text. Until migration 0071 is applied, `ready()` is false and every write here is a
no-op, so requests and decisions behave exactly as before.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload

KINDS = (
    "quantity_change_requested", "dismissal_requested",
    "quantity_change_approved", "quantity_change_rejected",
    "dismissal_approved", "dismissal_rejected",
)

READY_SQL = "SELECT to_regclass('user_notification') IS NOT NULL AS ready"

# Every admin but the actor (nobody settles their own request, so it is not news to them).
_TO_ADMINS_SQL = """
    INSERT INTO user_notification (recipient_user_id, kind, quantity_change_key, dismissal_request_key,
                                   actor_email, summary)
    SELECT u.user_id, :kind, :change_key, :request_key, :actor, :summary
    FROM users u
    WHERE u.role = 'admin' AND lower(u.email) <> lower(:actor)
    ON CONFLICT DO NOTHING
"""

# The requester, found by the email the request row keeps.
_TO_REQUESTER_SQL = """
    INSERT INTO user_notification (recipient_user_id, kind, quantity_change_key, dismissal_request_key,
                                   actor_email, summary)
    SELECT u.user_id, :kind, :change_key, :request_key, :actor, :summary
    FROM users u
    WHERE lower(u.email) = lower(:requester) AND lower(u.email) <> lower(:actor)
    ON CONFLICT DO NOTHING
"""


def ready(db: Session) -> bool:
    """Whether migration 0071's table exists (to_regclass never raises). No answer counts as not ready."""
    row = db.execute(text(READY_SQL)).mappings().first()
    return bool(row and row.get("ready"))


def _pcs(value) -> str:
    return f"{round(float(value)):,d} pcs" if value is not None else "—"


def _keys(change_key: int | None, request_key: int | None) -> dict:
    return {"change_key": change_key, "request_key": request_key}


def request_made(db: Session, *, kind: str, actor: TokenPayload, sku: str, recommended=None, proposed=None,
                 change_key: int | None = None, request_key: int | None = None) -> None:
    """A staff request was saved: tell every admin. Call inside the request's transaction, before commit."""
    if not ready(db):
        return
    if kind == "quantity_change_requested":
        summary = f"SKU {sku}: quantity {_pcs(recommended)} -> {_pcs(proposed)}"
    else:
        summary = f"SKU {sku}: dismiss the order of {_pcs(recommended)}"
    db.execute(text(_TO_ADMINS_SQL), {"kind": kind, **_keys(change_key, request_key),
                                      "actor": actor.email, "summary": summary})


def request_decided(db: Session, *, kind: str, admin: TokenPayload, requester: str, sku: str,
                    recommended=None, proposed=None,
                    change_key: int | None = None, request_key: int | None = None) -> None:
    """An admin approved or rejected a request: tell the requester. Call inside the decision's transaction."""
    if not ready(db) or not requester:
        return
    verdict = "approved" if kind.endswith("_approved") else "rejected"
    if kind.startswith("quantity_change"):
        summary = f"SKU {sku}: quantity change {_pcs(recommended)} -> {_pcs(proposed)} {verdict}"
    else:
        summary = f"SKU {sku}: dismissal request {verdict}"
    db.execute(text(_TO_REQUESTER_SQL), {"kind": kind, **_keys(change_key, request_key),
                                         "actor": admin.email, "requester": requester, "summary": summary})
