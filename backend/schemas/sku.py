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

import re

from pydantic import BaseModel, field_validator


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


# The most a name, brand or note can hold, and the one shape a pack size can take. Names appear on every page and
# GET /sku carries all of them (about 0.94 MB today); a pack size that is not a positive number silently turns off
# the whole-case check and the stock-in-pieces conversion for that SKU (backend/stock_units.PACK_SIZE_NUMERIC).
NAME_MAX, BRAND_MAX, NOTES_MAX = 200, 100, 2000
_PACK = re.compile(r"[0-9]+(\.[0-9]+)?")


class _SKUText(BaseModel):
    """Checks shared by create and update. None and not-sent pass; text is trimmed."""

    @field_validator("product_name", check_fields=False)
    @classmethod
    def _name(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("product_name can't be blank")
        if len(v) > NAME_MAX:
            raise ValueError(f"product_name is at most {NAME_MAX} characters")
        return v

    @field_validator("brand", check_fields=False)
    @classmethod
    def _brand(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) > BRAND_MAX:
            raise ValueError(f"brand is at most {BRAND_MAX} characters")
        return v or None

    @field_validator("pack_size", check_fields=False)
    @classmethod
    def _pack_size(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not (_PACK.fullmatch(v) and float(v) > 0):
            raise ValueError("pack_size must be a positive number of pieces per case, e.g. 24 or 144")
        return v

    @field_validator("notes", check_fields=False)
    @classmethod
    def _notes(cls, v):
        if v is not None and len(v) > NOTES_MAX:
            raise ValueError(f"notes is at most {NOTES_MAX} characters")
        return v


class SKUCreate(_SKUText):
    sku_code: str
    principal: str  # 'unilever' | 'delmonte'
    product_name: str
    pack_size: str | None = None
    brand: str | None = None
    unit_price: float | None = None
    lead_time_days: int | None = None
    notes: str | None = None


class SKUUpdate(_SKUText):
    product_name: str | None = None
    pack_size: str | None = None
    brand: str | None = None
    unit_price: float | None = None
    lead_time_days: int | None = None
    status: str | None = None
    notes: str | None = None
