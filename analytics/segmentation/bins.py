"""
analytics.segmentation.bins — Phase 2 binning schemes (BINS ONLY, no
forecasting models — see analytics.segmentation.traits' module docstring).

Each scheme function takes trait values already computed by traits.py and
returns (bin, bin_reason). Schemes never touch the DB or a demand series
directly, so a new scheme (trend_v1, volatility_v1, ...) needs only a new
function here plus new sku_segment rows — no schema or trait change.
"""
from __future__ import annotations

LENGTH_V1_INSUFFICIENT = 3
LENGTH_V1_LONG = 12


def length_v1(history_months: int) -> tuple[str, str]:
    """insufficient (<3 months with sales), short (3-11), long (12+).
    Cutoffs match the existing ABC/forecasting eligibility gate
    (analytics/forecasting/baseline.py:38, MIN_MONTHS_WITH_SALES=3) and
    the length-scheme cutoff used in reports/ABC_PHASE2_2026-09.md /
    the Round 1 diagnostic (12 months)."""
    if history_months < LENGTH_V1_INSUFFICIENT:
        return "insufficient", f"{history_months} months with sales < {LENGTH_V1_INSUFFICIENT}"
    if history_months < LENGTH_V1_LONG:
        return "short", f"{history_months} months with sales, {LENGTH_V1_INSUFFICIENT}-{LENGTH_V1_LONG - 1}"
    return "long", f"{history_months} months with sales >= {LENGTH_V1_LONG}"
