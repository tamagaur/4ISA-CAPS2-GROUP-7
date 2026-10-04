"""
backend.routers.decomposition — GET /decomposition?sku=

STL decomposition of one Unilever SKU's monthly demand (trend + seasonal +
remainder): the analytical mapping's D4. Computed on request from
Unilever_SKU_Demand_Fact_Real by analytics/forecasting/decomposition.py —
nothing stored, so it always reflects the loaded history.

The series is zero-filled from the SKU's first month on record to the
latest Unilever month (a month with no row is a zero-sale month, the same
convention as the forecast runner's build_series). Del Monte has no SKU
series (DEC-03), so a Del Monte product is a 404 here, like GET /forecast.

X-Data-Mode: preview reads the SKU's 2021-22 placeholder months too, so the
series (and the seasonal estimate) starts in 2021 (backend/data_mode.py).

yearly_pattern (2026-10-04) is the seasonality LABEL: "Repeats yearly",
"No reliable yearly pattern" or "Not enough history (needs 24 months)",
from the lag-12 autocorrelation test (analytics/forecasting/decomposition.
yearly_pattern). It replaces the panel's "Strong seasonality" band over STL
strength, which reads noise as seasonal at our lengths. It is always worked
out on the real series, in preview mode too: a label is a claim about SSM's
sales, so placeholder months never feed it (CLAUDE.md hard rule 2).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.forecasting.decomposition import MIN_MONTHS, PERIOD, stl_summary, yearly_pattern
from backend.data_mode import PREVIEW, REAL, get_data_mode, preview_block, unilever_demand
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import PrincipalQuery, principal_clause
from backend.response_cache import cached

router = APIRouter(prefix="/decomposition", tags=["decomposition"])


def _next_month(period: str) -> str:
    y, m = map(int, period.split("-"))
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


def _monthly_series(db: Session, demand: str, product_key) -> tuple[list[str], list[float]]:
    """('YYYY-MM' periods, pieces) from the product's first month on record to
    the latest month in `demand`, a month with no row as 0."""
    rows = db.execute(
        text(f"""
            SELECT calendar_month AS period, SUM(quantity_sold) AS qty
            FROM {demand} WHERE product_key = :product_key
            GROUP BY calendar_month ORDER BY calendar_month
        """),
        {"product_key": product_key},
    ).mappings().all()
    latest = db.execute(text(f"SELECT MAX(calendar_month) FROM {demand}")).scalar()
    by_period = {r["period"]: float(r["qty"] or 0) for r in rows}
    periods: list[str] = []
    if rows and latest:
        p = rows[0]["period"]
        while p <= latest:
            periods.append(p)
            p = _next_month(p)
    return periods, [by_period.get(p, 0.0) for p in periods]


@router.get("")
@cached("GET /decomposition")
def get_decomposition(
    sku: str = Query(..., description="Product_Dimension.sku_code"),
    principal: str | None = PrincipalQuery,
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("forecast.view", "lp.view")),
) -> dict:
    scope_sql, scope_params = principal_clause(principal, "principal")
    demand = unilever_demand(mode)
    product = db.execute(
        text("SELECT product_key, principal FROM Product_Dimension WHERE sku_code = :sku AND principal = 'unilever'" + scope_sql),
        {"sku": sku, **scope_params},
    ).mappings().first()
    if product is None:
        raise HTTPException(status_code=404, detail=f"No Unilever SKU '{sku}' in scope — STL needs a SKU-level series.")

    periods, values = _monthly_series(db, demand, product["product_key"])
    summary = stl_summary(periods, values)
    real_values = values if demand == unilever_demand(REAL) else _monthly_series(
        db, unilever_demand(REAL), product["product_key"])[1]
    payload = {"sku_id": sku, "method": {"name": "STL", "period": PERIOD, "robust": True, "min_months": MIN_MONTHS},
               **summary, "yearly_pattern": yearly_pattern(real_values)}
    if mode == PREVIEW:
        payload["data_mode"] = preview_block(db)
    return payload
