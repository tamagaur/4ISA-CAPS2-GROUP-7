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

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.forecasting.category_trend import (
    MANN_KENDALL_ALPHA, PROJECTION_MONTHS, TRAILING_MONTHS, method_constants, project_category,
)
from backend.data_mode import PREVIEW, REAL, get_data_mode, preview_block, unilever_demand
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import PrincipalQuery, normalize_principal
from backend.response_cache import cached
from backend.series_gaps import (
    REASON_CATEGORY_ABSENT, REASON_NO_SALE, REASON_NOT_COLLECTED, REASON_RETURNS_EXCEEDED_SALES, gap_note,
    month_range,
)

router = APIRouter(prefix="/category-trends", tags=["category-trends"])

DEL_MONTE_REGROUP_PERIOD = "2025-01"

# {demand} is the Unilever demand relation for the request's data mode
# (backend/data_mode.py) — the _Real view's own name in real mode.
_QUERIES = {
    # No WHERE filter (B4, 2026-10-16): a category-month where every row's net_amount is <= 0
    # (returns matched or exceeded sales) must still show up here, with revenue 0, so it can be
    # told apart from a month with no row at all. revenue = SUM(GREATEST(net_amount, 0)), the
    # same number the old `WHERE net_amount > 0` filter produced (a row <= 0 contributes 0
    # either way); `positive_rows` says whether any row was actually a net sale.
    "unilever": """
        SELECT COALESCE(pd.category_path, 'UNCLASSIFIED') AS category, d.calendar_month AS period,
               SUM(GREATEST(d.net_amount, 0)) AS revenue,
               COUNT(*) FILTER (WHERE d.net_amount > 0) AS positive_rows
        FROM {demand} d JOIN Product_Dimension pd ON pd.product_key = d.product_key
        GROUP BY 1, 2
    """,
    "delmonte": f"""
        SELECT pd.category_path AS category, s._period AS period, SUM(s.net_amount) AS revenue
        FROM SellOut_Fact_Real s JOIN Product_Dimension pd ON pd.product_key = s.product_key
        WHERE s._period >= '{DEL_MONTE_REGROUP_PERIOD}'
        GROUP BY 1, 2
    """,
}


def _series_start(principal: str) -> str | None:
    """The first month a principal's series may use, when it is cut: Del
    Monte's categories start at the regrouping, so the page can say so from
    this value instead of naming the month in its own copy."""
    return DEL_MONTE_REGROUP_PERIOD if principal == "delmonte" else None


def _next_month(period: str) -> str:
    y, m = map(int, period.split("-"))
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


def trends_for(
    db: Session, principal: str, mode: str = REAL,
    start_period: str | None = None, period: str | None = None,
) -> dict:
    rows = db.execute(text(_QUERIES[principal].format(demand=unilever_demand(mode)))).mappings().all()
    observed = sorted({
        r["period"] for r in rows
        if (start_period is None or r["period"] >= start_period) and (period is None or r["period"] <= period)
    })
    if not observed:
        return {
            "principal": principal, "observed_months": [], "categories": [],
            "series_start": _series_start(principal), "start_period": start_period, "end_period": period,
        }
    series: dict[str, dict[str, float]] = {}
    # Unilever only (B4, 2026-10-16): a category-month with rows but no positive one
    # (returns matched or exceeded sales) — distinct from no row at all, REASON_NO_SALE below.
    returns_exceeded: dict[str, set[str]] = {}
    for r in rows:
        series.setdefault(r["category"], {})[r["period"]] = float(r["revenue"] or 0)
        if principal == "unilever" and r["positive_rows"] == 0:
            returns_exceeded.setdefault(r["category"], set()).add(r["period"])

    # Projection months continue the calendar from the last observed month.
    ahead, p = [], observed[-1]
    for _ in range(PROJECTION_MONTHS):
        p = _next_month(p)
        ahead.append(p)

    # Chart points only: the history marks a zero that is not a recorded zero with a
    # `reason` (backend/series_gaps.py). The values, and so the projection, are unchanged.
    absent_reason = REASON_NO_SALE if principal == "unilever" else REASON_CATEGORY_ABSENT
    reasons_used: set[str] = set()
    categories = []
    for name, by_period in series.items():
        values = [by_period.get(m, 0.0) for m in observed]
        projection = project_category(values)
        history = []
        for m, v in zip(observed, values):
            point = {"period": m, "revenue": round(v, 2)}
            if m not in by_period:
                point["reason"] = absent_reason
                reasons_used.add(absent_reason)
            elif m in returns_exceeded.get(name, ()):
                point["reason"] = REASON_RETURNS_EXCEEDED_SALES
                reasons_used.add(REASON_RETURNS_EXCEEDED_SALES)
            history.append(point)
        categories.append({
            "category": name,
            # The field keeps its name for its callers; the span is
            # TRAILING_MONTHS, the same one the method block reports.
            "revenue_last_12": round(sum(values[-TRAILING_MONTHS:]), 2),
            "history": history,
            "projection_periods": ahead if projection.get("available") else [],
            **projection,
        })
    categories.sort(key=lambda c: c["revenue_last_12"], reverse=True)
    # Calendar months inside the observed range that the principal has no data for at
    # all are left out of the series (above); name them instead of dropping them silently.
    skipped = [m for m in month_range(observed[0], observed[-1]) if m not in set(observed)]
    out = {"principal": principal, "observed_months": observed, "categories": categories,
           "series_start": _series_start(principal), "start_period": observed[0], "end_period": observed[-1]}
    if skipped:
        out["skipped_months"] = [{"period": m, "reason": REASON_NOT_COLLECTED} for m in skipped]
        reasons_used.add(REASON_NOT_COLLECTED)
    note = gap_note(reasons_used)
    if note:
        out["gap_note"] = note
    return out


@router.get("")
@cached("GET /category-trends")
def get_category_trends(
    period: str | None = Query(
        None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description=(
            "'YYYY-MM'. The shared date-range picker's applied end month/year. "
            "Restricts the observed history to months at or before it. Omit to "
            "use every observed month, unbounded (current behaviour)."
        ),
    ),
    start_period: str | None = Query(
        None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description=(
            "'YYYY-MM'. The shared date-range picker's applied START month/year. "
            "Restricts the observed history to months at or after it. Omit to "
            "use every observed month, unbounded (current behaviour)."
        ),
    ),
    principal: str | None = PrincipalQuery,
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("category_trends.view")),
) -> dict:
    scope = normalize_principal(principal)
    payload = {
        "method": {
            "name": f"Theil–Sen trend line, Mann–Kendall significance (p < {MANN_KENDALL_ALPHA})",
            **method_constants(),
            "note": "A trend projection, not a validated forecast.",
        },
        "principals": [
            trends_for(db, p, mode, start_period, period) for p in ([scope] if scope else ["unilever", "delmonte"])
        ],
    }
    # The projection fits the last TREND_WINDOW_MONTHS (24) observed months,
    # all real, so preview lengthens the history without moving a projection.
    if mode == PREVIEW:
        payload["data_mode"] = preview_block(db)
    return payload
