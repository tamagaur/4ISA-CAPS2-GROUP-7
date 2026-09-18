"""
analytics.classification.abc — ABC/Pareto SKU classification.

Phase 3C (CLAUDE.md Steps 10–11):
  Step 10:
    - Compute cumulative revenue per SKU from Sales_Fact
    - Sort descending by revenue contribution
    - Assign tiers: A = 0–80%, B = 80–95%, C = 95–100%
    Checkpoint: Pareto 80/20 plot generated and reviewed.
                Cumulative Revenue Coverage Ratio validated.
                Inventory Turnover Ratio computed.
  Step 11:
    - Write tier assignments to ABC_Classification table in Supabase.
    Checkpoint: All active SKUs have a tier; no nulls.

  Downstream: Category A SKUs only proceed to SARIMA forecasting (Phase 4).
              Category B → descriptive monitoring.
              Category C → minimal monitoring.

Grain note (DEC-02 / DEC-03, see ARCHITECTURE.md §5.1): Sales_Fact is
invoice-grain and carries no product key, so this function does NOT read
Sales_Fact directly. It is a pure, grain-agnostic function: the caller
(the not-yet-written orchestration script) is responsible for handing it
a DataFrame already aggregated at whatever grain each principal's data
honestly supports — SKU for Unilever (product mart), category/brand for
Del Monte (from Sell Out). That decision belongs at the call site, not
here, per anti-fabrication principle #1: this module must not assume or
fabricate a grain it wasn't given.

Implements classify_abc(revenue_df) -> pd.DataFrame.
  Output columns: sku_id, total_revenue, revenue_share, cumulative_share,
  tier, boundary_flag.

Backlog #43 (2026-08): boundary_flag marks SKUs whose cumulative_share
sits within BOUNDARY_MARGIN of a tier cutoff (0.80 or 0.95) — these are
the ones a small revenue shift next period could flip into a different
tier, so procurement should expect them to move rather than be
surprised. NOTE: the backlog cites "Manuscript Sec.3.6" as already
defining this concept, but the specific margin value (how close counts
as "near") was not given to this implementation — 0.02 (2 percentage
points) below is a placeholder default, not sourced from the
manuscript. Confirm the real value against Sec.3.6 and update
BOUNDARY_MARGIN accordingly; do not treat 0.02 as final without that
check (anti-fabrication principle #1 — this module must not guess a
number the manuscript already specifies).
"""
from __future__ import annotations

import pandas as pd

REQUIRED_INPUT_COLUMNS = ("sku_id", "total_revenue")
OUTPUT_COLUMNS = ["sku_id", "total_revenue", "revenue_share", "cumulative_share", "tier", "boundary_flag"]

TIER_A_CUTOFF = 0.80
TIER_B_CUTOFF = 0.95
BOUNDARY_MARGIN = 0.02  # UNCONFIRMED against manuscript Sec.3.6 — see module docstring


def classify_abc(revenue_df: pd.DataFrame) -> pd.DataFrame:
    """ABC/Pareto classification (Steps 10-11).

    Args:
        revenue_df: one row per product key, already aggregated at the
            correct grain by the caller. Must contain:
              - sku_id: product/category key (name kept generic — it is
                a SKU for Unilever, a category for Del Monte; see grain
                note above)
              - total_revenue: revenue already summed for the
                classification period, one row per sku_id (not one row
                per transaction)

    Returns:
        DataFrame with OUTPUT_COLUMNS, sorted descending by total_revenue:
          - revenue_share: this SKU's share of total revenue (0-1)
          - cumulative_share: running cumulative share after this SKU
          - tier: 'A' (cumulative_share <= 0.80), 'B' (<= 0.95), else 'C'
          - boundary_flag: True if cumulative_share is within
            BOUNDARY_MARGIN of the 0.80 or 0.95 cutoff (see module
            docstring re: margin value not yet confirmed against the
            manuscript)

    Raises:
        ValueError: missing required columns, duplicate sku_id, or any
            negative total_revenue (a negative revenue value indicates an
            upstream data-cleaning gap and must be fixed there, not
            silently coerced here — anti-fabrication principle #1).
    """
    missing = [c for c in REQUIRED_INPUT_COLUMNS if c not in revenue_df.columns]
    if missing:
        raise ValueError(f"classify_abc: missing required columns: {missing}")

    if revenue_df["sku_id"].duplicated().any():
        dupes = revenue_df.loc[revenue_df["sku_id"].duplicated(), "sku_id"].tolist()
        raise ValueError(
            f"classify_abc expects one row per sku_id (already aggregated by the "
            f"caller); found duplicates: {dupes}"
        )

    if (revenue_df["total_revenue"] < 0).any():
        negative = revenue_df.loc[revenue_df["total_revenue"] < 0, "sku_id"].tolist()
        raise ValueError(
            f"classify_abc received negative total_revenue for sku_id(s) {negative}; "
            f"this signals an upstream cleaning gap and must not be classified as-is."
        )

    if revenue_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    out = revenue_df[["sku_id", "total_revenue"]].copy()
    # sku_id ASC tiebreak makes ranking deterministic when two SKUs tie on
    # revenue (the fetch queries carry no ORDER BY of their own, so ties
    # would otherwise depend on incidental DB return order).
    out = out.sort_values(["total_revenue", "sku_id"], ascending=[False, True], kind="mergesort").reset_index(drop=True)

    grand_total = out["total_revenue"].sum()
    if grand_total == 0:
        # Every SKU has zero revenue: shares are undefined (0/0), not
        # fabricated as 0% or split evenly. Every SKU still gets a tier
        # (no nulls, per the Step 11 checkpoint) — with zero revenue
        # everywhere, cumulative share never crosses 0%, so all fall to C.
        out["revenue_share"] = pd.NA
        out["cumulative_share"] = pd.NA
        out["tier"] = "C"
        out["boundary_flag"] = False  # undefined shares -> nothing to be "near" a cutoff of
        return out[OUTPUT_COLUMNS]

    out["revenue_share"] = out["total_revenue"] / grand_total
    out["cumulative_share"] = out["revenue_share"].cumsum()
    out["tier"] = out["cumulative_share"].apply(_assign_tier)
    out["boundary_flag"] = out["cumulative_share"].apply(_is_near_boundary)

    return out[OUTPUT_COLUMNS]


def _assign_tier(cumulative_share: float) -> str:
    if cumulative_share <= TIER_A_CUTOFF:
        return "A"
    if cumulative_share <= TIER_B_CUTOFF:
        return "B"
    return "C"


def _is_near_boundary(cumulative_share: float) -> bool:
    """True if this row's cumulative_share sits within BOUNDARY_MARGIN of
    either cutoff — see BOUNDARY_MARGIN's docstring note on confirming
    the real margin against the manuscript."""
    return (
        abs(cumulative_share - TIER_A_CUTOFF) <= BOUNDARY_MARGIN
        or abs(cumulative_share - TIER_B_CUTOFF) <= BOUNDARY_MARGIN
    )
