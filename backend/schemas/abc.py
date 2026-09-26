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
    # Unique per item in both views (one row per product_key). The frontend
    # keys rows on this, not sku_id: sku_id is a display label, and before
    # the category_path fallback was restored every Del Monte row had ''.
    product_key: int | None = None
    sku_id: str
    product_name: str | None = None
    principal: str
    tier: str  # 'A' | 'B' | 'C'
    # The run `tier`, revenue_share, cumulative_share and boundary_flag came
    # from. Equal to the response's classification_period in the default
    # view; under view=last_known an OLDER value means the tier is carried
    # forward from the SKU's most recent run, and its revenue_share is a
    # share of THAT month's revenue — not comparable with, and never summed
    # into, the current run's shares.
    tier_period: str | None = None
    revenue_share: float | None = None
    cumulative_share: float | None = None
    boundary_flag: bool = False  # backlog #43 — near a tier cutoff, margin unconfirmed vs manuscript Sec.3.6
    # None (not 0) when Inventory_Fact_Real has no row for this product_key
    # in the latest _period — as of 2025-12 inventory only covers ~509 of
    # the ~1,628 products present in ABC_Classification (partial ETL load,
    # more coverage expected), so "no record" and "confirmed zero stock"
    # are different facts and must not be coalesced into the same 0.
    current_stock: float | None = None
    stock_status: str  # 'IN STOCK' | 'LOW' | 'CRITICAL' | 'NO DATA'


class TierSummary(BaseModel):
    """Backlog #44: procurement wants to see cumulative revenue
    contribution PER TIER, not just per-SKU cumulative_share — this
    rolls that up so the dashboard doesn't have to sum client-side."""
    tier: str
    sku_count: int
    # Sum of revenue_share over this tier's CURRENT-run SKUs only. Carried-
    # forward rows are excluded: their shares are fractions of other months'
    # revenue, so adding them would push the tiers past 100% combined.
    revenue_share_total: float
    # How many of sku_count are carried forward (view=last_known); always 0
    # in the default view.
    carried_forward_count: int = 0
    # This tier's share of the items RANKED in the current run (carried-
    # forward rows excluded, like revenue_share_total) — the measured
    # counterpart of "A is about a fifth of SKUs", so the UI shows the real
    # figure rather than a stock phrase.
    sku_share: float | None = None


class ABCRules(BaseModel):
    """The rules the run applied (analytics/classification/abc.py), sent so
    every page states them from the source instead of repeating them."""
    tier_a_cutoff: float
    tier_b_cutoff: float
    boundary_margin: float


class ParetoCheck(BaseModel):
    """Manuscript §3.4.4.2.2 for the current run: revenue earned by the top
    `top_fraction` of ranked items, and whether it falls in the valid band."""
    top_fraction: float
    top_count: int
    ranked_count: int
    revenue_share: float
    band_low: float
    band_high: float
    passes: bool


class ABCResponse(BaseModel):
    items: list[ABCItem]
    count: int
    classification_period: str | None = None  # 'YYYY-MM'
    tier_summary: list[TierSummary] = []
    rules: ABCRules | None = None
    # None when nothing was ranked, or when the rows span both principals —
    # their shares are fractions of two different revenues and can't be
    # ranked against each other.
    pareto_check: ParetoCheck | None = None
    # view=last_known only: products in scope with no 'single' classification
    # at or before classification_period — never ranked, so they have no tier
    # to show. None in the default view, which does not compute it.
    unclassified_count: int | None = None
