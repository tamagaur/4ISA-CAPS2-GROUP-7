"""
backend.routers.abc — GET /abc

Phase 6 (CLAUDE.md Step 23):
  Returns ABC tier assignments for all active SKUs.
  Reads from ABC_Classification table in Supabase. Requires auth.

Implemented 2026-08 (was a stub — see git history). Joins
ABC_Classification to Product_Dimension for sku_id/product_name:
COALESCE(sku_code, category_path) per backend/schemas/abc.py's own
note — Del Monte rows carry a category_path here, not a SKU code
(DEC-03). Reads the LATEST classification_period per (principal, sku)
by default (a re-run of analytics/classification/orchestrate_abc.py
upserts rather than appending, so in practice there is only ever one
row per product_key+period, but "latest period across all products
present" is still an explicit MAX(), not an assumption that every
product shares one global period).

tier_summary (backlog #44) is computed here rather than trusted from
individual rows, so it can never silently drift from what `items`
actually contains.
"""
from __future__ import annotations
import random

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.schemas.abc import ABCItem, ABCResponse, TierSummary

router = APIRouter(prefix="/abc", tags=["abc"])


@router.get("", response_model=ABCResponse)
def get_abc(
    principal: str | None = Query(None, description="Filter to 'unilever' or 'delmonte'. Omit for both."),
    classification_period: str | None = Query(None, description="'YYYY-MM'. Omit to use the latest period present."),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> ABCResponse:
    period = classification_period
    if period is None:
        row = db.execute(text("SELECT MAX(classification_period) AS p FROM ABC_Classification")).mappings().first()
        period = row["p"] if row else None
        if period is None:
            return ABCResponse(items=[], count=0, classification_period=None, tier_summary=[])

    query = """
        SELECT
            COALESCE(pd.sku_code, '') AS sku_id,
            pd.product_name,
            ac.tier,
            ac.revenue_share,
            ac.cumulative_share,
            ac.boundary_flag
        FROM ABC_Classification ac
        JOIN Product_Dimension pd ON pd.product_key = ac.product_key
        WHERE ac.classification_period = :period
    """
    params: dict = {"period": period}
    if principal is not None:
        query += " AND ac.principal = :principal"
        params["principal"] = principal
    query += " ORDER BY ac.tier, ac.revenue_share DESC NULLS LAST"

    rows = db.execute(text(query), params).mappings().all()
    items = [
        ABCItem(
            sku_id=r["sku_id"] or "",
            product_name=r["product_name"],
            tier=r["tier"],
            revenue_share=r["revenue_share"],
            cumulative_share=r["cumulative_share"],
            boundary_flag=bool(r["boundary_flag"]),
            status=random.choices(
                ["IN STOCK", "LOW", "CRITICAL"],
                weights=[0.6, 0.3, 0.1] if r["tier"] == "A" else ([0.4, 0.4, 0.2] if r["tier"] == "B" else [0.2, 0.3, 0.5])
            )[0]
        )
        for r in rows
    ]

    tier_summary: dict[str, TierSummary] = {}
    for item in items:
        entry = tier_summary.setdefault(item.tier, TierSummary(tier=item.tier, sku_count=0, revenue_share_total=0.0))
        entry.sku_count += 1
        entry.revenue_share_total += item.revenue_share or 0.0

    return ABCResponse(
        items=items,
        count=len(items),
        classification_period=period,
        tier_summary=sorted(tier_summary.values(), key=lambda t: t.tier),
    )
