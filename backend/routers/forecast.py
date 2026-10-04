"""
backend.routers.forecast — GET /forecast/{sku_id}

Returns a SKU's Forecast_Result rows plus its trailing actuals from
Unilever_SKU_Demand_Fact_Real. Since 2026-09-21 the runner
(scripts/run_baseline_forecast.py) serves one model per history-length bin
— MA3, TSB or the XGBoost + MA3 average, with MA3 as benchmark and
fallback (analytics/forecasting/router.py) — and records which one in
model_params. This endpoint reads Forecast_Result generically (no method
filter), so the routing needed no query change. Each point also carries
the row's `status` ('ok' | 'insufficient_data' | 'dead_sku') and holdout
`mase`, the served model's rolling one-step MASE (null when not 'ok').

`?principal=` scopes the sku_code lookup (codes aren't unique across
principals, see backend/principals.py); the response's `principal` is the
resolved product's own. Forecasts exist for Unilever Tier A only: Del
Monte's sales data has no SKU column, so its rows never resolve here.

404 if sku_id doesn't resolve to a Product_Dimension row in scope.
Forecast_Result may legitimately be empty for a resolved product (every
SKU outside Tier A, or one the runner hasn't reached) — that is NOT a
404, it's a 200 with forecast: [].
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.data_mode import (
    PREVIEW,
    forecast_source,
    get_data_mode,
    predictive_preview,
    preview_block,
    unilever_demand,
)
from analytics.params import FORECAST_INTERVAL_LEVEL_PCT, FORECAST_INTERVAL_Z
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import PrincipalQuery, principal_clause
from backend.schemas.forecast import ActualPoint, ForecastPoint, ForecastResponse
from backend.response_cache import cached

# The band the forecast runner stores: forecast +/- CONFIDENCE_Z x the served
# model's holdout RMSE (scripts/run_baseline_forecast.py). Both read
# analytics.params: 1.645 is a two-sided ~90% normal band.
FORECAST_INTERVAL = {
    "z": FORECAST_INTERVAL_Z, "level_pct": FORECAST_INTERVAL_LEVEL_PCT,
    "basis": "the served model's holdout RMSE",
}

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/{sku_id}", response_model=ForecastResponse)
@cached("GET /forecast/{sku_id}")
def get_forecast(
    sku_id: str,
    principal: str | None = PrincipalQuery,
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("forecast.view")),
) -> ForecastResponse:
    # Both principals again (2026-09-17) — see backend/principals.py.
    # Scoping the sku_code lookup matters because sku_code is NOT unique
    # across principals in product_dimension; without a scope the same
    # code could resolve to either principal's product row.
    scope_sql, scope_params = principal_clause(principal, "principal")
    product_row = db.execute(
        text(
            "SELECT product_key, product_name, principal FROM Product_Dimension "
            "WHERE sku_code = :sku_id" + scope_sql
        ),
        {"sku_id": sku_id, **scope_params},
    ).mappings().first()
    if product_row is None:
        scope_label = principal or "any principal"
        raise HTTPException(status_code=404, detail=f"No product found for '{sku_id}' ({scope_label})")

    product_key = product_row["product_key"]

    def _safe_float(val, default=None):
        if val is None:
            return default
        try:
            f = float(val)
            import math
            if math.isnan(f) or math.isinf(f):
                return default
            return f
        except (ValueError, TypeError):
            return default

    # Preview with built outputs (backend/data_mode.py): the five-year what-if
    # forecast, and the history it was made from — placeholder months included.
    # Otherwise the live forecast and the real history, in either mode.
    fc, fc_params = forecast_source(mode, "forecast_result")
    demand = "unilever_sku_demand_fact_real" if not predictive_preview(mode) else unilever_demand(mode)
    forecast_rows = db.execute(
        text(f"""
            SELECT forecast_date, forecast_value, confidence_lower, confidence_upper, mape, mase,
                   status, model_params
            FROM {fc}
            WHERE product_key = :product_key
            ORDER BY forecast_date
        """),
        {"product_key": product_key, **fc_params},
    ).mappings().all()
    forecast = [
        ForecastPoint(
            forecast_date=r["forecast_date"],
            forecast_value=_safe_float(r["forecast_value"], 0.0),
            confidence_lower=_safe_float(r["confidence_lower"]),
            confidence_upper=_safe_float(r["confidence_upper"]),
            mape=_safe_float(r["mape"]),
            mase=_safe_float(r["mase"]),
            status=r["status"],
            model_params=r["model_params"],
        )
        for r in forecast_rows
    ]

    actual_rows = db.execute(
        text(f"""
            SELECT calendar_month, quantity_sold
            FROM {demand}
            WHERE product_key = :product_key
            ORDER BY calendar_month DESC
        """),
        {"product_key": product_key},
    ).mappings().all()
    actuals = [
        ActualPoint(period=r["calendar_month"], quantity=_safe_float(r["quantity_sold"], 0.0))
        for r in reversed(actual_rows)
    ]

    response = ForecastResponse(
        sku_id=sku_id,
        product_name=product_row["product_name"],
        principal=product_row["principal"],
        actuals=actuals,
        forecast=forecast,
        interval=dict(FORECAST_INTERVAL),
    )
    if mode != PREVIEW:
        return response
    block = preview_block(db, real_only=None if predictive_preview(mode) else ["forecast", "actuals"])
    return JSONResponse({**jsonable_encoder(response), "data_mode": block})

