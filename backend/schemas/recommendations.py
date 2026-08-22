"""
backend.schemas.recommendations — Pydantic models for GET/PATCH /recommendations.

Fields are limited to what LP_Recommendation + Product_Dimension +
Inventory_Fact_Real actually carry (analytics/db/schema.sql). No unit_cost,
lead_time_days, or supplier-cost breakdown exists anywhere in the schema —
those fields do not appear here rather than being fabricated.
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
    current_stock: float = 0
    urgency: str  # 'CRITICAL' | 'URGENT' | 'PLANNED' — derived from current_stock vs rop_i


class RecommendationsResponse(BaseModel):
    items: list[RecommendationItem]
    count: int


class RecommendationDecision(BaseModel):
    status: str  # 'accepted' | 'dismissed'
