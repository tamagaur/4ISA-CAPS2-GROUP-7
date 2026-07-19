"""
backend.schemas.bo_monitoring — Pydantic models for GET /bo-monitoring.

Phase 6 (CLAUDE.md Step 22):
TODO: Define BOMonitoringItem and BOMonitoringResponse Pydantic models.
      Fields: sku_id, product_name, period, bo_rate, bo_units, units_received.
"""

"""
backend.schemas.bo_monitoring — Pydantic models for GET /bo-monitoring.

Phase 6 (CLAUDE.md Step 22):
Fields: DEVIATES from the original TODO's (sku_id, product_name, period,
bo_rate, bo_units, units_received) — flagged, not silently changed.

analytics/db/schema.sql's own "OPEN QUESTION FOR YUAN" comment (SECTION 5)
already establishes why: BO/RMR returns are invoice-grain for Del Monte —
no SKU column exists anywhere upstream for this fact family (same
constraint as Sales/Purchase/SalesReturn, DEC-02). bo_monitoring_view is
computed at the grain the source data actually supports: principal /
region / period. A sku_id field here would be fabricated. This schema
mirrors that view exactly. Revisit together with schema.sql's open
question if Yuan decides this should be redefined as Unilever-only
SKU-level BO monitoring instead (Unilever_SKU_Demand_Fact does carry a
real SKU key).
"""
from __future__ import annotations

from pydantic import BaseModel


class BOMonitoringItem(BaseModel):
    principal: str  # 'unilever' | 'delmonte'
    region: str | None = None
    period: str  # 'YYYY-MM'
    bo_rate: float | None = None  # percent; null (not 0) when units_received is 0/unknown
    bo_units: float | None = None
    units_received: float | None = None


class BOMonitoringResponse(BaseModel):
    items: list[BOMonitoringItem]
    count: int
