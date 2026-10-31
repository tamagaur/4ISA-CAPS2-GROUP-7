"""
backend.routers.reorder_approval - reversing a reorder decision, and holding a planner's quantity edit for an admin.
Migrations 0067 and 0068, 2026-10-23. Backend only.

TWO STATE MACHINES, ONE ROW
---------------------------
lp_recommendation.status (unchanged values; the decision itself)

    pending --accept / dismiss (PATCH)-------------> accepted | dismissed
    accepted | dismissed --POST /{key}/reverse----> pending          (admin only, the decision is kept)

lp_quantity_change.state (new; one row per proposed quantity change, never deleted)

    (planner edits the quantity, no grant)  --> pending_approval
    pending_approval --POST /changes/{k}/approve (admin)--> approved   and the row becomes accepted
    pending_approval --POST /changes/{k}/reject  (admin)--> rejected   and the row stays pending

The recommendation row is NOT changed by a proposal: status stays 'pending', q_i is untouched, decided_* stay NULL.
While a change is pending_approval nobody can decide the row directly (PATCH answers 409): the admin settles it first.
At most one change per row can be pending_approval (partial unique index, migration 0068).

WHO CAN DO WHAT
---------------
lp.decide           propose a quantity change (POST /{key}/quantity-change), accept as recommended or dismiss (PATCH)
lp.propose          (2026-10-28) propose a quantity change, ask for a dismissal and report stock counted, all held
                    for an admin (backend/routers/reorder_requests.py). No direct accept or dismiss.
a direct-apply grant (lp_direct_apply_grant, an admin gives it to one user): the same POST applies at once, as an
                    accept with that quantity (outcome 'applied'); PATCH with a different quantity is allowed too
admin               approve or reject, reverse a decision, grant or revoke direct apply. An admin's own quantity
                    change always applies at once.
A user without a grant who sends a different quantity through PATCH gets 403 approval_required.

FIELDS REUSED
-------------
recommended_q_i (the API's name for q_i), decided_q_i, decision_reason, decided_by, decided_at on lp_recommendation.
On approval: status accepted, decided_q_i = the proposed quantity, decision_reason = the planner's reason,
decided_by = the PLANNER (they made the decision), decided_at = the approval time. The approver and the note are on
the lp_quantity_change row and in the audit log. A reversal copies the decision to lp_decision_reversal first.

AUDIT LOG (who and when come from the entry; the details carry the quantities)
    Reorder Quantity Change Proposed   SKU x: quantity 384.8 -> 390 proposed (change 7), awaiting approval
    Reorder Quantity Change Approved   SKU x: quantity 384.8 -> 390 approved (change 7, proposed by a@x at ...)
    Reorder Quantity Change Rejected   SKU x: quantity 384.8 -> 390 rejected (change 7, proposed by a@x): reason
    Reorder Decision Reversed          SKU x: accepted (quantity 390, decided by a@x at ...) reversed to pending: reason
    Direct Apply Granted / Revoked     user@x
A bypass user's direct change is the existing "Reorder Recommendation Accepted" entry, ending
"[quantity decided: 390; applied directly]".

BEFORE THE MIGRATIONS ARE APPLIED
---------------------------------
Without 0068 nothing here changes how PATCH behaves (a quantity edit applies at once, as before) and the approval
endpoints answer 503 approval_not_ready. Without 0067 the reverse endpoint answers 503 reversal_not_ready.
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import audit, notifications, planning_mart, response_cache, stock_observation
from backend.api_errors import ApiError
from backend.case_pack import PACK_SQL, check_whole_cases
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.routers import recommendations as rec
from backend.schemas.recommendations import (
    ApprovalNote,
    DirectApplyGrant,
    DirectApplyGrantBody,
    DirectApplyStatus,
    QuantityChange,
    QuantityChangeList,
    QuantityChangeOutcome,
    QuantityChangeRequest,
    RecommendationItem,
    RejectRequest,
    ReverseRequest,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

STATES = ("pending_approval", "approved", "rejected")
APPROVAL_NOT_READY = "Quantity-change approval isn't set up on this server yet (migration 0068 isn't applied)."
REVERSAL_NOT_READY = "Reversing a decision isn't set up on this server yet (migration 0067 isn't applied)."

_CURRENT_CYCLE = """
    lr.planning_cycle_date = (
        SELECT MAX(l2.planning_cycle_date) FROM lp_recommendation l2
        JOIN product_dimension p2 ON p2.product_key = l2.product_key
        WHERE p2.principal = pd.principal)"""

# The row a request is about: its quantity, state, cycle and the principal's current cycle.
_ROW_SQL = """
    SELECT lr.recommendation_key, lr.q_i, lr.status, lr.planning_cycle_date, lr.product_key,
           COALESCE(pd.sku_code, pd.category_path) AS sku,
           {PACK} AS pack,
           (SELECT MAX(l2.planning_cycle_date) FROM lp_recommendation l2
            JOIN product_dimension p2 ON p2.product_key = l2.product_key
            WHERE p2.principal = pd.principal) AS current_cycle
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE lr.recommendation_key = :key
""".replace("{PACK}", PACK_SQL)

# The row's state under a lock, after the proposal is inserted (change_quantity).
_LOCK_ROW_SQL = """
    SELECT lr.status, lr.planning_cycle_date,
           (SELECT MAX(l2.planning_cycle_date) FROM lp_recommendation l2
            JOIN product_dimension p2 ON p2.product_key = l2.product_key
            WHERE p2.principal = pd.principal) AS current_cycle
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE lr.recommendation_key = :key
    FOR UPDATE OF lr
"""

_CHANGE_COLUMNS = """
    SELECT c.change_key, c.recommendation_key, COALESCE(pd.sku_code, pd.category_path) AS sku_code, pd.product_name,
           lr.planning_cycle_date, c.recommended_q_i, c.proposed_q_i, c.proposal_reason AS reason, c.reviewed,
           c.state, c.proposed_by, c.proposed_at, c.resolved_by, c.resolved_at, c.resolution_note,
           rv.reversed_by, rv.reversed_at, pu.full_name AS proposed_by_name
    FROM lp_quantity_change c
    JOIN lp_recommendation lr ON lr.recommendation_key = c.recommendation_key
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    -- The requester's name for the Staff Requests table (2026-10-28): the row keeps only the email.
    LEFT JOIN users pu ON lower(pu.email) = lower(c.proposed_by)
    -- An approved change whose decision an admin later reversed (audit 2026-10-23 finding 10): the state stays
    -- 'approved' as the record, and these two columns say the decision it made was undone.
    LEFT JOIN LATERAL (SELECT r.reversed_by, r.reversed_at FROM lp_decision_reversal r
                       WHERE r.recommendation_key = c.recommendation_key AND c.state = 'approved'
                         AND r.reversed_at >= c.resolved_at
                       ORDER BY r.reversed_at DESC LIMIT 1) rv ON true
"""
_CHANGE_BY_KEY_SQL = _CHANGE_COLUMNS + " WHERE c.change_key = :change_key"
# FOR UPDATE on both rows: a rerun of the LP (which upserts pending rows) or another decision waits for the commit.
_CHANGE_LOCKED_SQL = _CHANGE_BY_KEY_SQL + " FOR UPDATE OF c, lr"

# A proposal is inserted only for a pending row of the current cycle with a different quantity, and not when one is
# already open: ON CONFLICT DO NOTHING against the partial unique index answers None for that race.
_PROPOSE_SQL = """
    INSERT INTO lp_quantity_change (recommendation_key, recommended_q_i, proposed_q_i, proposal_reason, reviewed,
                                    proposed_by)
    SELECT lr.recommendation_key, lr.q_i, ROUND(CAST(:quantity AS numeric), 2), :reason, :reviewed, :proposed_by
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE lr.recommendation_key = :key
      AND lr.status = 'pending'
      AND""" + _CURRENT_CYCLE + """
      AND ROUND(CAST(:quantity AS numeric), 2) <> lr.q_i
    ON CONFLICT (recommendation_key) WHERE state = 'pending_approval' DO NOTHING
    RETURNING change_key
"""

_RESOLVE_SQL = """
    UPDATE lp_quantity_change
    SET state = :state, resolved_by = :resolved_by, resolved_at = :resolved_at, resolution_note = :note
    WHERE change_key = :change_key AND state = 'pending_approval'
    RETURNING change_key
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
    key (tests/backend/test_permissions.py walks them), but lp.decide and users.manage can be ticked for a staff
    account, and none of these is for staff: approving, reversing and granting are the admin's. The 403 names
    admin_required, as backend.permissions.require_admin_for does."""
    inner = require_permission(*keys)

    def dependency(current_user: TokenPayload = Depends(inner)) -> TokenPayload:
        if current_user.role != "admin":
            raise ApiError(403, "Only an admin can do this.", code="admin_required")
        return current_user

    return dependency


require_lp_admin = _admin_only("lp.decide")
require_grant_admin = _admin_only("users.manage")


def _fmt(value) -> str:
    return f"{float(value):g}"


def _stamp(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if hasattr(value, "strftime") else str(value)


def _require_approval(present: dict) -> None:
    if not present.get("approval"):
        raise ApiError(503, APPROVAL_NOT_READY, code="approval_not_ready")


def _change(db: Session, change_key: int, present: dict | None = None) -> QuantityChange:
    row = db.execute(text(_CHANGE_BY_KEY_SQL), {"change_key": change_key}).mappings().first()
    change = QuantityChange(**dict(row))
    if present and present.get("requests"):
        change.stock_observation = stock_observation.latest_for(db, "quantity_change_key", [change_key]).get(change_key)
    return change


def cases_text(pieces, pack) -> str:
    """' (13 cases of 30)' for a whole-case quantity with a pack size, else ''. For the audit entries, so the log
    states the same case count the page shows."""
    if pack is None or float(pack) <= 1:
        return ""
    cases = float(pieces) / float(pack)
    return f" ({cases:g} cases of {float(pack):g})" if abs(cases - round(cases)) < 1e-6 else ""


def refuse_self_approval(row, approver: TokenPayload, requester_column: str) -> None:
    """An admin never settles their own request (an admin's own change applies at once, so this only meets an
    account that was staff when it asked). 409 self_approval."""
    if (row[requester_column] or "").lower() == (approver.email or "").lower():
        raise ApiError(409, "You made this request, so another admin has to approve or reject it.", code="self_approval")


# ── propose, or apply directly ─────────────────────────────────────────────────────────────────────────────
@router.post("/{recommendation_key}/quantity-change", response_model=QuantityChangeOutcome)
def change_quantity(
    recommendation_key: int,
    body: QuantityChangeRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("lp.decide", "lp.propose")),
) -> QuantityChangeOutcome:
    """Edit the recommended quantity. Held for an admin (HTTP 202, outcome 'held') unless the caller is an admin or
    has a direct-apply grant, in which case it applies at once as an accept with this quantity (HTTP 200, outcome
    'applied'). The recommendation is not changed by a held proposal."""
    present = rec._present(db)
    _require_approval(present)
    row = db.execute(text(_ROW_SQL), {"key": recommendation_key}).mappings().first()
    if row is None or row["status"] != "pending" or row["planning_cycle_date"] != row["current_cycle"]:
        raise rec.refusal_for(None if row is None else {
            "status": row["status"], "planning_cycle_date": row["planning_cycle_date"],
            "current_cycle": row["current_cycle"]})
    quantity = round(float(body.quantity), 2)
    recommended = round(float(row["q_i"]), 2)
    if quantity == recommended:
        raise ApiError(400, "That is the recommended quantity. Accept the recommendation as it is instead.",
                       code="quantity_unchanged", recommended_q_i=recommended)
    check_whole_cases(quantity, row["pack"], recommended)
    reason = body.reason.strip()
    flagged = rec._review_reasons(db, recommendation_key) if present["review_flag"] else None
    if flagged is not None and not body.reviewed:
        raise HTTPException(status_code=409, detail=(
            "This product is flagged for review before ordering (" + ", ".join(flagged) + "). "
            "Change it from its own row after checking it."
        ))

    direct = rec.may_apply_directly(db, current_user)
    if body.stock_observation is not None:
        # A count travels with a request an admin reads. Validated (unit, pack size, whole cases) before anything
        # is written.
        if direct:
            raise ApiError(400, "A stock count goes with a change sent for approval. Yours applies at once, so "
                                "record the count with a dismissal or leave it out.", code="observation_needs_request")
        if not present.get("requests"):
            raise ApiError(503, rec.REQUESTS_NOT_READY, code="requests_not_ready")
        stock_observation.to_pieces(body.stock_observation.quantity, body.stock_observation.unit, row["pack"])

    if direct:
        decided = rec.decide_row(db, present, key=recommendation_key, status="accepted", reason=reason,
                                 decided_quantity=quantity, decided_by=current_user.email)
        audit.record(
            db, "Reorder Recommendation Accepted",
            f"SKU {decided['sku']}" + (f": {reason}" if reason else "")
            + f" [quantity decided: {_fmt(quantity)}{cases_text(quantity, row['pack'])}; applied directly, "
              f"recommended {_fmt(recommended)}]"
            + (f" [flagged for review: {', '.join(flagged)}; reviewed]" if flagged else ""),
            actor=current_user,
        )
        db.commit()
        response_cache.invalidate()
        return QuantityChangeOutcome(
            outcome="applied", item=rec.item_for(db, present, recommendation_key, decided["planning_cycle_date"]))

    created = db.execute(text(_PROPOSE_SQL), {
        "key": recommendation_key, "quantity": quantity, "reason": reason, "reviewed": bool(flagged),
        "proposed_by": current_user.email,
    }).mappings().first()
    if created is None:
        open_change = db.execute(text(rec._OPEN_CHANGE_SQL), {"key": recommendation_key}).mappings().first()
        db.rollback()
        raise rec.refusal_for({"status": "pending", "planning_cycle_date": row["planning_cycle_date"],
                               "current_cycle": row["current_cycle"]}, open_change)
    # The row is locked and re-read AFTER the insert (audit 2026-10-23, the race with an admin's accept). The insert
    # above read `status = 'pending'` without a lock; an accept that committed since (or commits while this waits for
    # the lock) must not leave an open change on a decided row. Lock order is the change, then the row, the same
    # as approve_change, and decide_row takes the row lock first and nothing else, so no cycle is possible.
    after = db.execute(text(_LOCK_ROW_SQL), {"key": recommendation_key}).mappings().first()
    if after is None or after["status"] != "pending" or after["planning_cycle_date"] != after["current_cycle"]:
        db.rollback()
        raise rec.refusal_for(None if after is None else dict(after))
    # A dismissal request open on the row (migration 0070) is read AFTER the lock too: one waiting request per row,
    # whichever kind. reorder_requests.request_dismissal takes the same lock and checks this table the other way.
    if present.get("requests"):
        open_dismissal = db.execute(text(rec._OPEN_DISMISSAL_SQL), {"key": recommendation_key}).mappings().first()
        if open_dismissal is not None:
            db.rollback()
            raise rec.refusal_for(dict(after), None, open_dismissal)
    audit.record(
        db, "Reorder Quantity Change Proposed",
        f"SKU {row['sku']}: quantity {_fmt(recommended)} -> {_fmt(quantity)}{cases_text(quantity, row['pack'])} "
        f"proposed (change {created['change_key']}), awaiting approval: {reason}",
        actor=current_user,
    )
    # The bell (migration 0071): every admin is told, in this same transaction.
    notifications.request_made(db, kind="quantity_change_requested", actor=current_user, sku=row["sku"],
                               recommended=recommended, proposed=quantity, change_key=created["change_key"])
    if body.stock_observation is not None:
        stock_observation.record(db, body.stock_observation, product_key=row["product_key"],
                                 recommendation_key=recommendation_key, pack=row["pack"], context="quantity_change",
                                 actor=current_user, sku=row["sku"], change_key=created["change_key"])
    change = _change(db, created["change_key"], present)
    db.commit()
    response_cache.invalidate()
    response.status_code = 202
    return QuantityChangeOutcome(outcome="held", change=change)


# ── the admin's queue ──────────────────────────────────────────────────────────────────────────────────────
@router.get("/changes", response_model=QuantityChangeList)
def list_changes(
    state: str = Query("pending_approval", description="pending_approval | approved | rejected | all"),
    recommendation_key: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("lp.decide", "lp.propose")),
) -> QuantityChangeList:
    """An admin sees every change. Anyone else sees only the ones they proposed. Newest first."""
    present = rec._present(db)
    _require_approval(present)
    if state != "all" and state not in STATES:
        raise HTTPException(status_code=400, detail="state must be one of pending_approval, approved, rejected, all")
    where, params = [], {}
    if state != "all":
        where.append("c.state = :state")
        params["state"] = state
    if recommendation_key is not None:
        where.append("c.recommendation_key = :recommendation_key")
        params["recommendation_key"] = recommendation_key
    if current_user.role != "admin":
        where.append("c.proposed_by = :me")
        params["me"] = current_user.email
    sql = _CHANGE_COLUMNS + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY c.proposed_at DESC, c.change_key DESC"
    rows = db.execute(text(sql), params).mappings().all()
    items = [QuantityChange(**dict(r)) for r in rows]
    if present.get("requests"):
        counts = stock_observation.latest_for(db, "quantity_change_key", [c.change_key for c in items])
        for c in items:
            c.stock_observation = counts.get(c.change_key)
    return QuantityChangeList(count=len(items), items=items)


def _locked_pending_change(db: Session, change_key: int):
    row = db.execute(text(_CHANGE_LOCKED_SQL), {"change_key": change_key}).mappings().first()
    if row is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Quantity change not found")
    if row["state"] != "pending_approval":
        db.rollback()
        raise HTTPException(status_code=409, detail=(
            f"This change was already {row['state']} by {row['resolved_by']}; it is decided once."))
    return row


@router.post("/changes/{change_key}/approve", response_model=QuantityChange)
def approve_change(
    change_key: int,
    body: ApprovalNote | None = None,
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_lp_admin),
) -> QuantityChange:
    """Apply a held change: the recommendation becomes accepted with the proposed quantity (decided_by is the
    planner who proposed it). Refused (409) when the recommendation has been decided, superseded by a newer LP run,
    or its q_i has moved since the change was proposed."""
    present = rec._present(db)
    _require_approval(present)
    change = _locked_pending_change(db, change_key)
    try:
        refuse_self_approval(change, admin, "proposed_by")
    except ApiError:
        db.rollback()
        raise
    current = db.execute(text(_ROW_SQL), {"key": change["recommendation_key"]}).mappings().first()
    if current["planning_cycle_date"] != current["current_cycle"]:
        # Audit 2026-10-23 finding 9: the row's cycle has been superseded, so the change can never be applied. Close it
        # (rejected, with the reason) and commit, instead of rolling back and leaving it in the queue for ever.
        note = (f"Closed automatically: the {current['planning_cycle_date']} cycle was superseded by the "
                f"{current['current_cycle']} LP run, so this change can no longer be applied.")
        closed = db.execute(text(_RESOLVE_SQL), {
            "state": "rejected", "resolved_by": admin.email, "resolved_at": datetime.datetime.utcnow(), "note": note,
            "change_key": change_key,
        }).mappings().first()
        if closed is not None:
            audit.record(db, "Reorder Quantity Change Closed",
                         f"SKU {current['sku']}: quantity change {change_key} closed, {note}", actor=admin)
            db.commit()
        else:
            db.rollback()
        raise HTTPException(status_code=409, detail=(
            f"This recommendation belongs to the {current['planning_cycle_date']} cycle, which a newer LP run "
            f"({current['current_cycle']}) has superseded, so the change cannot be approved. It has been closed."))
    if round(float(current["q_i"]), 2) != round(float(change["recommended_q_i"]), 2):
        db.rollback()
        raise ApiError(409, (f"The recommendation changed after this was proposed (it was "
                             f"{_fmt(change['recommended_q_i'])}, it is now {_fmt(current['q_i'])}). Reject this "
                             "change and have it proposed again."), code="recommendation_changed",
                       recommended_q_i=float(current["q_i"]))
    try:  # a proposal held before the case-pack check existed is refused here too
        check_whole_cases(change["proposed_q_i"], current["pack"], current["q_i"])
    except ApiError:
        db.rollback()
        raise
    note = ((body.note if body else None) or "").strip() or None
    now = datetime.datetime.utcnow()
    resolved = db.execute(text(_RESOLVE_SQL), {
        "state": "approved", "resolved_by": admin.email, "resolved_at": now, "note": note, "change_key": change_key,
    }).mappings().first()
    if resolved is None:  # lost a race with another admin
        db.rollback()
        raise HTTPException(status_code=409, detail="This change was just decided by someone else.")
    # The accept itself. The change is already 'approved' in this transaction, so the open-change guard lets it
    # through. A refusal rolls everything back, the change included.
    decided = rec.decide_row(db, present, key=change["recommendation_key"], status="accepted",
                             reason=change["reason"], decided_quantity=float(change["proposed_q_i"]),
                             decided_by=change["proposed_by"], decided_at=now)
    audit.record(
        db, "Reorder Quantity Change Approved",
        f"SKU {decided['sku']}: quantity {_fmt(change['recommended_q_i'])} -> {_fmt(change['proposed_q_i'])}"
        f"{cases_text(change['proposed_q_i'], current['pack'])} approved "
        f"(change {change_key}, proposed by {change['proposed_by']} at {_stamp(change['proposed_at'])})"
        + (f": {note}" if note else ""),
        actor=admin,
    )
    notifications.request_decided(db, kind="quantity_change_approved", admin=admin, requester=change["proposed_by"],
                                  sku=decided["sku"], recommended=change["recommended_q_i"],
                                  proposed=change["proposed_q_i"], change_key=change_key)
    db.commit()
    response_cache.invalidate()
    return _change(db, change_key, present)


@router.post("/changes/{change_key}/reject", response_model=QuantityChange)
def reject_change(
    change_key: int,
    body: RejectRequest,
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_lp_admin),
) -> QuantityChange:
    """Turn a held change down. The recommendation stays pending and untouched, the change stays as the record."""
    _require_approval(rec._present(db))
    change = _locked_pending_change(db, change_key)
    try:
        refuse_self_approval(change, admin, "proposed_by")
    except ApiError:
        db.rollback()
        raise
    note = body.reason.strip()
    resolved = db.execute(text(_RESOLVE_SQL), {
        "state": "rejected", "resolved_by": admin.email, "resolved_at": datetime.datetime.utcnow(), "note": note,
        "change_key": change_key,
    }).mappings().first()
    if resolved is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="This change was just decided by someone else.")
    audit.record(
        db, "Reorder Quantity Change Rejected",
        f"SKU {change['sku_code']}: quantity {_fmt(change['recommended_q_i'])} -> {_fmt(change['proposed_q_i'])} "
        f"rejected (change {change_key}, proposed by {change['proposed_by']} at {_stamp(change['proposed_at'])}): {note}",
        actor=admin,
    )
    notifications.request_decided(db, kind="quantity_change_rejected", admin=admin, requester=change["proposed_by"],
                                  sku=change["sku_code"], recommended=change["recommended_q_i"],
                                  proposed=change["proposed_q_i"], change_key=change_key)
    db.commit()
    response_cache.invalidate()
    return _change(db, change_key)


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


# ── who may apply directly ─────────────────────────────────────────────────────────────────────────────────
@router.get("/direct-apply-grants/me", response_model=DirectApplyStatus)
def my_direct_apply(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("lp.decide", "lp.propose")),
) -> DirectApplyStatus:
    """Whether the caller's quantity changes apply at once, so the page can say 'will be sent for approval'."""
    ready = bool(rec._present(db).get("approval"))
    if current_user.role == "admin":
        return DirectApplyStatus(can_apply_directly=True, reason="admin", approval_ready=ready)
    granted = ready and rec.may_apply_directly(db, current_user)
    return DirectApplyStatus(can_apply_directly=granted, reason="granted" if granted else "not_granted",
                             approval_ready=ready)


@router.get("/direct-apply-grants", response_model=list[DirectApplyGrant])
def list_direct_apply_grants(
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_grant_admin),
) -> list[DirectApplyGrant]:
    _require_approval(rec._present(db))
    rows = db.execute(text("""
        SELECT g.user_id, u.email, u.full_name, g.granted_by, g.granted_at
        FROM lp_direct_apply_grant g LEFT JOIN users u ON u.user_id = g.user_id
        ORDER BY g.granted_at DESC, g.user_id
    """)).mappings().all()
    return [DirectApplyGrant(**dict(r)) for r in rows]


@router.put("/direct-apply-grants/{user_id}", response_model=DirectApplyStatus)
def set_direct_apply_grant(
    user_id: int,
    body: DirectApplyGrantBody,
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_grant_admin),
) -> DirectApplyStatus:
    """Allow (granted true) or stop allowing (false) one user to apply reorder quantity changes with no approval.
    Audited. An open proposal of a user whose grant is removed stays open for an admin to settle."""
    _require_approval(rec._present(db))
    target = db.execute(text("SELECT user_id, email, role FROM users WHERE user_id = :uid"), {"uid": user_id}).mappings().first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.granted:
        db.execute(text("""
            INSERT INTO lp_direct_apply_grant (user_id, granted_by) VALUES (:uid, :by)
            ON CONFLICT (user_id) DO NOTHING
        """), {"uid": user_id, "by": admin.email})
    else:
        db.execute(text("DELETE FROM lp_direct_apply_grant WHERE user_id = :uid"), {"uid": user_id})
    audit.record(db, "Direct Apply Granted" if body.granted else "Direct Apply Revoked", target["email"], actor=admin)
    db.commit()
    response_cache.invalidate()
    return DirectApplyStatus(can_apply_directly=body.granted or target["role"] == "admin",
                             reason="admin" if target["role"] == "admin" else ("granted" if body.granted else "not_granted"),
                             approval_ready=True)
