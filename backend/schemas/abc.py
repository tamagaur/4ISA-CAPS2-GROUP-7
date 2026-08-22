"""
backend.schemas.abc — Pydantic models for GET /abc.

Phase 6 (CLAUDE.md Step 22):
Fields: sku_id, product_name, tier (A/B/C), revenue_share, cumulative_share.

NOTE on sku_id: Product_Dimension covers two kinds of product identity
(schema.sql) — Unilever rows carry a real sku_code, Del Monte rows carry
a category_path instead (DEC-03: Del Monte forecasts at category grain,
no per-SKU data exists). `sku_id` here is COALESCE(sku_code, category_path)
— for Del Monte rows it is a category path, not a SKU code. Flagged here
rather than silently presented as a SKU for both principals.
"""
from __future__ import annotations

from pydantic import BaseModel


class ABCItem(BaseModel):
    sku_id: str
    product_name: str | None = None
    principal: str
    tier: str  # 'A' | 'B' | 'C'
    revenue_share: float | None = None
    cumulative_share: float | None = None
    boundary_flag: bool = False  # backlog #43 — near a tier cutoff, margin unconfirmed vs manuscript Sec.3.6
    current_stock: float = 0
    stock_status: str  # 'IN STOCK' | 'LOW' | 'CRITICAL' — same thresholds as GET /inventory/current


class TierSummary(BaseModel):
    """Backlog #44: procurement wants to see cumulative revenue
    contribution PER TIER, not just per-SKU cumulative_share — this
    rolls that up so the dashboard doesn't have to sum client-side."""
    tier: str
    sku_count: int
    revenue_share_total: float  # sum of this tier's SKUs' individual revenue_share


class ABCResponse(BaseModel):
    items: list[ABCItem]
    count: int
    classification_period: str | None = None  # 'YYYY-MM'
    tier_summary: list[TierSummary] = []
