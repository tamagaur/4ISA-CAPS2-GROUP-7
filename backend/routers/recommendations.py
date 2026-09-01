"""
backend.routers.recommendations — GET /recommendations, PATCH /recommendations/{id}

Returns LP-derived replenishment quantities Q_i per SKU, joined to
Product_Dimension for identity and to the latest Inventory_Fact_Real period
for current_stock. urgency is derived from current_stock vs rop_i (same
CRITICAL/URGENT/PLANNED thresholds a reviewer would apply reading the ROP
column), not stored anywhere.

?from=/?to= (shared date-range picker, 2026-09) — OPTIONAL, both must be
given together or neither is used (matching backend/routers/dashboard.py's
own ?period=/?start_period= convention for the same shared picker, just
under bo_monitoring.py's from/to naming since this is a plain date-bounded
table read, not a period-anchored trend). Filters on lr.planning_cycle_date
falling within [from, to] inclusive — real, meaningful spread on this
column (34 distinct pending planning_cycle_dates from 2023-05 through
2026-03, confirmed live), unlike GET /forecast's forecast_date which is a
single fixed value for every SKU and can't be meaningfully range-filtered
the same way.

PATCH implements the Accept/Dismiss write-back onto LP_Recommendation.status.
There is no cost/lead-time/reason column on LP_Recommendation — accept/dismiss
reasons stay logged client-side to the audit log, not persisted here.
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.schemas.recommendations import RecommendationItem, RecommendationDecision, RecommendationsResponse

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

_SELECT_ONE = """
    SELECT
        lr.recommendation_key,
        COALESCE(pd.sku_code, pd.category_path) AS sku_id,
        pd.product_name,
        pd.principal,
        lr.planning_cycle_date,
        lr.q_i,
        lr.rop_i,
        lr.ss_i,
        lr.status,
        COALESCE(inv.current_stock, 0) AS current_stock
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    LEFT JOIN (
        SELECT product_key, SUM(quantity_on_hand) AS current_stock
        FROM inventory_fact_real
        WHERE _period = (SELECT MAX(_period) FROM inventory_fact_real)
        GROUP BY product_key
    ) inv ON inv.product_key = lr.product_key
"""


def _to_item(r) -> RecommendationItem:
    stock = float(r["current_stock"] or 0)
    rop = float(r["rop_i"])
    urgency = "CRITICAL" if stock < rop * 0.5 else ("URGENT" if stock < rop else "PLANNED")
    return RecommendationItem(
        recommendation_key=r["recommendation_key"],
        sku_id=r["sku_id"] or "",
        product_name=r["product_name"],
        principal=r["principal"],
        planning_cycle_date=r["planning_cycle_date"],
        q_i=float(r["q_i"]),
        rop_i=rop,
        ss_i=float(r["ss_i"]),
        status=r["status"],
        current_stock=stock,
        urgency=urgency,
    )


@router.get("", response_model=RecommendationsResponse)
def get_recommendations(
    status: str | None = Query(None, description="Filter to 'pending' | 'accepted' | 'dismissed'. Omit for all."),
    from_date: str | None = Query(None, alias="from", description="'YYYY-MM-DD'. The shared date-range picker's applied start. Must be given with 'to' or not at all — filters on lr.planning_cycle_date."),
    to_date: str | None = Query(None, alias="to", description="'YYYY-MM-DD'. The shared date-range picker's applied end. Must be given with 'from' or not at all."),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> RecommendationsResponse:
    # Unilever-only (2026-09) — see backend/routers/dashboard.py's module
    # docstring for the full reasoning.
    query = _SELECT_ONE + " WHERE pd.principal = 'unilever'"
    params: dict = {}
    if status:
        query += " AND lr.status = :status"
        params["status"] = status
    # Shared date-range picker (2026-09) — planning_cycle_date is a real
    # DATE column (unlike the fact tables' 'YYYY-MM' _period text), so this
    # compares dates directly, no month-truncation needed.
    if from_date and to_date:
        query += " AND lr.planning_cycle_date >= :from_date AND lr.planning_cycle_date <= :to_date"
        params["from_date"] = from_date
        params["to_date"] = to_date
    query += " ORDER BY lr.planning_cycle_date DESC, lr.rop_i DESC"

    rows = db.execute(text(query), params).mappings().all()
    items = [_to_item(r) for r in rows]
    return RecommendationsResponse(items=items, count=len(items))


@router.patch("/{recommendation_key}", response_model=RecommendationItem)
def update_recommendation(
    recommendation_key: int,
    decision: RecommendationDecision,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> RecommendationItem:
    if decision.status not in ("accepted", "dismissed"):
        raise HTTPException(status_code=400, detail="status must be 'accepted' or 'dismissed'")

    result = db.execute(
        text("""
            UPDATE lp_recommendation
            SET status = :status, decided_at = :decided_at, decided_by = :decided_by
            WHERE recommendation_key = :key
        """),
        {
            "status": decision.status,
            "decided_at": datetime.datetime.utcnow(),
            "decided_by": current_user.email,
            "key": recommendation_key,
        },
    )
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="Recommendation not found")
    db.commit()

    row = db.execute(
        text(_SELECT_ONE + " WHERE lr.recommendation_key = :key"), {"key": recommendation_key}
    ).mappings().first()
    return _to_item(row)
