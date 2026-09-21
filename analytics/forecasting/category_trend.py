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

Pure function, no DB.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

from analytics.segmentation.traits import trend_stats

TREND_WINDOW_MONTHS = 24
PROJECTION_MONTHS = 12
MIN_POINTS = 12


def _line(slope: float, y: np.ndarray, x: np.ndarray) -> float:
    """Theil–Sen intercept for a given slope: median of y - slope * x."""
    return float(np.median(y - slope * x))


def _change_pct(slope: float, intercept: float, n: int) -> float | None:
    past = np.clip(intercept + slope * np.arange(n - 12, n), 0, None).sum()
    ahead = np.clip(intercept + slope * np.arange(n, n + PROJECTION_MONTHS), 0, None).sum()
    return round((ahead - past) / past * 100, 1) if past > 0 else None


def project_category(values: list[float]) -> dict:
    """values: the category's monthly revenue over its observed months,
    oldest first. Returns {available, reason?, points, direction, mk_p,
    slope_per_month, slope_ci, trailing_12, projected_12, change_pct,
    change_pct_low, change_pct_high, fitted, projection}."""
    y_all = np.asarray(values, dtype=float)
    y = y_all[-TREND_WINDOW_MONTHS:]
    n = len(y)
    if n < MIN_POINTS:
        return {
            "available": False,
            "points": int(n),
            "reason": f"A projection needs {MIN_POINTS} observed months; this category has {n}.",
        }

    x = np.arange(n, dtype=float)
    slope, intercept, lo, hi = stats.theilslopes(y, x, 0.95)
    direction, mk_p, _ = trend_stats(y)
    label = {"up": "growing", "down": "declining"}.get(direction, "flat")
    lo_line, hi_line = _line(lo, y, x), _line(hi, y, x)
    change = _change_pct(slope, intercept, n)
    bounds = sorted(v for v in (_change_pct(lo, lo_line, n), _change_pct(hi, hi_line, n)) if v is not None)
    ahead = np.clip(intercept + slope * np.arange(n, n + PROJECTION_MONTHS), 0, None)

    return {
        "available": True,
        "points": int(n),
        "direction": label,
        "mk_p": None if mk_p is None else round(float(mk_p), 4),
        "slope_per_month": round(float(slope), 2),
        "slope_ci": [round(float(lo), 2), round(float(hi), 2)],
        "trailing_12": round(float(y[-12:].sum()), 2),
        "projected_12": round(float(ahead.sum()), 2),
        "change_pct": change,
        "change_pct_low": bounds[0] if bounds else None,
        "change_pct_high": bounds[-1] if bounds else None,
        "fitted": [round(float(v), 2) for v in np.clip(intercept + slope * x, 0, None)],
        "projection": [round(float(v), 2) for v in ahead],
    }
