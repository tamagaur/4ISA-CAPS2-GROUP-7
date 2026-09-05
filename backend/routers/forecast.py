"""
backend.routers.forecast — GET /forecast/{sku_id}

Returns MA3 (3-month moving average) forecast output for a Unilever SKU
from Forecast_Result, plus trailing actuals from Unilever_SKU_Demand_Fact.
Retired SARIMA in favor of MA3 (see analytics/forecasting/baseline.py's
module docstring for the evidence) — this endpoint reads Forecast_Result
generically (no method filter), so it needed no query change, only this
docstring update.

UNILEVER ONLY (2026-09): Del Monte has been dropped from this app's
scope — there is no more `?principal=` param; every lookup is hardcoded
to `principal = 'unilever'` and resolves sku_id via sku_code only (Del
Monte's category_path lookup and its SellOut_Fact_Real actuals branch
are gone, not filtered — SellOut_Fact_Real is Del Monte-only at the
schema level, see backend/routers/dashboard.py's module docstring).

404 if sku_id doesn't resolve to a Unilever Product_Dimension row.
Forecast_Result may legitimately be empty for a resolved product (the
scripts/run_baseline_forecast.py runner hasn't been run against every
SKU, or at all, yet) — that is NOT a 404, it's a 200 with forecast: [].
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.schemas.forecast import ActualPoint, ForecastPoint, ForecastResponse

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/{sku_id}", response_model=ForecastResponse)
def get_forecast(
    sku_id: str,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> ForecastResponse:
    product_row = db.execute(
        text("""
            SELECT product_key, product_name
            FROM Product_Dimension
            WHERE principal = 'unilever' AND sku_code = :sku_id
        """),
        {"sku_id": sku_id},
    ).mappings().first()
    if product_row is None:
        raise HTTPException(status_code=404, detail=f"No unilever product found for '{sku_id}'")

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

    forecast_rows = db.execute(
        text("""
            SELECT forecast_date, forecast_value, confidence_lower, confidence_upper, mape, model_params
            FROM forecast_result
            WHERE product_key = :product_key
            ORDER BY forecast_date
        """),
        {"product_key": product_key},
    ).mappings().all()
    forecast = [
        ForecastPoint(
            forecast_date=r["forecast_date"],
            forecast_value=_safe_float(r["forecast_value"], 0.0),
            confidence_lower=_safe_float(r["confidence_lower"]),
            confidence_upper=_safe_float(r["confidence_upper"]),
            mape=_safe_float(r["mape"]),
            model_params=r["model_params"],
        )
        for r in forecast_rows
    ]

    actual_rows = db.execute(
        text("""
            SELECT calendar_month, quantity_sold
            FROM unilever_sku_demand_fact_real
            WHERE product_key = :product_key
            ORDER BY calendar_month DESC
        """),
        {"product_key": product_key},
    ).mappings().all()
    actuals = [
        ActualPoint(period=r["calendar_month"], quantity=_safe_float(r["quantity_sold"], 0.0))
        for r in reversed(actual_rows)
    ]

    return ForecastResponse(
        sku_id=sku_id,
        product_name=product_row["product_name"],
        principal="unilever",
        actuals=actuals,
        forecast=forecast,
    )

