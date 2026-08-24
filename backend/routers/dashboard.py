"""
backend.routers.dashboard — GET /dashboard

Feeds the Dashboard page's four KPI cards + weeks-of-cover chart
(frontend/src/api/dashboard.js's getDashboardData). Response shape is
fixed by that file's stub — this endpoint must match it exactly so
swapping the frontend over is a one-line change, not a rewrite.

Honest-null policy (matches the frontend's null-handling contract):
  inventory.value / inventory.weeks_of_cover / cover_series[].weeks_of_cover
    — always null. inventory_fact has no valuation/price column anywhere
    (confirmed against the live schema) and unit-quantity math was tried
    and confirmed implausible (Del Monte inventory is per-SKU, demand is
    per-category, they don't join per product). There is nothing honest
    to compute here yet — do not fabricate a value once this file is
    touched again for a different reason.
  recommendations.order_value
    — always null. lp_recommendation has no runner yet, and even once one
    exists, Q_i * unit_price needs a cost column that doesn't exist.
  recommendations.product_count
    — real: COUNT(*) of pending LP_Recommendation rows. Needs no price,
    so it's honestly computable even though order_value isn't.
  forecast.unreliable_count / forecast.total_count
    — real: from Forecast_Result at its most recent forecast_date. mape
    is stored as a PERCENT (see schema.sql's column comment) — the gate
    is `mape >= 20.0`, not `>= 0.20`. unreliable_count is null (not 0)
    when total_count is 0, matching this app's "null = no data source
    yet" convention everywhere else, rather than claiming "0 unreliable"
    when there's no forecast run to judge at all.
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

POLICY_WEEKS = 3
MAPE_UNRELIABLE_GATE = 20.0  # percent — see schema.sql's Forecast_Result.mape comment


def _last_12_periods() -> list[str]:
    """Last 12 calendar months as 'YYYY-MM', oldest first — same grain
    _period/calendar_month use everywhere else, mirrors the frontend
    stub's last12Periods() so the shape is identical either way."""
    today = datetime.date.today()
    periods = []
    for i in range(11, -1, -1):
        month_index = today.month - 1 - i
        year = today.year + month_index // 12
        month = month_index % 12 + 1
        periods.append(f"{year:04d}-{month:02d}")
    return periods


@router.get("")
def get_dashboard(
    principal: str = Query("all", description="Filter to 'unilever' or 'delmonte'. Use 'all' for both."),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    principal_filter = ""
    params: dict = {}
    if principal in ("unilever", "delmonte"):
        principal_filter = "AND pd.principal = :principal"
        params["principal"] = principal

    # recommendations.product_count — real, no price needed.
    reco_row = db.execute(
        text(f"""
            SELECT COUNT(*) AS product_count
            FROM LP_Recommendation lr
            JOIN Product_Dimension pd ON pd.product_key = lr.product_key
            WHERE lr.status = 'pending' {principal_filter}
        """),
        params,
    ).mappings().first()
    product_count = int(reco_row["product_count"])

    # forecast.unreliable_count / total_count — real, at the most recent
    # forecast_date. A product_key with no Product_Dimension match can't
    # happen (FK is NOT NULL), so the join never silently drops rows.
    forecast_row = db.execute(
        text(f"""
            WITH latest AS (
                SELECT MAX(forecast_date) AS forecast_date FROM Forecast_Result
            )
            SELECT
                COUNT(*) AS total_count,
                COUNT(*) FILTER (WHERE fr.mape >= :mape_gate) AS unreliable_count
            FROM Forecast_Result fr
            JOIN Product_Dimension pd ON pd.product_key = fr.product_key
            JOIN latest ON fr.forecast_date = latest.forecast_date
            WHERE 1=1 {principal_filter}
        """),
        {**params, "mape_gate": MAPE_UNRELIABLE_GATE},
    ).mappings().first()
    total_count = int(forecast_row["total_count"])
    unreliable_count = int(forecast_row["unreliable_count"]) if total_count > 0 else None

    return {
        "principal": principal,
        "period": None,
        "inventory": {"value": None, "weeks_of_cover": None, "policy_weeks": POLICY_WEEKS},
        "recommendations": {"order_value": None, "product_count": product_count},
        "forecast": {"unreliable_count": unreliable_count, "total_count": total_count},
        "cover_series": [{"period": p, "weeks_of_cover": None} for p in _last_12_periods()],
    }
