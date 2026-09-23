"""
backend.routers.category_trends — GET /category-trends

Per product category, the monthly revenue history and a 12-month trend
projection: the analytical mapping's P1. The method and its limits live in
analytics/forecasting/category_trend.py — a Theil–Sen trend line with
Mann–Kendall significance, not a validated forecast.

  Unilever   Product_Dimension.category_path over
             Unilever_SKU_Demand_Fact_Real (positive net_amount, the ABC run's
             revenue measure). 'UNCLASSIFIED' is kept as its own row.
             X-Data-Mode: preview adds the 2021-22 placeholder months to the
             history (backend/data_mode.py).
  Del Monte  SellOut_Fact_Real by category_path, only from the Jan 2025
             regrouping on (DEL_MONTE_REGROUP_PERIOD) — the older
             sub-categories aren't the same categories.

Only OBSERVED months count: a month the principal has no data for at all is
left out, not read as zero revenue (Del Monte's files are missing for whole
months). A category with no revenue in an observed month gets a zero there.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.forecasting.category_trend import MIN_POINTS, PROJECTION_MONTHS, TREND_WINDOW_MONTHS, project_category
from backend.data_mode import PREVIEW, REAL, get_data_mode, preview_block, unilever_demand
from backend.deps import TokenPayload, get_current_user, get_db
from backend.principals import PrincipalQuery, normalize_principal

router = APIRouter(prefix="/category-trends", tags=["category-trends"])

DEL_MONTE_REGROUP_PERIOD = "2025-01"

# {demand} is the Unilever demand relation for the request's data mode
# (backend/data_mode.py) — the _Real view's own name in real mode.
_QUERIES = {
    "unilever": """
        SELECT COALESCE(pd.category_path, 'UNCLASSIFIED') AS category, d.calendar_month AS period,
               SUM(d.net_amount) AS revenue
        FROM {demand} d JOIN Product_Dimension pd ON pd.product_key = d.product_key
        WHERE d.net_amount > 0
        GROUP BY 1, 2
    """,
    "delmonte": f"""
        SELECT pd.category_path AS category, s._period AS period, SUM(s.net_amount) AS revenue
        FROM SellOut_Fact_Real s JOIN Product_Dimension pd ON pd.product_key = s.product_key
        WHERE s._period >= '{DEL_MONTE_REGROUP_PERIOD}'
        GROUP BY 1, 2
    """,
}


def _next_month(period: str) -> str:
    y, m = map(int, period.split("-"))
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


def trends_for(db: Session, principal: str, mode: str = REAL) -> dict:
    rows = db.execute(text(_QUERIES[principal].format(demand=unilever_demand(mode)))).mappings().all()
    observed = sorted({r["period"] for r in rows})
    if not observed:
        return {"principal": principal, "observed_months": [], "categories": []}
    series: dict[str, dict[str, float]] = {}
    for r in rows:
        series.setdefault(r["category"], {})[r["period"]] = float(r["revenue"] or 0)

    # Projection months continue the calendar from the last observed month.
    ahead, p = [], observed[-1]
    for _ in range(PROJECTION_MONTHS):
        p = _next_month(p)
        ahead.append(p)

    categories = []
    for name, by_period in series.items():
        values = [by_period.get(m, 0.0) for m in observed]
        projection = project_category(values)
        categories.append({
            "category": name,
            "revenue_last_12": round(sum(values[-12:]), 2),
            "history": [{"period": m, "revenue": round(v, 2)} for m, v in zip(observed, values)],
            "projection_periods": ahead if projection.get("available") else [],
            **projection,
        })
    categories.sort(key=lambda c: c["revenue_last_12"], reverse=True)
    return {"principal": principal, "observed_months": observed, "categories": categories}


@router.get("")
def get_category_trends(
    principal: str | None = PrincipalQuery,
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> dict:
    scope = normalize_principal(principal)
    payload = {
        "method": {
            "name": "Theil–Sen trend line, Mann–Kendall significance (p < 0.05)",
            "window_months": TREND_WINDOW_MONTHS,
            "projection_months": PROJECTION_MONTHS,
            "min_points": MIN_POINTS,
            "note": "A trend projection, not a validated forecast.",
        },
        "principals": [trends_for(db, p, mode) for p in ([scope] if scope else ["unilever", "delmonte"])],
    }
    # The projection fits the last TREND_WINDOW_MONTHS (24) observed months,
    # all real, so preview lengthens the history without moving a projection.
    if mode == PREVIEW:
        payload["data_mode"] = preview_block(db)
    return payload
