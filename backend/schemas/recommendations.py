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
                    In PIECES since 2026-09-23 (see current_stock), so it is
                    now a real shortfall quantity, not an index.
  priority_score  — revenue_share x stockout_gap, the "revenue at risk"
                    ranking key. Both inputs are now on a consistent basis
                    (revenue share x a piece shortfall) — before 2026-09-23
                    the gap mixed cases and pieces, so the ranking is no
                    longer merely ordinal. None when either input is
                    missing — such rows are unranked, never ranked as zero.
  days_of_cover   — stock at cost (₱) / average daily sales value (₱/day),
                    the same peso basis GET /dashboard's weeks_of_cover uses,
                    precisely BECAUSE stock (cases) and demand (pieces)
                    can't be divided directly. None with cover_blocked_reason
                    whenever either side is unavailable.
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel, Field


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
    # PIECES since 2026-09-23 (backend/stock_units.py), the same unit as
    # rop_i/ss_i/q_i — cases x pack_size + the loose remainder. None when
    # there is no snapshot row, or no usable pack size to convert with.
    current_stock: float | None = None
    current_stock_cases: float | None = None  # the raw snapshot figure, for display
    urgency: str  # 'CRITICAL' | 'URGENT' | 'PLANNED' | 'NO DATA' — derived from current_stock vs rop_i
    # Why urgency is 'NO DATA': no snapshot row, or no usable pack size.
    stock_blocked_reason: str | None = None
    revenue_share: float | None = None
    # The product's tier in the latest ABC run (None when that run did not
    # rank it). The LP plans Category A, but a cycle outlives the ABC run it
    # was solved against, so a row can be for a SKU that is no longer A.
    tier: str | None = None
    stockout_gap: float | None = None
    priority_score: float | None = None
    days_of_cover: float | None = None
    cover_blocked_reason: str | None = None


class RecommendationsResponse(BaseModel):
    items: list[RecommendationItem]
    count: int
    # The LP cycle these rows belong to, and how many pending rows from
    # earlier runs were withheld so a superseded cycle can't be acted on
    # (backend/lp_cycle.py). Optional so older fixtures still validate.
    planning_cycle_date: str | None = None
    superseded_count: int = 0
    # {cycle_date, lp_generated_at, forecast_generated_at, is_stale,
    #  superseded_pending_count, reason} — lets the UI warn that q_i/rop_i
    #  were solved against forecasts that have since been replaced.
    freshness: dict | None = None
    # {weights: {cost, service_level, storage}, service_level_pct, z_score} —
    # the solver's own settings (backend/lp_cycle.lp_model_info), so the
    # detail view states what the LP does rather than a copy of it.
    lp_model: dict | None = None


class RecommendationDecision(BaseModel):
    status: str  # 'accepted' | 'dismissed'
    # The admin's reason from the decision dialog; it goes into the audit log
    # entry the server writes for the decision.
    reason: str | None = Field(default=None, max_length=500)
