"""
backend.schemas.recommendations — Pydantic models for GET /recommendations.

Phase 6 (CLAUDE.md Step 22):
Fields: sku_id, q_i, rop_i, ss_i, planning_cycle_date, status (accepted/dismissed/pending).
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel


class RecommendationItem(BaseModel):
    sku_id: str
    q_i: float
    rop_i: float
    ss_i: float
    planning_cycle_date: datetime.date
    status: str  # 'pending' | 'accepted' | 'dismissed'


class PaginatedRecommendations(BaseModel):
    items: list[RecommendationItem]
    page: int
    page_size: int
    total: int
