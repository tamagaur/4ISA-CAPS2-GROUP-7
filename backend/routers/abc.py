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

Fixed 2026-08: stock_status was previously `random.choices(...)` — a
placeholder that re-rolled a fake status on every request instead of
reading real inventory. Replaced with the same real, deterministic rule
GET /inventory already uses (backend/routers/inventory.py), extended to
prefer each SKU's actual reorder point (from the latest pending
LP_Recommendation — same source SKUManagement/ReorderRecommendations
read) over the flat 100-unit fallback when one exists.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.schemas.abc import ABCItem, ABCResponse, TierSummary

router = APIRouter(prefix="/abc", tags=["abc"])


def _stock_status(current_stock: float, reorder_point: float | None) -> str:
    """Real, deterministic stock status — no simulation. Mirrors
    GET /inventory's rule (current_stock > 100 -> IN STOCK, > 0 -> LOW,
    else CRITICAL), but uses the SKU's own reorder_point as the LOW/IN
    STOCK cutoff instead of the flat 100-unit default whenever a pending
    LP_Recommendation exists for it — that's a real per-SKU threshold,
    not a guess.
    """
    if current_stock <= 0:
        return "CRITICAL"
    if reorder_point is not None:
        return "IN STOCK" if current_stock > reorder_point else "LOW"
    return "IN STOCK" if current_stock > 100 else "LOW"


@router.get("", response_model=ABCResponse)
def get_abc(
    principal: str | None = Query(None, description="Filter to 'unilever' or 'delmonte'. Omit for both."),
    classification_period: str | None = Query(None, description="'YYYY-MM'. Omit to use the latest period present."),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> ABCResponse:
    period = classification_period
    if period is None:
        row = db.execute(text("SELECT MAX(classification_period) AS p FROM abc_classification")).mappings().first()
        period = row["p"] if row else None
        if period is None:
            return ABCResponse(items=[], count=0, classification_period=None, tier_summary=[])

    query = """
        SELECT
            COALESCE(pd.sku_code, '') AS sku_id,
            pd.product_name,
            ac.principal,
            ac.tier,
            ac.revenue_share,
            ac.cumulative_share,
            ac.boundary_flag,
            COALESCE(inv.current_stock, 0) AS current_stock,
            rop.rop_i AS reorder_point
        FROM abc_classification ac
        JOIN product_dimension pd ON pd.product_key = ac.product_key
        LEFT JOIN (
            SELECT product_key, SUM(quantity_on_hand) AS current_stock
            FROM inventory_fact_real
            WHERE _period = (SELECT MAX(_period) FROM inventory_fact_real)
            GROUP BY product_key
        ) inv ON inv.product_key = ac.product_key
        LEFT JOIN (
            SELECT DISTINCT ON (product_key) product_key, rop_i
            FROM lp_recommendation
            WHERE status = 'pending'
            ORDER BY product_key, planning_cycle_date DESC
        ) rop ON rop.product_key = ac.product_key
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
            principal=r["principal"],
            tier=r["tier"],
            revenue_share=r["revenue_share"],
            cumulative_share=r["cumulative_share"],
            boundary_flag=bool(r["boundary_flag"]),
            current_stock=float(r["current_stock"] or 0),
            stock_status=_stock_status(
                float(r["current_stock"] or 0),
                float(r["reorder_point"]) if r["reorder_point"] is not None else None,
            ),
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
