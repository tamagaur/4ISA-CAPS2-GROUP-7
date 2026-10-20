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

import datetime
from typing import Literal

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
    current_stock: float | None = None  # pieces (backend/stock_units.py)
    # 'IN STOCK' | 'LOW' | 'CRITICAL' | 'NO DATA' | 'NO ROP' — cover against
    # the LP's current-cycle ss_i and target stock rop_i (the order-up-to
    # level since the 2026-09-30 run); backend/stock_status.py. 'ON HAND'
    # instead of the first three and NO ROP for an account without lp.view
    # (routers/abc.py's _status_for). 'NO ROP' keeps its name because other
    # pages read the value.
    stock_status: str
    # Why the LP's current cycle gives this product no target stock, in the
    # words the page shows ("Not planned: forecast accuracy check not passed
    # (MASE 1.24)"), and a stable code the page groups by. None when it has a
    # target, and for an account without lp.view (whether the LP plans a
    # product is LP information). routers/abc.py's _no_target_reason.
    no_target_reason: str | None = None
    no_target_code: str | None = None


class TierSummary(BaseModel):
    """Backlog #44: procurement wants to see cumulative revenue
    contribution PER TIER, not just per-SKU cumulative_share — this
    rolls that up so the dashboard doesn't have to sum client-side."""
    tier: str
    sku_count: int
    # This tier's share of the CURRENT run's revenue. Carried-forward rows
    # are excluded: their shares are fractions of other months' revenue, so
    # adding them would push the tiers past 100% combined. Read off the
    # stored running total at the tier's boundary, not summed from per-row
    # shares that were each rounded to 4 dp (routers/abc.py's _tier_shares).
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
    `top_fraction` of ranked items, and whether it falls in the valid band.

    status 'not_applicable' (passes None, `reason` says why) when fewer than
    `min_items` were ranked: with Del Monte's 4 categories the "top 20%" is
    one category, so pass or fail would only describe that one category's
    share (routers/abc.py's PARETO_MIN_ITEMS). The measured figures are still
    sent; a caller must read `status` before `passes`."""
    top_fraction: float
    top_count: int
    ranked_count: int
    revenue_share: float
    band_low: float
    band_high: float
    passes: bool | None
    status: Literal["pass", "fail", "not_applicable"]
    min_items: int
    reason: str | None = None


class ABCResponse(BaseModel):
    items: list[ABCItem]
    count: int
    classification_period: str | None = None  # 'YYYY-MM'
    # {principal display name: 'YYYY-MM'} — each principal's own run (they differ).
    tier_a_periods: dict[str, str] = {}
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
    # view=last_known only: Del Monte categories left out because they stopped existing (the Jan 2025 regrouping)
    # — their last real month is before the anchor, so their tier is not carried forward (audit BE-3).
    retired_series_count: int = 0
    # {principal: day its latest stock count was taken} — the count every
    # row's current_stock comes from (routers/sku.py's STOCK_COUNT_DATE_SQL).
    # Unilever's "Mar 2026" file was counted 2026-04-06, so the page states
    # the day instead of the month the file is filed under (2026-10-03).
    stock_count_dates: dict[str, datetime.date] = {}
    # The LP cycle each row's target stock comes from (a month's first day,
    # "Mar 2026 plan"). None without lp.view — the target stock itself is
    # withheld then — or when there is no current cycle.
    planning_cycle_date: datetime.date | None = None
