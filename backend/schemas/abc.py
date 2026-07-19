"""
backend.schemas.abc — Pydantic models for GET /abc.

Phase 6 (CLAUDE.md Step 22):
TODO: Define ABCItem and ABCResponse Pydantic models.
      Fields: sku_id, product_name, tier (A/B/C), revenue_share, cumulative_share.
"""


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
    tier: str  # 'A' | 'B' | 'C'
    revenue_share: float | None = None
    cumulative_share: float | None = None


class ABCResponse(BaseModel):
    items: list[ABCItem]
    count: int
    classification_period: str | None = None  # 'YYYY-MM'
