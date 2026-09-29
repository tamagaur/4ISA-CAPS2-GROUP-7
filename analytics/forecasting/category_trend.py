"""
analytics.forecasting.category_trend — category-level trend over the coming
year: the analytical mapping's P1, "what are the projected growth and
decline trajectories for each product category over the coming year?".

A TREND PROJECTION, not a validated forecast. Over the last
TREND_WINDOW_MONTHS observed months of a category's revenue (fewer when the
category is younger), the Theil–Sen line is extended PROJECTION_MONTHS
ahead:

  direction       Mann–Kendall (p < 0.05, analytics.segmentation.traits.
                  trend_stats — the same test sku_traits uses): 'growing' /
                  'declining' when significant, else 'flat'.
  change_pct      the next 12 months on the line against the last 12 months
                  on the same line — the trend's own growth over a year,
                  free of any level mismatch between the line and the
                  actuals (seasonality moves individual months, not the
                  slope).
  change range    the same comparison at the slope's 95% confidence bounds.

Fewer than MIN_POINTS observed months gives no projection, with the reason:
a line through a handful of months says more about the gaps than the
category (Del Monte's categories restart at the Jan 2025 regrouping).

The line starts at the category's FIRST SALE inside the window (2026-09-25).
Months before a category existed are not zero demand: fitting them tilted a
young category's slope upward, while its Mann–Kendall test (trend_stats)
already started at the first sale — two different series behind one
verdict. A category with no revenue anywhere in the window gets no line and
says so, instead of reading as a flat trend.

Every number the page states about the method (window, projection length,
minimum months, significance level, confidence level) is a constant here,
sent through GET /category-trends' `method` block.

Pure function, no DB.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

from analytics.segmentation.traits import MANN_KENDALL_ALPHA, trend_stats

TREND_WINDOW_MONTHS = 24
PROJECTION_MONTHS = 12
MIN_POINTS = 12
# "Revenue, last N months" and the base the change is measured against.
TRAILING_MONTHS = 12
# Confidence level of the Theil–Sen slope bounds behind the change range.
SLOPE_CONFIDENCE = 0.95


def method_constants() -> dict:
    """The method's numbers, for the API to send and the page to state."""
    return {
        "window_months": TREND_WINDOW_MONTHS,
        "projection_months": PROJECTION_MONTHS,
        "min_points": MIN_POINTS,
        "trailing_months": TRAILING_MONTHS,
        "significance_alpha": MANN_KENDALL_ALPHA,
        "slope_confidence": SLOPE_CONFIDENCE,
    }


def _line(slope: float, y: np.ndarray, x: np.ndarray) -> float:
    """Theil–Sen intercept for a given slope, median(y) - slope * median(x):
    scipy.stats.theilslopes's own convention, so the two slope-bound lines
    and the fitted line all pass through the same point. With median(y -
    slope * x) for the bounds only (until 2026-09-29) they could sit above a
    line that had already reached zero, and the table read "— (-100.0% to
    -100.0%)"."""
    return float(np.median(y) - slope * np.median(x))


def _change_pct(slope: float, intercept: float, n: int) -> float | None:
    past = np.clip(intercept + slope * np.arange(n - TRAILING_MONTHS, n), 0, None).sum()
    ahead = np.clip(intercept + slope * np.arange(n, n + PROJECTION_MONTHS), 0, None).sum()
    return round((ahead - past) / past * 100, 1) if past > 0 else None


def project_category(values: list[float]) -> dict:
    """values: the category's monthly revenue over its observed months,
    oldest first. Returns {available, label?, reason?, points, direction,
    mk_p, slope_per_month, slope_ci, trailing_12, projected_12, change_pct,
    change_pct_low, change_pct_high, fitted, projection, projection_low,
    projection_high}. projection_low/high shade the chart's likely range —
    the slope's SLOPE_CONFIDENCE bounds extended over the projection
    months. `label` is the short status for a table cell when no
    projection is available; `reason` is the sentence behind it."""
    window = np.asarray(values, dtype=float)[-TREND_WINDOW_MONTHS:]
    sold = np.flatnonzero(window > 0)
    if sold.size == 0:
        return {
            "available": False,
            "points": 0,
            "label": "No recent sales",
            "reason": f"No revenue in the last {len(window)} observed months, so there is no trend to project.",
        }
    y = window[sold[0]:]
    n = len(y)
    if n < MIN_POINTS:
        return {
            "available": False,
            "points": int(n),
            "label": "Not enough months",
            "reason": f"A projection needs {MIN_POINTS} observed months from the first sale; this category has {n}.",
        }

    x = np.arange(n, dtype=float)
    slope, intercept, lo, hi = stats.theilslopes(y, x, SLOPE_CONFIDENCE)
    direction, mk_p, _ = trend_stats(y)
    label = {"up": "growing", "down": "declining"}.get(direction, "flat")
    lo_line, hi_line = _line(lo, y, x), _line(hi, y, x)
    change = _change_pct(slope, intercept, n)
    # No range around a change that has no value: when the fitted line is
    # already at zero over the last 12 months there is nothing to compare.
    bounds = [] if change is None else sorted(
        v for v in (_change_pct(lo, lo_line, n), _change_pct(hi, hi_line, n)) if v is not None
    )
    x_ahead = np.arange(n, n + PROJECTION_MONTHS)
    ahead = np.clip(intercept + slope * x_ahead, 0, None)
    # The projection's likely range, month by month: the same two
    # slope-confidence lines the change range above is computed from,
    # extended over the projection months. All three lines pivot on
    # (median x, median y) (_line), so past the window they cannot cross;
    # the per-month min/max is kept as a guard so low <= high always, and
    # both clip at zero exactly like the projection itself.
    ahead_lo = lo_line + lo * x_ahead
    ahead_hi = hi_line + hi * x_ahead
    band_low = np.clip(np.minimum(ahead_lo, ahead_hi), 0, None)
    band_high = np.clip(np.maximum(ahead_lo, ahead_hi), 0, None)

    return {
        "available": True,
        "points": int(n),
        "direction": label,
        "mk_p": None if mk_p is None else round(float(mk_p), 4),
        "slope_per_month": round(float(slope), 2),
        "slope_ci": [round(float(lo), 2), round(float(hi), 2)],
        "trailing_12": round(float(y[-TRAILING_MONTHS:].sum()), 2),
        "projected_12": round(float(ahead.sum()), 2),
        "change_pct": change,
        "change_pct_low": bounds[0] if bounds else None,
        "change_pct_high": bounds[-1] if bounds else None,
        "fitted": [round(float(v), 2) for v in np.clip(intercept + slope * x, 0, None)],
        "projection": [round(float(v), 2) for v in ahead],
        "projection_low": [round(float(v), 2) for v in band_low],
        "projection_high": [round(float(v), 2) for v in band_high],
    }
