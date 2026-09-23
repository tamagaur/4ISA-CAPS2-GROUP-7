"""
backend.routers.fsn — GET /fsn

FSN (fast / slow / non-moving) per product by movement frequency: the
analytical mapping's D3. The rules live in analytics/classification/fsn.py.

Window: the last FSN_WINDOW_MONTHS OBSERVED months up to `period` — the
months the principal has any data for, never past its latest month, so a
month the data doesn't reach (or a missing Del Monte file) isn't read as
zero sales. Default `period`: the principal's latest data month. Per
principal, because their months differ (Del Monte's sell-out ends earlier
and has gaps).

Grain follows the data (DEC-03): Unilever per SKU from
Unilever_SKU_Demand_Fact_Real; Del Monte per product category from
SellOut_Fact_Real, summed across regions like the ABC run. A product with no
sale anywhere in the window isn't listed — it is non-moving by definition,
and callers treat a classified product missing here as 'N'.

X-Data-Mode: preview adds Unilever's 2021-22 placeholder months, so a
window ending in them is classified on placeholder movement
(backend/data_mode.py).
"""
from __future__ import annotations

from collections import Counter

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.classification.fsn import (
    FAST_ADI_MAX, FSN_LABELS, FSN_WINDOW_MONTHS, MIN_FAST_SALES_MONTHS, NON_MOVING_MONTHS, classify_fsn,
)
from backend.data_mode import PREVIEW, REAL, get_data_mode, preview_block, unilever_demand
from backend.deps import TokenPayload, get_current_user, get_db
from backend.principals import PrincipalQuery, normalize_principal

router = APIRouter(prefix="/fsn", tags=["fsn"])

# Per principal: (observed-months query, per-product monthly quantity query).
# {demand} is the Unilever demand relation for the request's data mode
# (backend/data_mode.py) — the _Real view's own name in real mode.
_SOURCES = {
    "unilever": (
        "SELECT DISTINCT calendar_month AS period FROM {demand} "
        "WHERE calendar_month <= :end ORDER BY calendar_month DESC LIMIT :n",
        """
        SELECT d.product_key, pd.sku_code AS sku_id, d.calendar_month AS period, SUM(d.quantity_sold) AS qty
        FROM {demand} d
        JOIN Product_Dimension pd ON pd.product_key = d.product_key
        WHERE d.calendar_month = ANY(:months)
        GROUP BY d.product_key, pd.sku_code, d.calendar_month
        """,
    ),
    "delmonte": (
        "SELECT DISTINCT _period AS period FROM SellOut_Fact_Real "
        "WHERE _period <= :end ORDER BY _period DESC LIMIT :n",
        """
        SELECT s.product_key, pd.category_path AS sku_id, s._period AS period, SUM(s.quantity) AS qty
        FROM SellOut_Fact_Real s
        JOIN Product_Dimension pd ON pd.product_key = s.product_key
        WHERE s._period = ANY(:months)
        GROUP BY s.product_key, pd.category_path, s._period
        """,
    ),
}


def classify_principal(
    db: Session, principal: str, period: str | None, mode: str = REAL,
) -> tuple[dict | None, list[dict]]:
    """(window, items) for one principal; window None when it has no data."""
    months_sql, qty_sql = (sql.format(demand=unilever_demand(mode)) for sql in _SOURCES[principal])
    end = period or "9999-12"
    months = sorted(r["period"] for r in db.execute(text(months_sql), {"end": end, "n": FSN_WINDOW_MONTHS}).mappings().all())
    if not months:
        return None, []
    index = {m: i for i, m in enumerate(months)}
    series: dict[int, dict] = {}
    for r in db.execute(text(qty_sql), {"months": months}).mappings().all():
        entry = series.setdefault(int(r["product_key"]), {"sku_id": r["sku_id"], "qty": np.zeros(len(months))})
        entry["qty"][index[r["period"]]] += float(r["qty"] or 0)

    items = []
    for product_key, entry in series.items():
        if not (entry["qty"] > 0).any():
            continue
        result = classify_fsn(entry["qty"])
        last_sale = max(i for i, q in enumerate(entry["qty"]) if q > 0)
        items.append({
            "product_key": product_key,
            "sku_id": entry["sku_id"],
            "principal": principal,
            **result,
            "last_sale_period": months[last_sale],
        })
    return {"start": months[0], "end": months[-1], "observed_months": len(months)}, items


@router.get("")
def get_fsn(
    principal: str | None = PrincipalQuery,
    period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$", description="Window end 'YYYY-MM'; default the latest data month."),
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> dict:
    scope = normalize_principal(principal)
    windows, items = {}, []
    for p in ([scope] if scope else ["unilever", "delmonte"]):
        window, rows = classify_principal(db, p, period, mode)
        if window:
            windows[p] = window
            items.extend(rows)
    counts = Counter(i["fsn"] for i in items)
    payload = {
        "period": period,
        "windows": windows,
        "rules": {
            "window_months": FSN_WINDOW_MONTHS,
            "non_moving_months": NON_MOVING_MONTHS,
            "fast_adi_max": FAST_ADI_MAX,
            "min_fast_sales_months": MIN_FAST_SALES_MONTHS,
            "labels": FSN_LABELS,
        },
        "summary": {k: counts.get(k, 0) for k in ("F", "S", "N")},
        "items": items,
    }
    if mode == PREVIEW:
        payload["data_mode"] = preview_block(db)
    return payload
