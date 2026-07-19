"""
backend.schemas.inventory — Pydantic models for GET /inventory/current.

Phase 6 (CLAUDE.md Step 22):
TODO: Define InventoryItem and InventoryResponse Pydantic models.
      Fields: sku_id, product_name, current_stock, unit, last_updated.
"""

"""
backend.schemas.inventory — Pydantic models for GET /inventory/current.

Phase 6 (CLAUDE.md Step 22):
Fields: sku_id, product_name, current_stock, unit, last_updated.

NOTE: `unit` is always null. Inventory_Fact (analytics/db/schema.sql) has
no unit-of-measure column — the source files never carried one. Left
null (not fabricated as e.g. "pcs") per ARCHITECTURE.md principle #1.
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel


class InventoryItem(BaseModel):
    sku_id: str
    product_name: str | None = None
    current_stock: float | None = None
    unit: str | None = None
    last_updated: datetime.date


class InventoryResponse(BaseModel):
    items: list[InventoryItem]
    count: int
