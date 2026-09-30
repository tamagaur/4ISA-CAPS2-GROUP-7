"""
backend.routers.pareto — GET /pareto

Brand- and category-level ABC (Pareto): the analytical mapping's D1, "which
brands and product categories drive the majority of SSM's demand?".

Revenue is measured exactly as the SKU-level ABC run measures it
(analytics/classification/orchestrate_abc.py): positive net_amount — per
SKU from Unilever_SKU_Demand_Fact_Real, per product category from
SellOut_Fact_Real — then summed to the requested grain and ranked by the
same classify_abc() with the same 80% / 95% cutoffs.

  grain=brand     Unilever only: Del Monte's product master carries no brand
                  (0 / 15,308), so its answer is a reason, not rows.
  grain=category  Unilever: Product_Dimension.category_path (380 SKUs sit in
                  'UNCLASSIFIED' and are kept as their own row, not dropped).
                  Del Monte: its category grain, the same rows its ABC ranks.

`months` = 1 matches the ABC page (one month's revenue, the 'single'
method); 12 sums the trailing 12 months ending at `period` for a steadier
view. Default `period`: each principal's latest data month.

X-Data-Mode: preview adds Unilever's 2021-22 placeholder months to the
revenue, so a window reaching back into them ranks placeholder revenue
(backend/data_mode.py).
"""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.classification.abc import TIER_A_CUTOFF, TIER_B_CUTOFF, classify_abc
from backend.data_mode import PREVIEW, REAL, get_data_mode, preview_block, unilever_demand
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import PrincipalQuery, normalize_principal
from backend.routers.dashboard import _latest_sales_period

router = APIRouter(prefix="/pareto", tags=["pareto"])


def _month_minus(period: str, months: int) -> str:
    y, m = map(int, period.split("-"))
    total = y * 12 + (m - 1) - months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


# {demand} is the Unilever demand relation for the request's data mode
# (backend/data_mode.py) — the _Real view's own name in real mode.
_QUERIES = {
    ("unilever", "brand"): """
        SELECT COALESCE(pd.brand, 'NO BRAND') AS name, SUM(d.net_amount) AS revenue, COUNT(DISTINCT d.product_key) AS products
        FROM {demand} d JOIN Product_Dimension pd ON pd.product_key = d.product_key
        WHERE d.calendar_month > :start AND d.calendar_month <= :end AND d.net_amount > 0
        GROUP BY 1
    """,
    ("unilever", "category"): """
        SELECT COALESCE(pd.category_path, 'UNCLASSIFIED') AS name, SUM(d.net_amount) AS revenue, COUNT(DISTINCT d.product_key) AS products
        FROM {demand} d JOIN Product_Dimension pd ON pd.product_key = d.product_key
        WHERE d.calendar_month > :start AND d.calendar_month <= :end AND d.net_amount > 0
        GROUP BY 1
    """,
    ("delmonte", "category"): """
        SELECT pd.category_path AS name, SUM(s.net_amount) AS revenue, COUNT(DISTINCT s.product_key) AS products
        FROM SellOut_Fact_Real s JOIN Product_Dimension pd ON pd.product_key = s.product_key
        WHERE s._period > :start AND s._period <= :end
        GROUP BY 1
        HAVING SUM(s.net_amount) > 0
    """,
}


def pareto_for(db: Session, principal: str, grain: str, period: str | None, months: int, mode: str = REAL) -> dict:
    query = _QUERIES.get((principal, grain))
    if query is None:
        return {"principal": principal, "rows": [], "blocked_reason": (
            "Del Monte's product master has no brand for any product, so there is no brand ranking — "
            "use grain=category."
        )}
    latest = _latest_sales_period(db, principal)
    end = min(period, latest) if (period and latest) else (period or latest)
    if end is None:
        return {"principal": principal, "rows": [], "blocked_reason": f"No sales data for {principal}."}
    rows = db.execute(
        text(query.format(demand=unilever_demand(mode))), {"start": _month_minus(end, months), "end": end}
    ).mappings().all()
    df = pd.DataFrame(
        [{"sku_id": r["name"], "total_revenue": float(r["revenue"]), "products": int(r["products"])} for r in rows],
        columns=["sku_id", "total_revenue", "products"],
    )
    if df.empty:
        return {"principal": principal, "period": end, "rows": [], "blocked_reason": f"No positive revenue for {principal} in the window."}
    ranked = classify_abc(df[["sku_id", "total_revenue"]]).merge(df[["sku_id", "products"]], on="sku_id")
    ranked = ranked.sort_values("total_revenue", ascending=False)
    return {
        "principal": principal,
        "period": end,
        "window_start": _month_minus(end, months - 1),
        "rows": [
            {
                "name": r.sku_id,
                "revenue": round(float(r.total_revenue), 2),
                "revenue_share": round(float(r.revenue_share), 4),
                "cumulative_share": round(float(r.cumulative_share), 4),
                "tier": r.tier,
                "products": int(r.products),
            }
            for r in ranked.itertuples()
        ],
        "blocked_reason": None,
    }


@router.get("")
def get_pareto(
    grain: str = Query("brand", pattern="^(brand|category)$"),
    principal: str | None = PrincipalQuery,
    period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    months: int = Query(1, ge=1, le=36, description="1 = the ABC page's single month; 12 = trailing year."),
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("abc.view")),
) -> dict:
    scope = normalize_principal(principal)
    payload = {
        "grain": grain,
        "months": months,
        "cutoffs": {"A": TIER_A_CUTOFF, "B": TIER_B_CUTOFF},
        "principals": [
            pareto_for(db, p, grain, period, months, mode) for p in ([scope] if scope else ["unilever", "delmonte"])
        ],
    }
    if mode == PREVIEW:
        payload["data_mode"] = preview_block(db)
    return payload
