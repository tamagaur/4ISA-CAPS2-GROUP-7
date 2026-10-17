"""
backend.schemas.sku — Pydantic models for GET/POST/PATCH /sku.

sku_id is COALESCE(sku_code, category_path), same convention as
backend/schemas/abc.py — Del Monte rows carry a category_path, not a real
SKU code (DEC-03). current_stock is in PIECES at the product's own
principal's latest Inventory_Fact_Real snapshot (current_stock_cases is the
same stock in cases); reorder_point, also pieces, comes from the LP's current
cycle; tier from the latest ABC_Classification period. All are read-only
(computed elsewhere, not stored on Product_Dimension) and simply omitted
when no matching row exists yet for a new/unclassified product.
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel


class SKUItem(BaseModel):
    product_key: int
    sku_id: str
    product_name: str | None = None
    principal: str
    # 'sku' (an item code) or 'category' (a Del Monte sell-out category,
    # DEC-03). Del Monte is ranked by category, so its item codes are never
    # classified one by one; the page counts the two apart.
    grain: str | None = None
    pack_size: str | None = None
    brand: str | None = None
    unit_price: float | None = None
    # Cost per piece in pesos (what SSM pays), migration 0045; None without a
    # cost row and a numeric pack size. Read-only: not in SKUCreate/SKUUpdate.
    unit_cost: float | None = None
    lead_time_days: int | None = None
    status: str  # 'ACTIVE' | 'DISABLED'
    notes: str | None = None
    # Pieces; None when there is no stock row, or no usable pack size to
    # convert the warehouse's case count (current_stock_cases is still set).
    current_stock: float | None = None
    current_stock_cases: float | None = None
    reorder_point: float | None = None
    tier: str | None = None  # 'A' | 'B' | 'C', this product's most recent ABC run
    # The period `tier` was computed in ('YYYY-MM'). Travels with the tier
    # because it is a LAST-KNOWN classification, not necessarily a current
    # one — a SKU with no sales last month keeps its previous category, and
    # the consumer needs the date to say how stale that is.
    tier_period: str | None = None
    # The day the stock above was counted: MAX(snapshot_date) of this
    # product's principal's latest snapshot (routers/sku.py's
    # STOCK_COUNT_DATE_SQL). Unilever's "Mar 2026" file -> 2026-04-06. Set
    # whenever the principal has any stock count, even if this product has
    # no row in it.
    stock_count_date: datetime.date | None = None


class SKUListResponse(BaseModel):
    items: list[SKUItem]
    count: int
    # {principal: day its latest stock count was taken}, for the principals
    # in the list — what the page's stock column header states.
    stock_count_dates: dict[str, datetime.date] = {}
    # The LP cycle reorder_point comes from (a month's first day). None
    # without lp.view, like reorder_point itself, or when there is no cycle.
    planning_cycle_date: datetime.date | None = None
    # {principal display name: 'YYYY-MM'} — each principal's latest ABC run.
    tier_a_periods: dict[str, str] = {}


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
