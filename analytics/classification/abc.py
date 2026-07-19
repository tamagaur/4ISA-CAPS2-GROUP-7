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
  Output columns: sku_id, total_revenue, revenue_share, cumulative_share, tier.
"""
from __future__ import annotations

import pandas as pd

REQUIRED_INPUT_COLUMNS = ("sku_id", "total_revenue")
OUTPUT_COLUMNS = ["sku_id", "total_revenue", "revenue_share", "cumulative_share", "tier"]

TIER_A_CUTOFF = 0.80
TIER_B_CUTOFF = 0.95


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
    out = out.sort_values("total_revenue", ascending=False, kind="mergesort").reset_index(drop=True)

    grand_total = out["total_revenue"].sum()
    if grand_total == 0:
        # Every SKU has zero revenue: shares are undefined (0/0), not
        # fabricated as 0% or split evenly. Every SKU still gets a tier
        # (no nulls, per the Step 11 checkpoint) — with zero revenue
        # everywhere, cumulative share never crosses 0%, so all fall to C.
        out["revenue_share"] = pd.NA
        out["cumulative_share"] = pd.NA
        out["tier"] = "C"
        return out[OUTPUT_COLUMNS]

    out["revenue_share"] = out["total_revenue"] / grand_total
    out["cumulative_share"] = out["revenue_share"].cumsum()
    out["tier"] = out["cumulative_share"].apply(_assign_tier)

    return out[OUTPUT_COLUMNS]


def _assign_tier(cumulative_share: float) -> str:
    if cumulative_share <= TIER_A_CUTOFF:
        return "A"
    if cumulative_share <= TIER_B_CUTOFF:
        return "B"
    return "C"
