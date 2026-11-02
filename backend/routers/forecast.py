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
Monte's sales data has no SKU column, so a Del Monte request (scope
delmonte, or a code that resolves to a Del Monte product) is a 200 with
forecast: [] and blocked_reason saying so, never a 404.

404 if sku_id doesn't resolve to a Product_Dimension row in scope.
Forecast_Result may legitimately be empty for a resolved product (every
SKU outside Tier A, or one the runner hasn't reached) — that is NOT a
404, it's a 200 with forecast: [].
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.data_mode import (
    PREVIEW,
    demo_data_enabled,
    forecast_source,
    get_data_mode,
    predictive_preview,
    preview_block,
    unilever_demand,
)
from analytics.params import CALENDAR_FACTOR_SIGNED_OFF, FORECAST_INTERVAL_LEVEL_PCT, FORECAST_INTERVAL_Z
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import PrincipalQuery, normalize_principal, principal_clause
from backend import demo_data
from backend.schemas.forecast import ActualPoint, ForecastPoint, ForecastResponse
from backend.series_gaps import gap_note, unilever_points
from backend.response_cache import cached

# The band the forecast runner stores: forecast +/- CONFIDENCE_Z x the served
# model's holdout RMSE (scripts/run_baseline_forecast.py). Both read
# analytics.params: 1.645 is a two-sided ~90% normal band.
FORECAST_INTERVAL = {
    "z": FORECAST_INTERVAL_Z, "level_pct": FORECAST_INTERVAL_LEVEL_PCT,
    "basis": "the served model's holdout RMSE",
}

DEL_MONTE_NO_FORECAST = "No product-level forecast for Del Monte: its sales files have no product detail."

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/{sku_id}", response_model=ForecastResponse)
@cached("GET /forecast/{sku_id}")
def get_forecast(
    sku_id: str,
    principal: str | None = PrincipalQuery,
    category: str | None = Query(
        None,
        description="Del Monte category_path, for the demonstration series (DM_DEMO_ENABLED on only). "
                    "Ignored otherwise: Del Monte has no product-level forecast.",
    ),
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
    if normalize_principal(principal) == "delmonte" or (product_row and product_row["principal"] == "delmonte"):
        if demo_data_enabled(mode):
            # The labelled demonstration series and its MA3 forecast (schema demo; backend/demo_data.py): history with
            # each point's origin and reason, the one-step forecast with no accuracy figure and no band.
            demo = demo_data.series_points(db, "delmonte", category or sku_id)
            if demo is not None:
                fc = [f for f in demo_data.forecasts(db) if f["category"] == demo["key"]]
                body = ForecastResponse(
                    sku_id=sku_id, product_name=demo["key"], principal="delmonte",
                    forecast=[ForecastPoint(forecast_date=f["forecast_period"] + "-01", forecast_value=f["forecast_quantity"],
                                            status=f["status"], model_params={"method": f["method"], "demonstration": True})
                              for f in fc],
                ).model_dump(mode="json")
                body["actuals"] = demo["points"]
                for k in ("data_source", "demonstration", "demonstration_note", "origin_counts", "run", "gap_note"):
                    body[k] = demo[k]
                body["forecast_note"] = (None if fc else "No demonstration forecast: this series has no real observation "
                                                          "at the end of the window (2025-12).")
                return JSONResponse(body)
        return ForecastResponse(
            sku_id=sku_id,
            product_name=product_row["product_name"] if product_row else None,
            principal="delmonte",
            blocked_reason=DEL_MONTE_NO_FORECAST,
        )
    if demo_data_enabled(mode) and (normalize_principal(principal) == "unilever"
                                     or (product_row and product_row["principal"] == "unilever")):
        # The labelled demonstration series and its MA3 forecast (schema demo; backend/demo_data.py), the same
        # source as the chart (so charts and forecasts come from the same source, Kelvin 2026-10-16). Unilever's
        # REAL Forecast_Result is unaffected: this table is never read outside this toggle.
        demo = demo_data.series_points(db, "unilever", sku_id)
        if demo is not None:
            fc = demo_data.unilever_forecast(db, sku_id)
            body = ForecastResponse(
                sku_id=sku_id, product_name=product_row["product_name"] if product_row else None, principal="unilever",
                forecast=[ForecastPoint(forecast_date=fc["forecast_period"] + "-01", forecast_value=fc["forecast_quantity"],
                                        status=fc["status"], model_params={"method": fc["method"], "demonstration": True})]
                        if fc else [],
            ).model_dump(mode="json")
            body["actuals"] = demo["points"]
            for k in ("data_source", "demonstration", "demonstration_note", "origin_counts", "run", "gap_note"):
                body[k] = demo[k]
            body["forecast_note"] = (None if fc else "No demonstration forecast for this SKU: fewer than 3 real "
                                                      "months, or more than one blank-capture month in the window.")
            return JSONResponse(body)

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
            SELECT calendar_month, quantity_sold,
                   (SELECT MIN(calendar_month) FROM {demand}) AS series_start,
                   (SELECT MAX(calendar_month) FROM {demand}) AS series_end
            FROM {demand}
            WHERE product_key = :product_key
            ORDER BY calendar_month DESC
        """),
        {"product_key": product_key},
    ).mappings().all()
    # Chart points only (backend/series_gaps.py): a month with no row between the
    # first and last sale is 0 (no_sale), a blank quantity is null (blank_capture,
    # never 0), months outside the product's life are null. The forecast path
    # (build_series, the runner, the LP) does not read this.
    by_period = {r["calendar_month"]: _safe_float(r["quantity_sold"]) for r in actual_rows}
    grid = (actual_rows[0].get("series_start"), actual_rows[0].get("series_end")) if actual_rows else (None, None)
    points = unilever_points(by_period, *grid)
    actuals = [ActualPoint(**pt) for pt in points]

    response = ForecastResponse(
        sku_id=sku_id,
        product_name=product_row["product_name"],
        principal=product_row["principal"],
        actuals=actuals,
        forecast=forecast,
        interval=dict(FORECAST_INTERVAL),
        gap_note=gap_note(pt["reason"] for pt in points if pt["reason"]),
        calendar_signed_off=CALENDAR_FACTOR_SIGNED_OFF,
    )
    if mode != PREVIEW:
        return response
    block = preview_block(db, real_only=None if predictive_preview(mode) else ["forecast", "actuals"])
    return JSONResponse({**jsonable_encoder(response), "data_mode": block})

