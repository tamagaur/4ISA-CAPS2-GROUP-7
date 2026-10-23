"""
backend.routers.reorder_approval - reversing a reorder decision (migration 0067, 2026-10-23). Backend only.

    accepted | dismissed --POST /{key}/reverse----> pending          (admin only, the decision is kept)

The decision it undoes is copied to lp_decision_reversal first (status, quantity decided, reason, who decided and
when), next to who reversed it, when and why, and the row is reset to the pending shape. Nothing is deleted. Admin
only, a reason is required, and only a row of its principal's current cycle (an older cycle's decision is history).
Audited as "Reorder Decision Reversed". Until 0067 is applied the endpoint answers 503 reversal_not_ready.
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import audit, planning_mart, response_cache
from backend.api_errors import ApiError
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.routers import recommendations as rec
from backend.schemas.recommendations import RecommendationItem, ReverseRequest

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

REVERSAL_NOT_READY = "Reversing a decision isn't set up on this server yet (migration 0067 isn't applied)."

_CURRENT_CYCLE = """
    lr.planning_cycle_date = (
        SELECT MAX(l2.planning_cycle_date) FROM lp_recommendation l2
        JOIN product_dimension p2 ON p2.product_key = l2.product_key
        WHERE p2.principal = pd.principal)"""

# The row a request is about: its quantity, state, cycle and the principal's current cycle.
_ROW_SQL = """
    SELECT lr.recommendation_key, lr.q_i, lr.status, lr.planning_cycle_date,
           COALESCE(pd.sku_code, pd.category_path) AS sku,
           (SELECT MAX(l2.planning_cycle_date) FROM lp_recommendation l2
            JOIN product_dimension p2 ON p2.product_key = l2.product_key
            WHERE p2.principal = pd.principal) AS current_cycle
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE lr.recommendation_key = :key
"""

# The decision to reverse, locked, only when it is a decision and the row is in the current cycle.
_REVERSAL_ROW_SQL = """
    SELECT lr.recommendation_key, lr.q_i, lr.status, lr.decided_at, lr.decided_by{decision_columns},
           COALESCE(pd.sku_code, pd.category_path) AS sku, lr.planning_cycle_date
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE lr.recommendation_key = :key
      AND lr.status IN ('accepted', 'dismissed')
      AND""" + _CURRENT_CYCLE + """
    FOR UPDATE OF lr
"""
_REVERSAL_COLUMNS = ", lr.decided_q_i, lr.decision_reason"
_REVERSAL_COLUMNS_ABSENT = ", NULL::numeric AS decided_q_i, NULL::text AS decision_reason"

_LOG_REVERSAL_SQL = """
    INSERT INTO lp_decision_reversal (recommendation_key, prior_status, prior_decided_q_i, prior_reason,
                                      prior_decided_by, prior_decided_at, q_i, reversed_by, reversed_at,
                                      reversal_reason)
    VALUES (:key, :prior_status, :prior_decided_q_i, :prior_reason, :prior_decided_by, :prior_decided_at, :q_i,
            :reversed_by, :reversed_at, :reason)
"""
# Back to the pending shape ck_lp_decision_shape allows. q_i, rop_i and ss_i are not in the SET list.
_RESET_SQL = """
    UPDATE lp_recommendation
    SET status = 'pending', decided_at = NULL, decided_by = NULL{decision_columns}
    WHERE recommendation_key = :key AND status IN ('accepted', 'dismissed')
"""
_RESET_COLUMNS = ", decided_q_i = NULL, decision_reason = NULL"


def _admin_only(*keys: str):
    """require_permission(*keys), and then the caller must also be an ADMIN. Every route here declares a catalog
    key (tests/backend/test_permissions.py walks them), but lp.decide can be ticked for a staff
    account, and reversing is the admin's. The 403 names
    admin_required, as backend.permissions.require_admin_for does."""
    inner = require_permission(*keys)

    def dependency(current_user: TokenPayload = Depends(inner)) -> TokenPayload:
        if current_user.role != "admin":
            raise ApiError(403, "Only an admin can do this.", code="admin_required")
        return current_user

    return dependency


require_lp_admin = _admin_only("lp.decide")


def _fmt(value) -> str:
    return f"{float(value):g}"


def _stamp(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if hasattr(value, "strftime") else str(value)


# ── reversing a decision ───────────────────────────────────────────────────────────────────────────────────
@router.post("/{recommendation_key}/reverse", response_model=RecommendationItem)
def reverse_decision(
    recommendation_key: int,
    body: ReverseRequest,
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_lp_admin),
) -> RecommendationItem:
    """Return an accepted or dismissed recommendation to pending. Admin only, reason required, current cycle only
    (an older cycle's decision is history, not an open plan). The decision is copied to lp_decision_reversal
    before the row is reset, and the reversal is audited with who, when and why."""
    present = rec._present(db)
    if not present.get("reversal"):
        raise ApiError(503, REVERSAL_NOT_READY, code="reversal_not_ready")
    columns = _REVERSAL_COLUMNS if present["decision_cols"] else _REVERSAL_COLUMNS_ABSENT
    prior = db.execute(text(_REVERSAL_ROW_SQL.format(decision_columns=columns)), {"key": recommendation_key}).mappings().first()
    if prior is None:
        why = db.execute(text(_ROW_SQL), {"key": recommendation_key}).mappings().first()
        db.rollback()
        if why is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if why["status"] == "pending":
            raise HTTPException(status_code=409, detail="This recommendation is still pending; there is no decision to reverse.")
        raise HTTPException(status_code=409, detail=(
            f"This decision belongs to the {why['planning_cycle_date']} cycle, which a newer LP run "
            f"({why['current_cycle']}) has superseded, so it is history and is not reversed."))
    reason = body.reason.strip()
    now = datetime.datetime.utcnow()
    db.execute(text(_LOG_REVERSAL_SQL), {
        "key": recommendation_key, "prior_status": prior["status"], "prior_decided_q_i": prior["decided_q_i"],
        "prior_reason": prior["decision_reason"], "prior_decided_by": prior["decided_by"],
        "prior_decided_at": prior["decided_at"], "q_i": prior["q_i"], "reversed_by": admin.email,
        "reversed_at": now, "reason": reason,
    })
    db.execute(text(_RESET_SQL.format(decision_columns=_RESET_COLUMNS if present["decision_cols"] else "")),
               {"key": recommendation_key})
    planning_mart.undecide(db, recommendation_key)
    quantity = f", quantity {_fmt(prior['decided_q_i'])}" if prior["decided_q_i"] is not None else ""
    audit.record(
        db, "Reorder Decision Reversed",
        f"SKU {prior['sku']}: {prior['status']} (decided by {prior['decided_by']} at {_stamp(prior['decided_at'])}"
        f"{quantity}) reversed to pending: {reason}",
        actor=admin,
    )
    db.commit()
    response_cache.invalidate()
    return rec.item_for(db, present, recommendation_key, prior["planning_cycle_date"])


