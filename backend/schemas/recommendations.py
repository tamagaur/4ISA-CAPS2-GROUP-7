"""
backend.schemas.recommendations — Pydantic models for GET/PATCH /recommendations.

Fields are limited to what LP_Recommendation + Product_Dimension +
Inventory_Fact_Real (+ ABC_Classification / Unilever_SKU_Demand_Fact_Real
for the ranking and cover fields added 2026-09-18) actually carry
(analytics/db/schema.sql). No unit_cost, lead_time_days, or supplier-cost
breakdown exists anywhere in the schema — those fields do not appear here
rather than being fabricated.

2026-09-18 — impact ranking + cover (see backend/routers/recommendations.py
for the derivations and the unit caveats):
  current_stock   — now None (not 0) when Inventory_Fact_Real has no row
                    for the product at the latest snapshot. It used to
                    COALESCE to 0, which _to_item then read as CRITICAL —
                    "no stock record" and "confirmed empty" are different
                    facts. urgency is 'NO DATA' in that case.
  revenue_share   — the SKU's share of period revenue at its latest
                    single-period ABC run; None when never classified.
  stockout_gap    — max(0, rop_i - current_stock); None when stock unknown.
  priority_score  — revenue_share x stockout_gap, the "revenue at risk"
                    ranking key. A ranking index only, NOT pesos: rop_i is
                    on the demand series' piece scale while quantity_on_hand
                    is in cases (see the router docstring), so its absolute
                    value is not a quantity of anything. None when either
                    input is missing — such rows are unranked, never
                    ranked as zero.
  days_of_cover   — stock at cost (₱) / average daily sales value (₱/day),
                    the same peso basis GET /dashboard's weeks_of_cover uses,
                    precisely BECAUSE stock (cases) and demand (pieces)
                    can't be divided directly. None with cover_blocked_reason
                    whenever either side is unavailable.
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel


class RecommendationItem(BaseModel):
    recommendation_key: int
    sku_id: str
    product_name: str | None = None
    principal: str
    planning_cycle_date: datetime.date
    q_i: float  # recommended order quantity
    rop_i: float  # reorder point
    ss_i: float  # safety stock
    status: str  # 'pending' | 'accepted' | 'dismissed'
    current_stock: float | None = None  # None = no Inventory_Fact_Real row at the latest snapshot
    urgency: str  # 'CRITICAL' | 'URGENT' | 'PLANNED' | 'NO DATA' — derived from current_stock vs rop_i
    revenue_share: float | None = None
    stockout_gap: float | None = None
    priority_score: float | None = None
    days_of_cover: float | None = None
    cover_blocked_reason: str | None = None


class RecommendationsResponse(BaseModel):
    items: list[RecommendationItem]
    count: int


class RecommendationDecision(BaseModel):
    status: str  # 'accepted' | 'dismissed'
