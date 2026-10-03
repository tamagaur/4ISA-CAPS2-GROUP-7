"""
analytics.segmentation.bins — Phase 2 binning schemes (BINS ONLY, no
forecasting models — see analytics.segmentation.traits' module docstring).

Each scheme function takes trait values already computed by traits.py and
returns (bin, bin_reason). Schemes never touch the DB or a demand series
directly, so a new scheme (trend_v1, volatility_v1, ...) needs only a new
function here plus new sku_segment rows — no schema or trait change.
"""
from __future__ import annotations

from analytics.params import MIN_MONTHS_WITH_SALES, XYZ_CV_HIGH, XYZ_CV_LOW

LENGTH_V1_INSUFFICIENT = MIN_MONTHS_WITH_SALES
LENGTH_V1_LONG = 12


def length_v1(history_months: int) -> tuple[str, str]:
    """insufficient (<3 months with sales), short (3-11), long (12+).
    Cutoffs match the existing ABC/forecasting eligibility gate
    (analytics.params.MIN_MONTHS_WITH_SALES = 3, the runner's own) and
    the length-scheme cutoff used in reports/ABC_PHASE2_2026-09.md /
    the Round 1 diagnostic (12 months)."""
    if history_months < LENGTH_V1_INSUFFICIENT:
        return "insufficient", f"{history_months} months with sales < {LENGTH_V1_INSUFFICIENT}"
    if history_months < LENGTH_V1_LONG:
        return "short", f"{history_months} months with sales, {LENGTH_V1_INSUFFICIENT}-{LENGTH_V1_LONG - 1}"
    return "long", f"{history_months} months with sales >= {LENGTH_V1_LONG}"


# Round 2 (2026-09-20). Every scheme below gates on the same
# LENGTH_V1_INSUFFICIENT floor first: under 3 sales months neither a trend
# test nor a CV has anything to measure, so those SKUs get 'insufficient'
# rather than a label the data cannot support.
LENGTH_V2_SEASONAL = 24   # two full yearly cycles — the least a 12-month seasonal term can be fit on
# XYZ cut-offs on sku_traits.cv (analytics.params; a convention, no citation
# on record). Fixed on purpose, NOT cohort quartiles: a quartile moves with
# the cohort, so a SKU could change bin without its sales changing.
VOLATILITY_V1_LOW = XYZ_CV_LOW
VOLATILITY_V1_HIGH = XYZ_CV_HIGH


def length_v2(history_months: int) -> tuple[str, str]:
    """length_v1 with 'long' split at 24 sales months: insufficient (<3),
    short (3-11), medium (12-23), long (24+)."""
    if history_months < LENGTH_V1_LONG:
        return length_v1(history_months)
    if history_months < LENGTH_V2_SEASONAL:
        return "medium", f"{history_months} months with sales, {LENGTH_V1_LONG}-{LENGTH_V2_SEASONAL - 1}"
    return "long", f"{history_months} months with sales >= {LENGTH_V2_SEASONAL}"


def _trend_reason(trend: str, trend_p: float | None, trend_slope: float | None) -> str:
    if trend_p is None or trend_slope is None:
        return f"trend={trend} (series too short or constant to test)"
    return f"Mann-Kendall p={trend_p:.4f} from first sale, Theil-Sen slope {trend_slope:+.1f} units/month"


def trend_v1(history_months: int, trend: str, trend_p: float | None, trend_slope: float | None) -> tuple[str, str]:
    """up / down / none from traits.trend_stats (first sale onward), or
    insufficient (<3 sales months)."""
    if history_months < LENGTH_V1_INSUFFICIENT:
        return "insufficient", f"{history_months} months with sales < {LENGTH_V1_INSUFFICIENT}"
    return trend, _trend_reason(trend, trend_p, trend_slope)


def volatility_v1(history_months: int, cv: float | None) -> tuple[str, str]:
    """low (CV < 0.5), medium (0.5 <= CV < 1.0), high (CV >= 1.0), on CV
    from first sale onward, or insufficient (<3 sales months)."""
    if history_months < LENGTH_V1_INSUFFICIENT or cv is None:
        return "insufficient", f"{history_months} months with sales < {LENGTH_V1_INSUFFICIENT}"
    if cv < VOLATILITY_V1_LOW:
        return "low", f"CV {cv:.2f} < {VOLATILITY_V1_LOW}"
    if cv < VOLATILITY_V1_HIGH:
        return "medium", f"CV {cv:.2f}, {VOLATILITY_V1_LOW}-{VOLATILITY_V1_HIGH}"
    return "high", f"CV {cv:.2f} >= {VOLATILITY_V1_HIGH}"


def stability_v1(stability_group: str, tier_a_periods: int, total_periods: int) -> tuple[str, str]:
    """The ABC-derived traits.stability_group, as a scheme."""
    return stability_group, f"Tier A in {tier_a_periods} of {total_periods} periods"


def combined_v1(history_months: int, trend: str, trend_p: float | None, trend_slope: float | None) -> tuple[str, str]:
    """length_v2, with 'long' split by trend: insufficient, short, medium,
    long_up, long_down, long_flat. Trend is only consulted at 24+ sales
    months — below that the series is too short for the test to be
    trusted as a split."""
    length_bin, length_reason = length_v2(history_months)
    if length_bin != "long":
        return length_bin, length_reason
    suffix = {"up": "up", "down": "down", "none": "flat"}[trend]
    return f"long_{suffix}", f"{length_reason}; {_trend_reason(trend, trend_p, trend_slope)}"
