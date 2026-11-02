"""
backend.routers.reorder_requests - a staff member asks for a dismissal, reports stock counted, and everyone can see
what is waiting and what happened to a recommendation. Migration 0070, 2026-10-28.

Quantity changes are backend/routers/reorder_approval.py (migration 0068). This module adds the dismissal side of
the same flow and the read-only views the Reorder page needs.

THE DISMISSAL REQUEST
---------------------
lp_dismissal_request.state (one row per request, never deleted)

    (staff with lp.propose asks, with a reason)        --> pending_approval
    pending_approval --POST /dismissal-requests/{k}/approve (admin)--> approved   the row becomes dismissed
    pending_approval --POST /dismissal-requests/{k}/reject  (admin)--> rejected   the row stays pending, active

The recommendation is NOT changed by a request: status stays 'pending', q_i is untouched. While a request is open
nobody decides the row directly (recommendations.decide_row's guard), and no quantity change can be proposed on it
(reorder_approval.change_quantity checks under the row lock), and the other way round here. Approval is the ordinary
dismiss through recommendations.decide_row: status dismissed, decision_reason = the requester's reason,
decided_by = the requester, decided_at = the approval time. Refused when the row was decided meanwhile, when its
cycle was superseded (the request is then closed as rejected, as 0068 does), when q_i moved since the request
(409 recommendation_changed), or when the approver made the request (409 self_approval).

STOCK COUNTS
------------
backend/stock_observation.py. An observation only: Inventory_Fact stays the stock on hand and nothing in the plan
reads lp_stock_observation. An admin may mark one verified or rejected, which records the check and nothing else.

AUDIT LOG
    Reorder Dismissal Requested         SKU x: dismissal requested (request 4), recommended 390: reason
    Reorder Dismissal Request Approved  SKU x: dismissed on request 4 (requested by a@x at ...), recommended 390
    Reorder Dismissal Request Rejected  SKU x: request 4 rejected, the recommendation stays active: reason
    Reorder Dismissal Request Closed    the cycle was superseded
    Stock Count Reported / Verified / Rejected
A direct dismissal stays the existing "Reorder Recommendation Dismissed", so the two are told apart in the log.
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import audit, notifications, response_cache, stock_observation
from backend.api_errors import ApiError
from backend.case_pack import PACK_SQL
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.routers import recommendations as rec
from backend.routers.reorder_approval import (
    STATES, _CHANGE_COLUMNS, _CURRENT_CYCLE, _fmt, _stamp, refuse_self_approval, require_lp_admin,
)
from backend.schemas.recommendations import (
    ApprovalNote,
    DismissalRequest,
    DismissalRequestIn,
    DismissalRequestList,
    HistoryEvent,
    OpenRequest,
    OpenRequestList,
    QuantityChange,
    RecommendationHistory,
    RejectRequest,
    StockObservation,
    StockObservationList,
    VerifyObservationBody,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

PROPOSE_KEYS = ("lp.decide", "lp.propose")

# The row a request is about, LOCKED: its state, cycle, quantity, product and pack size.
_LOCK_ROW_SQL = """
    SELECT lr.recommendation_key, lr.q_i, lr.status, lr.planning_cycle_date, lr.product_key,
           COALESCE(pd.sku_code, pd.category_path) AS sku, {PACK} AS pack,
           (SELECT MAX(l2.planning_cycle_date) FROM lp_recommendation l2
            JOIN product_dimension p2 ON p2.product_key = l2.product_key
            WHERE p2.principal = pd.principal) AS current_cycle
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE lr.recommendation_key = :key
    FOR UPDATE OF lr
""".replace("{PACK}", PACK_SQL)
_ROW_SQL = _LOCK_ROW_SQL.replace("FOR UPDATE OF lr", "")

_INSERT_REQUEST_SQL = """
    INSERT INTO lp_dismissal_request (recommendation_key, recommended_q_i, request_reason, requested_by)
    SELECT lr.recommendation_key, lr.q_i, :reason, :requested_by
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE lr.recommendation_key = :key AND lr.status = 'pending' AND""" + _CURRENT_CYCLE + """
    ON CONFLICT (recommendation_key) WHERE state = 'pending_approval' DO NOTHING
    RETURNING request_key
"""

_REQUEST_COLUMNS = """
    SELECT d.request_key, d.recommendation_key, COALESCE(pd.sku_code, pd.category_path) AS sku_code, pd.product_name,
           lr.planning_cycle_date, d.recommended_q_i, d.request_reason AS reason, d.state, d.requested_by,
           d.requested_at, d.resolved_by, d.resolved_at, d.resolution_note, rv.reversed_by, rv.reversed_at,
           ru.full_name AS requested_by_name
    FROM lp_dismissal_request d
    JOIN lp_recommendation lr ON lr.recommendation_key = d.recommendation_key
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    -- The requester's name for the Staff Requests table (2026-10-28): the row keeps only the email.
    LEFT JOIN users ru ON lower(ru.email) = lower(d.requested_by)
    LEFT JOIN LATERAL (SELECT r.reversed_by, r.reversed_at FROM lp_decision_reversal r
                       WHERE r.recommendation_key = d.recommendation_key AND d.state = 'approved'
                         AND r.reversed_at >= d.resolved_at
                       ORDER BY r.reversed_at DESC LIMIT 1) rv ON true
"""
_REQUEST_BY_KEY_SQL = _REQUEST_COLUMNS + " WHERE d.request_key = :request_key"
_REQUEST_LOCKED_SQL = _REQUEST_BY_KEY_SQL + " FOR UPDATE OF d, lr"

_RESOLVE_SQL = """
    UPDATE lp_dismissal_request
    SET state = :state, resolved_by = :resolved_by, resolved_at = :resolved_at, resolution_note = :note
    WHERE request_key = :request_key AND state = 'pending_approval'
    RETURNING request_key
"""

_OPEN_REQUESTS_SQL = """
    SELECT 'quantity_change' AS kind, c.change_key AS key, c.recommendation_key, c.recommended_q_i,
           c.proposed_q_i, c.proposed_at AS requested_at, c.proposed_by AS requested_by
    FROM lp_quantity_change c WHERE c.state = 'pending_approval'
    {DISMISSALS}
    ORDER BY requested_at DESC
"""
_OPEN_DISMISSALS_UNION = """
    UNION ALL
    SELECT 'dismissal' AS kind, d.request_key AS key, d.recommendation_key, d.recommended_q_i,
           NULL::numeric AS proposed_q_i, d.requested_at, d.requested_by
    FROM lp_dismissal_request d WHERE d.state = 'pending_approval'
"""


def _require_requests(present: dict) -> None:
    if not (present.get("requests") and present.get("approval") and present.get("reversal")):
        raise ApiError(503, rec.REQUESTS_NOT_READY, code="requests_not_ready")


def _request(db: Session, request_key: int) -> DismissalRequest:
    row = db.execute(text(_REQUEST_BY_KEY_SQL), {"request_key": request_key}).mappings().first()
    item = DismissalRequest(**dict(row))
    item.stock_observation = stock_observation.latest_for(db, "dismissal_request_key", [request_key]).get(request_key)
    return item


def _mine(email_a: str | None, email_b: str | None) -> bool:
    return (email_a or "").lower() == (email_b or "").lower() and bool(email_a)


# ── ask for a dismissal ────────────────────────────────────────────────────────────────────────────────────
@router.post("/{recommendation_key}/dismissal-request", response_model=DismissalRequest, status_code=202)
def request_dismissal(
    recommendation_key: int,
    body: DismissalRequestIn,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("lp.propose")),
) -> DismissalRequest:
    """Ask an admin to dismiss this recommendation. Held (202): the recommendation stays pending and active until
    an admin approves or rejects. A stock count may go with it (an observation, never stock on hand)."""
    present = rec._present(db)
    _require_requests(present)
    if current_user.role == "admin":
        raise ApiError(400, "An admin dismisses a recommendation directly (Dismiss) rather than asking for it.",
                       code="use_direct_dismissal")
    reason = body.reason.strip()
    # The row lock first: a quantity change or dismissal request racing this one waits, and the two reads below
    # (separate statements, so fresh snapshots under READ COMMITTED) see whatever it committed.
    row = db.execute(text(_LOCK_ROW_SQL), {"key": recommendation_key}).mappings().first()
    if row is None or row["status"] != "pending" or row["planning_cycle_date"] != row["current_cycle"]:
        db.rollback()
        raise rec.refusal_for(None if row is None else dict(row))
    open_change = db.execute(text(rec._OPEN_CHANGE_SQL), {"key": recommendation_key}).mappings().first()
    open_dismissal = db.execute(text(rec._OPEN_DISMISSAL_SQL), {"key": recommendation_key}).mappings().first()
    if open_change is not None or open_dismissal is not None:
        db.rollback()
        raise rec.refusal_for(dict(row), open_change, open_dismissal)
    if body.stock_observation is not None:   # refused (422) before anything is written
        try:
            stock_observation.to_pieces(body.stock_observation.quantity, body.stock_observation.unit, row["pack"])
        except ApiError:
            db.rollback()
            raise
    created = db.execute(text(_INSERT_REQUEST_SQL), {
        "key": recommendation_key, "reason": reason, "requested_by": current_user.email,
    }).mappings().first()
    if created is None:   # lost the race on the one-open index
        db.rollback()
        raise HTTPException(status_code=409, detail="A dismissal request for this recommendation was just made by someone else.")
    key = created["request_key"]
    audit.record(db, "Reorder Dismissal Requested",
                 f"SKU {row['sku']}: dismissal requested (request {key}), recommended {_fmt(row['q_i'])} pieces, "
                 f"awaiting approval: {reason}", actor=current_user)
    # The bell (migration 0071): every admin is told, in this same transaction.
    notifications.request_made(db, kind="dismissal_requested", actor=current_user, sku=row["sku"],
                               recommended=row["q_i"], request_key=key)
    if body.stock_observation is not None:
        stock_observation.record(db, body.stock_observation, product_key=row["product_key"],
                                 recommendation_key=recommendation_key, pack=row["pack"], context="dismissal_request",
                                 actor=current_user, sku=row["sku"], request_key=key)
    item = _request(db, key)
    db.commit()
    response_cache.invalidate()
    return item


@router.get("/dismissal-requests", response_model=DismissalRequestList)
def list_dismissal_requests(
    state: str = Query("pending_approval", description="pending_approval | approved | rejected | all"),
    recommendation_key: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission(*PROPOSE_KEYS)),
) -> DismissalRequestList:
    """An admin sees every request. Anyone else sees only their own. Newest first."""
    _require_requests(rec._present(db))
    if state != "all" and state not in STATES:
        raise HTTPException(status_code=400, detail="state must be one of pending_approval, approved, rejected, all")
    where, params = [], {}
    if state != "all":
        where.append("d.state = :state")
        params["state"] = state
    if recommendation_key is not None:
        where.append("d.recommendation_key = :recommendation_key")
        params["recommendation_key"] = recommendation_key
    if current_user.role != "admin":
        where.append("d.requested_by = :me")
        params["me"] = current_user.email
    sql = (_REQUEST_COLUMNS + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY d.requested_at DESC, d.request_key DESC")
    items = [DismissalRequest(**dict(r)) for r in db.execute(text(sql), params).mappings().all()]
    counts = stock_observation.latest_for(db, "dismissal_request_key", [i.request_key for i in items])
    for i in items:
        i.stock_observation = counts.get(i.request_key)
    return DismissalRequestList(count=len(items), items=items)


def _locked_pending_request(db: Session, request_key: int, admin: TokenPayload):
    row = db.execute(text(_REQUEST_LOCKED_SQL), {"request_key": request_key}).mappings().first()
    if row is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Dismissal request not found")
    if row["state"] != "pending_approval":
        db.rollback()
        raise HTTPException(status_code=409, detail=(
            f"This request was already {row['state']} by {row['resolved_by']}; it is decided once."))
    try:
        refuse_self_approval(row, admin, "requested_by")
    except ApiError:
        db.rollback()
        raise
    return row


@router.post("/dismissal-requests/{request_key}/approve", response_model=DismissalRequest)
def approve_dismissal(
    request_key: int,
    body: ApprovalNote | None = None,
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_lp_admin),
) -> DismissalRequest:
    """Dismiss the recommendation as requested (the ordinary dismiss, decided_by = the requester). Refused (409)
    when it was decided meanwhile, superseded, its q_i moved since the request, or the approver asked."""
    present = rec._present(db)
    _require_requests(present)
    request = _locked_pending_request(db, request_key, admin)
    current = db.execute(text(_ROW_SQL), {"key": request["recommendation_key"]}).mappings().first()
    now = datetime.datetime.utcnow()
    if current["planning_cycle_date"] != current["current_cycle"]:
        note = (f"Closed automatically: the {current['planning_cycle_date']} cycle was superseded by the "
                f"{current['current_cycle']} LP run, so this request can no longer be applied.")
        closed = db.execute(text(_RESOLVE_SQL), {"state": "rejected", "resolved_by": admin.email, "resolved_at": now,
                                                 "note": note, "request_key": request_key}).mappings().first()
        if closed is not None:
            audit.record(db, "Reorder Dismissal Request Closed",
                         f"SKU {current['sku']}: dismissal request {request_key} closed, {note}", actor=admin)
            db.commit()
        else:
            db.rollback()
        raise HTTPException(status_code=409, detail=(
            f"This recommendation belongs to the {current['planning_cycle_date']} cycle, which a newer LP run "
            f"({current['current_cycle']}) has superseded, so the request cannot be approved. It has been closed."))
    if round(float(current["q_i"]), 2) != round(float(request["recommended_q_i"]), 2):
        db.rollback()
        raise ApiError(409, (f"The recommendation changed after this request was made (it was "
                             f"{_fmt(request['recommended_q_i'])}, it is now {_fmt(current['q_i'])}). Reject this "
                             "request and have it made again against the new figure."),
                       code="recommendation_changed", recommended_q_i=float(current["q_i"]))
    note = ((body.note if body else None) or "").strip() or None
    resolved = db.execute(text(_RESOLVE_SQL), {"state": "approved", "resolved_by": admin.email, "resolved_at": now,
                                               "note": note, "request_key": request_key}).mappings().first()
    if resolved is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="This request was just decided by someone else.")
    # The dismiss itself; the request is already 'approved' in this transaction, so the open-request guard passes.
    decided = rec.decide_row(db, present, key=request["recommendation_key"], status="dismissed",
                             reason=request["reason"], decided_quantity=None, decided_by=request["requested_by"],
                             decided_at=now)
    audit.record(db, "Reorder Dismissal Request Approved",
                 f"SKU {decided['sku']}: dismissed on request {request_key} (requested by {request['requested_by']} "
                 f"at {_stamp(request['requested_at'])}), recommended {_fmt(request['recommended_q_i'])} pieces: "
                 f"{request['reason']}", actor=admin)
    notifications.request_decided(db, kind="dismissal_approved", admin=admin, requester=request["requested_by"],
                                  sku=decided["sku"], recommended=request["recommended_q_i"], request_key=request_key)
    db.commit()
    response_cache.invalidate()
    return _request(db, request_key)


@router.post("/dismissal-requests/{request_key}/reject", response_model=DismissalRequest)
def reject_dismissal(
    request_key: int,
    body: RejectRequest,
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_lp_admin),
) -> DismissalRequest:
    """Turn the request down: the recommendation stays pending and active, the request stays as the record."""
    _require_requests(rec._present(db))
    request = _locked_pending_request(db, request_key, admin)
    note = body.reason.strip()
    resolved = db.execute(text(_RESOLVE_SQL), {"state": "rejected", "resolved_by": admin.email,
                                               "resolved_at": datetime.datetime.utcnow(), "note": note,
                                               "request_key": request_key}).mappings().first()
    if resolved is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="This request was just decided by someone else.")
    audit.record(db, "Reorder Dismissal Request Rejected",
                 f"SKU {request['sku_code']}: dismissal request {request_key} (requested by {request['requested_by']}) "
                 f"rejected, the recommendation stays active: {note}", actor=admin)
    notifications.request_decided(db, kind="dismissal_rejected", admin=admin, requester=request["requested_by"],
                                  sku=request["sku_code"], recommended=request["recommended_q_i"],
                                  request_key=request_key)
    db.commit()
    response_cache.invalidate()
    return _request(db, request_key)


# ── stock counts ───────────────────────────────────────────────────────────────────────────────────────────
@router.get("/stock-observations", response_model=StockObservationList)
def list_stock_observations(
    state: str = Query("all", description="unverified | verified | rejected | all"),
    recommendation_key: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission(*PROPOSE_KEYS)),
) -> StockObservationList:
    """An admin sees every count. Anyone else sees only their own. Newest first."""
    _require_requests(rec._present(db))
    if state not in ("unverified", "verified", "rejected", "all"):
        raise HTTPException(status_code=400, detail="state must be one of unverified, verified, rejected, all")
    where, params = [], {}
    if state != "all":
        where.append("o.verification_state = :state")
        params["state"] = state
    if recommendation_key is not None:
        where.append("o.recommendation_key = :recommendation_key")
        params["recommendation_key"] = recommendation_key
    if current_user.role != "admin":
        where.append("o.reported_by = :me")
        params["me"] = current_user.email
    sql = (stock_observation.COLUMNS_SQL + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY o.reported_at DESC, o.observation_key DESC")
    items = [StockObservation(**dict(r)) for r in db.execute(text(sql), params).mappings().all()]
    return StockObservationList(count=len(items), items=items)


@router.post("/stock-observations/{observation_key}/verify", response_model=StockObservation)
def verify_stock_observation(
    observation_key: int,
    body: VerifyObservationBody,
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_lp_admin),
) -> StockObservation:
    """Record that an admin checked a count (verified) or found it wrong (rejected, note required). Changes no
    stock: Inventory_Fact and the plan are untouched."""
    _require_requests(rec._present(db))
    row = db.execute(text(stock_observation.COLUMNS_SQL + " WHERE o.observation_key = :k FOR UPDATE OF o"),
                     {"k": observation_key}).mappings().first()
    if row is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Stock count not found")
    if row["verification_state"] != "unverified":
        db.rollback()
        raise HTTPException(status_code=409, detail=f"This count was already {row['verification_state']} by {row['verified_by']}.")
    try:
        refuse_self_approval(row, admin, "reported_by")
    except ApiError:
        db.rollback()
        raise
    state = "verified" if body.verified else "rejected"
    note = (body.note or "").strip() or None
    updated = db.execute(text("""
        UPDATE lp_stock_observation
        SET verification_state = :state, verified_by = :by, verified_at = :at, verification_note = :note
        WHERE observation_key = :k AND verification_state = 'unverified'
        RETURNING observation_key
    """), {"state": state, "by": admin.email, "at": datetime.datetime.utcnow(), "note": note,
           "k": observation_key}).mappings().first()
    if updated is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="This count was just checked by someone else.")
    audit.record(db, f"Stock Count {'Verified' if body.verified else 'Rejected'}",
                 f"SKU {row['sku_code']}: observation {observation_key}, {_fmt(row['quantity_pieces'])} pieces "
                 f"reported by {row['reported_by']}" + (f": {note}" if note else "")
                 + ". Recorded only: stock on hand and the order plan are unchanged.", actor=admin)
    db.commit()
    response_cache.invalidate()
    return StockObservation(**dict(db.execute(text(stock_observation.COLUMNS_SQL + " WHERE o.observation_key = :k"),
                                              {"k": observation_key}).mappings().first()))


# ── what is waiting, and what happened ─────────────────────────────────────────────────────────────────────
@router.get("/open-requests", response_model=OpenRequestList)
def open_requests(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("lp.view")),
) -> OpenRequestList:
    """Every request awaiting an admin, so the table can mark a row 'under review' for every viewer. Who asked is
    shown to an admin and to the requester only."""
    present = rec._present(db)
    if not present.get("approval"):
        return OpenRequestList(ready=False, items=[])
    sql = _OPEN_REQUESTS_SQL.replace("{DISMISSALS}", _OPEN_DISMISSALS_UNION if present.get("requests") else "")
    items = []
    for r in db.execute(text(sql)).mappings().all():
        mine = _mine(r["requested_by"], current_user.email)
        items.append(OpenRequest(**{**dict(r), "mine": mine,
                                    "requested_by": r["requested_by"] if mine or current_user.role == "admin" else None}))
    return OpenRequestList(ready=bool(present.get("requests")), items=items)


_HISTORY_ROW_SQL = """
    SELECT lr.recommendation_key, lr.q_i, lr.status, lr.planning_cycle_date, lr.generated_at, lr.lp_run_key,
           {_DECISION}, COALESCE(pd.sku_code, pd.category_path) AS sku_code, pd.product_name, {PACK} AS pack
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE lr.recommendation_key = :key
""".replace("{PACK}", PACK_SQL)


@router.get("/{recommendation_key}/history", response_model=RecommendationHistory)
def recommendation_history(
    recommendation_key: int,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission(*PROPOSE_KEYS)),
) -> RecommendationHistory:
    """The recommendation's life, oldest first: the system's quantity, each request and its outcome, each decision
    and reversal, each stock count. A non-admin sees their own requests and counts, and every decision."""
    present = rec._present(db)
    decision = rec._DECISION_COLS_SQL if present.get("decision_cols") else rec._DECISION_COLS_ABSENT_SQL
    row = db.execute(text(_HISTORY_ROW_SQL.replace("{_DECISION}", decision)), {"key": recommendation_key}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    admin = current_user.role == "admin"
    visible = lambda who: admin or _mine(who, current_user.email)   # noqa: E731
    events: list[HistoryEvent] = [HistoryEvent(
        at=row["generated_at"], kind="recommended", actor="order plan",
        summary=f"The order plan recommended {_fmt(row['q_i'])} pieces"
                + (f" (LP run {row['lp_run_key']})" if row.get("lp_run_key") is not None else "") + ".",
        quantity_after=float(row["q_i"]))]

    if present.get("approval"):
        for c in db.execute(text(_CHANGE_COLUMNS + " WHERE c.recommendation_key = :key ORDER BY c.proposed_at"),
                            {"key": recommendation_key}).mappings().all():
            if not visible(c["proposed_by"]):
                continue
            c = QuantityChange(**dict(c))
            events.append(HistoryEvent(at=c.proposed_at, kind="change_proposed", actor=c.proposed_by, reason=c.reason,
                                       quantity_before=c.recommended_q_i, quantity_after=c.proposed_q_i,
                                       summary=f"Quantity change {c.change_key} proposed: {_fmt(c.recommended_q_i)} -> "
                                               f"{_fmt(c.proposed_q_i)} pieces."))
            if c.state != "pending_approval":
                events.append(HistoryEvent(at=c.resolved_at, kind=f"change_{c.state}", actor=c.resolved_by,
                                           reason=c.resolution_note, quantity_before=c.recommended_q_i,
                                           quantity_after=c.proposed_q_i,
                                           summary=f"Quantity change {c.change_key} {c.state}."))
    if present.get("requests"):
        for d in db.execute(text(_REQUEST_COLUMNS + " WHERE d.recommendation_key = :key ORDER BY d.requested_at"),
                            {"key": recommendation_key}).mappings().all():
            if not visible(d["requested_by"]):
                continue
            events.append(HistoryEvent(at=d["requested_at"], kind="dismissal_requested", actor=d["requested_by"],
                                       reason=d["reason"], quantity_before=float(d["recommended_q_i"]),
                                       summary=f"Dismissal requested (request {d['request_key']})."))
            if d["state"] != "pending_approval":
                events.append(HistoryEvent(at=d["resolved_at"], kind=f"dismissal_{d['state']}", actor=d["resolved_by"],
                                           reason=d["resolution_note"],
                                           summary=f"Dismissal request {d['request_key']} {d['state']}."))
        for o in db.execute(text(stock_observation.COLUMNS_SQL + " WHERE o.recommendation_key = :key ORDER BY o.reported_at"),
                            {"key": recommendation_key}).mappings().all():
            if not visible(o["reported_by"]):
                continue
            typed = f"{_fmt(o['quantity_entered'])} {o['unit_entered']}"
            pieces = f" = {_fmt(o['quantity_pieces'])} pieces" if o["unit_entered"] != "pieces" else ""
            events.append(HistoryEvent(at=o["reported_at"], kind="stock_reported", actor=o["reported_by"],
                                       reason=o["notes"], quantity_after=float(o["quantity_pieces"]),
                                       summary=f"Stock counted: {typed}{pieces}"
                                               + (f" at {o['location']}" if o["location"] else "")
                                               + " (an observation; stock on hand unchanged)."))
            if o["verification_state"] != "unverified":
                events.append(HistoryEvent(at=o["verified_at"], kind=f"stock_{o['verification_state']}",
                                           actor=o["verified_by"], reason=o["verification_note"],
                                           summary=f"Stock count {o['observation_key']} {o['verification_state']}."))
    if present.get("reversal"):
        for r in db.execute(text("""
            SELECT prior_status, prior_decided_q_i, prior_reason, prior_decided_by, prior_decided_at, q_i,
                   reversed_by, reversed_at, reversal_reason
            FROM lp_decision_reversal WHERE recommendation_key = :key ORDER BY reversed_at
        """), {"key": recommendation_key}).mappings().all():
            qty = r["prior_decided_q_i"] if r["prior_decided_q_i"] is not None else r["q_i"]
            events.append(HistoryEvent(at=r["prior_decided_at"], kind="decided", actor=r["prior_decided_by"],
                                       reason=r["prior_reason"], quantity_after=float(qty) if r["prior_status"] == "accepted" else None,
                                       summary=f"Decision: {r['prior_status']}"
                                               + (f" at {_fmt(qty)} pieces." if r["prior_status"] == "accepted" else ".")))
            events.append(HistoryEvent(at=r["reversed_at"], kind="reversed", actor=r["reversed_by"],
                                       reason=r["reversal_reason"], summary="Decision reversed; back to pending."))
    if row["status"] in ("accepted", "dismissed"):
        qty = row.get("decided_q_i") if row.get("decided_q_i") is not None else row["q_i"]
        events.append(HistoryEvent(at=row.get("decided_at"), kind="decided", actor=row.get("decided_by"),
                                   reason=row.get("decision_reason"),
                                   quantity_after=float(qty) if row["status"] == "accepted" else None,
                                   summary=f"Decision: {row['status']}"
                                           + (f" at {_fmt(qty)} pieces." if row["status"] == "accepted" else ".")))
    epoch = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    def _key(e: HistoryEvent):
        at = e.at or epoch
        return at if at.tzinfo else at.replace(tzinfo=datetime.timezone.utc)

    events.sort(key=_key)
    return RecommendationHistory(
        recommendation_key=recommendation_key, sku_code=row["sku_code"], product_name=row["product_name"],
        planning_cycle_date=row["planning_cycle_date"], recommended_q_i=float(row["q_i"]),
        pack_size=float(row["pack"]) if row["pack"] is not None else None, status=row["status"], events=events)
