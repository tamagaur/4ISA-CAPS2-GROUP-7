"""
backend.routers.forecast — GET /forecast/{sku_id}

Returns SARIMA forecast output for a SKU (Unilever) or category (Del Monte)
from Forecast_Result, plus trailing actuals for Unilever SKUs from
Unilever_SKU_Demand_Fact (Del Monte has no SKU-level demand fact — DEC-03).

404 if sku_id/principal doesn't resolve to a Product_Dimension row.
Forecast_Result may legitimately be empty for a resolved product (the
analytics/ SARIMA pipeline hasn't been run against every SKU, or at all,
yet) — that is NOT a 404, it's a 200 with forecast: [].
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.schemas.forecast import ActualPoint, ForecastPoint, ForecastResponse

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/{sku_id}", response_model=ForecastResponse)
def get_forecast(
    sku_id: str,
    principal: str = Query(..., description="'unilever' or 'delmonte' — required to disambiguate sku_id vs category_path"),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> ForecastResponse:
    if principal not in ("unilever", "delmonte"):
        raise HTTPException(status_code=400, detail="principal must be 'unilever' or 'delmonte'")

    product_row = db.execute(
        text("""
            SELECT product_key, product_name
            FROM Product_Dimension
            WHERE principal = :principal AND (sku_code = :sku_id OR category_path = :sku_id)
        """),
        {"principal": principal, "sku_id": sku_id},
    ).mappings().first()
    if product_row is None:
        raise HTTPException(status_code=404, detail=f"No {principal} product found for '{sku_id}'")

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

    actuals: list[ActualPoint] = []
    if principal == "unilever":
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
    elif principal == "delmonte":
        actual_rows = db.execute(
            text("""
                SELECT _period, SUM(quantity) as quantity_sold
                FROM SellOut_Fact_Real
                WHERE product_key = :product_key
                GROUP BY _period
                ORDER BY _period DESC
            """),
            {"product_key": product_key},
        ).mappings().all()
        actuals = [
            ActualPoint(period=r["_period"], quantity=_safe_float(r["quantity_sold"], 0.0))
            for r in reversed(actual_rows)
        ]

    return ForecastResponse(
        sku_id=sku_id,
        product_name=product_row["product_name"],
        principal=principal,
        actuals=actuals,
        forecast=forecast,
    )

