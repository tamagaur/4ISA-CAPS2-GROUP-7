"""
backend.schemas.forecast — Pydantic models for GET /forecast/{sku_id}.

Returns the full Forecast_Result horizon for a SKU (not just the latest
point — the unique key on Forecast_Result is (product_key, forecast_date),
so a forecast run can in principle produce several forecast_date rows,
and the UI needs the whole horizon to draw a chart), plus trailing
actuals from Unilever_SKU_Demand_Fact. In practice the deployed method
(MA3, scripts/run_baseline_forecast.py — SARIMA was retired, see
analytics/forecasting/baseline.py) writes exactly one forecast_date row
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
    mape: float | None = None
    model_params: dict | None = None  # method-specific provenance (e.g. MA3's window/holdout metrics), stored as given


class ActualPoint(BaseModel):
    period: str  # 'YYYY-MM'
    quantity: float


class ForecastResponse(BaseModel):
    sku_id: str
    product_name: str | None = None
    principal: str
    actuals: list[ActualPoint] = []
    forecast: list[ForecastPoint] = []
