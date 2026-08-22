"""
backend.schemas.forecast — Pydantic models for GET /forecast/{sku_id}.

Returns the full Forecast_Result horizon for a SKU/category (not just the
latest point — the unique key on Forecast_Result is (product_key,
forecast_date), so a single SARIMA run can produce several forecast_date
rows, and the UI needs the whole horizon to draw a chart) plus, for
Unilever SKUs only, trailing actuals from Unilever_SKU_Demand_Fact.
Del Monte has no SKU-level demand fact (DEC-03 — category grain only), so
actuals is always [] for a Del Monte category_path.
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
    model_params: dict | None = None  # SARIMA (p,d,q)(P,D,Q,s), stored as given


class ActualPoint(BaseModel):
    period: str  # 'YYYY-MM'
    quantity: float


class ForecastResponse(BaseModel):
    sku_id: str
    product_name: str | None = None
    principal: str
    actuals: list[ActualPoint] = []
    forecast: list[ForecastPoint] = []
