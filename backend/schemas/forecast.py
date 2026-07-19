"""
backend.schemas.forecast — Pydantic models for GET /forecast/{sku_id}.

Phase 6 (CLAUDE.md Step 22):
TODO: Define ForecastResponse Pydantic model.
      Fields: sku_id, forecast_value, confidence_lower, confidence_upper,
              forecast_date, mape, model_params.
"""

"""
backend.schemas.forecast — Pydantic models for GET /forecast/{sku_id}.

Phase 6 (CLAUDE.md Step 22):
Fields: sku_id, forecast_value, confidence_lower, confidence_upper,
        forecast_date, mape, model_params.
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict


class ForecastResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())  # model_params below isn't a pydantic "model_" field

    sku_id: str
    forecast_value: float
    confidence_lower: float | None = None
    confidence_upper: float | None = None
    forecast_date: datetime.date
    mape: float | None = None
    model_params: dict | None = None  # SARIMA (p,d,q)(P,D,Q,s), stored as given
