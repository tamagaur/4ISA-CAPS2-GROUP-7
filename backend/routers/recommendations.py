"""
backend.routers.recommendations — GET /recommendations, PATCH /recommendations/{id}

Returns LP-derived replenishment quantities Q_i per SKU, joined to
Product_Dimension for identity and to the latest Inventory_Fact_Real period
for current_stock. urgency is derived from current_stock vs rop_i (same
CRITICAL/URGENT/PLANNED thresholds a reviewer would apply reading the ROP
column), not stored anywhere.

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
    FROM LP_Recommendation lr
    JOIN Product_Dimension pd ON pd.product_key = lr.product_key
    LEFT JOIN (
        SELECT product_key, SUM(quantity_on_hand) AS current_stock
        FROM Inventory_Fact_Real
        WHERE _period = (SELECT MAX(_period) FROM Inventory_Fact_Real)
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
    principal: str | None = Query(None, description="Filter to 'unilever' or 'delmonte'. Omit for both."),
    status: str | None = Query(None, description="Filter to 'pending' | 'accepted' | 'dismissed'. Omit for all."),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> RecommendationsResponse:
    query = _SELECT_ONE + " WHERE 1=1"
    params: dict = {}
    if principal in ("unilever", "delmonte"):
        query += " AND pd.principal = :principal"
        params["principal"] = principal
    if status:
        query += " AND lr.status = :status"
        params["status"] = status
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
            UPDATE LP_Recommendation
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
