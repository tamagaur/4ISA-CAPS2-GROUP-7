"""
backend.schemas.sku — Pydantic models for GET/POST/PATCH /sku.

sku_id is COALESCE(sku_code, category_path), same convention as
backend/schemas/abc.py — Del Monte rows carry a category_path, not a real
SKU code (DEC-03). current_stock comes from the latest Inventory_Fact_Real
period; reorder_point from the latest pending LP_Recommendation row; tier
from the latest ABC_Classification period. All three are read-only
(computed elsewhere, not stored on Product_Dimension) and simply omitted
when no matching row exists yet for a new/unclassified product.
"""
from __future__ import annotations

from pydantic import BaseModel


class SKUItem(BaseModel):
    product_key: int
    sku_id: str
    product_name: str | None = None
    principal: str
    pack_size: str | None = None
    brand: str | None = None
    unit_price: float | None = None
    lead_time_days: int | None = None
    status: str  # 'ACTIVE' | 'DISABLED'
    notes: str | None = None
    current_stock: float | None = None
    reorder_point: float | None = None
    tier: str | None = None  # 'A' | 'B' | 'C', this product's most recent ABC run
    # The period `tier` was computed in ('YYYY-MM'). Travels with the tier
    # because it is a LAST-KNOWN classification, not necessarily a current
    # one — a SKU with no sales last month keeps its previous category, and
    # the consumer needs the date to say how stale that is.
    tier_period: str | None = None


class SKUListResponse(BaseModel):
    items: list[SKUItem]
    count: int


class SKUCreate(BaseModel):
    sku_code: str
    principal: str  # 'unilever' | 'delmonte'
    product_name: str
    pack_size: str | None = None
    brand: str | None = None
    unit_price: float | None = None
    lead_time_days: int | None = None
    notes: str | None = None


class SKUUpdate(BaseModel):
    product_name: str | None = None
    pack_size: str | None = None
    brand: str | None = None
    unit_price: float | None = None
    lead_time_days: int | None = None
    status: str | None = None
    notes: str | None = None
