"""
backend.schemas.forecast — Pydantic models for GET /forecast/{sku_id}.

Returns the full Forecast_Result horizon for a SKU (not just the latest
point — the unique key on Forecast_Result is (product_key, forecast_date),
so a forecast run can in principle produce several forecast_date rows,
and the UI needs the whole horizon to draw a chart), plus trailing
actuals from Unilever_SKU_Demand_Fact. In practice the runner
(one served model per history-length bin, scripts/run_baseline_forecast.py — see analytics/forecasting/router.py) writes exactly one forecast_date row
per product (one-step-ahead), so `forecast` is currently always a
single-element list — this schema stays list-shaped rather than a bare
point so a future multi-step method doesn't need a response-shape change.
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict


class ForecastPoint(BaseModel):
    model_config = ConfigDict(protected_namespaces=())  # model_params isn't a pydantic "model_" field

    forecast_date: datetime.date
    forecast_value: float
    confidence_lower: float | None = None
    confidence_upper: float | None = None
    mape: float | None = None  # percent; the served model's rolling one-step holdout MAPE
    mase: float | None = None  # same holdout, scaled error; null unless status is 'ok'
    status: str | None = None  # 'ok' | 'insufficient_data' (provisional average) | 'dead_sku' (zero, no order)
    model_params: dict | None = None  # method-specific provenance (served model, bin, MA3 benchmark, holdout metrics), stored as given


class ActualPoint(BaseModel):
    period: str  # 'YYYY-MM'
    quantity: float


class ForecastResponse(BaseModel):
    sku_id: str
    product_name: str | None = None
    principal: str
    actuals: list[ActualPoint] = []
    forecast: list[ForecastPoint] = []
    # How confidence_lower/upper were made: {z, level_pct, basis} — forecast
    # +/- z x the served model's holdout RMSE, floored at 0. Sent so the page
    # names the band's level instead of calling it a bare "confidence
    # interval".
    interval: dict | None = None
    # Why there is no forecast at all for this request (Del Monte: no
    # product-level sales), None otherwise.
    blocked_reason: str | None = None
