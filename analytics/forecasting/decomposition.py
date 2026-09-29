"""
analytics.forecasting.decomposition — STL decomposition of one monthly
demand series: the analytical mapping's D4, "what trend patterns and demand
variability are present in historical SKU demand?".

STL (Seasonal-Trend decomposition using Loess, Cleveland et al. 1990) via
statsmodels, period 12, robust fitting so one freak month doesn't bend the
seasonal shape. The series runs from the first sale (the months before it
are "not launched yet", not zero demand — the router's own convention).
Three full seasonal cycles (MIN_MONTHS) are required; a shorter series gets
the reason instead of a fit to noise. Two were required until 2026-09-29,
when the same stl_summary() run on pure white noise read "Strong"
seasonality for 79% of 24-month series and 98% at 26 months (85% at 30,
20% at 38): with so few cycles the robust fit absorbs one-off spikes into
the seasonal shape, so the panel was reporting noise as seasonality.

Strength of trend and seasonality follow Hyndman & Athanasopoulos,
Forecasting: Principles and Practice (3rd ed.), §4.3:
    F_T = max(0, 1 - Var(R) / Var(T + R))
    F_S = max(0, 1 - Var(R) / Var(S + R))
0 = no trend / seasonality beyond the noise, 1 = all of it.

Pure function, no DB.
"""
from __future__ import annotations

import numpy as np
from statsmodels.tsa.seasonal import STL

PERIOD = 12
MIN_MONTHS = 3 * PERIOD
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _strength(component: np.ndarray, resid: np.ndarray) -> float:
    denom = np.var(component + resid)
    if denom <= 0:
        return 0.0
    return float(max(0.0, 1.0 - np.var(resid) / denom))


def stl_summary(periods: list[str], values: list[float]) -> dict:
    """Decompose a zero-filled monthly series ('YYYY-MM' periods, ascending,
    no gaps). Returns {available, reason?, periods, observed, trend,
    seasonal, resid, trend_strength, seasonal_strength, peak_month,
    trough_month, seasonal_swing_pct, months}."""
    y = np.asarray(values, dtype=float)
    sold = np.flatnonzero(y > 0)
    if sold.size == 0:
        return {"available": False, "reason": "No sales recorded.", "months": 0}
    start = int(sold[0])
    y = y[start:]
    periods = list(periods[start:])
    if len(y) < MIN_MONTHS:
        return {
            "available": False,
            "reason": (
                f"Seasonality needs {MIN_MONTHS} months from the first sale (three seasonal cycles) to tell a "
                f"repeating pattern from noise; this series has {len(y)}."
            ),
            "months": int(len(y)),
        }

    fit = STL(y, period=PERIOD, robust=True).fit()
    trend, seasonal, resid = np.asarray(fit.trend), np.asarray(fit.seasonal), np.asarray(fit.resid)

    # Seasonal shape by calendar month: the average seasonal component for
    # each month of the year over the whole series.
    month_idx = np.array([int(p[5:7]) - 1 for p in periods])
    by_month = np.array([seasonal[month_idx == m].mean() if (month_idx == m).any() else np.nan for m in range(12)])
    level = float(np.mean(y))
    swing = float(np.nanmax(by_month) - np.nanmin(by_month))

    return {
        "available": True,
        "months": int(len(y)),
        "periods": periods,
        "observed": [round(float(v), 2) for v in y],
        "trend": [round(float(v), 2) for v in trend],
        "seasonal": [round(float(v), 2) for v in seasonal],
        "resid": [round(float(v), 2) for v in resid],
        "trend_strength": round(_strength(trend, resid), 3),
        "seasonal_strength": round(_strength(seasonal, resid), 3),
        "peak_month": MONTH_NAMES[int(np.nanargmax(by_month))],
        "trough_month": MONTH_NAMES[int(np.nanargmin(by_month))],
        # Peak-to-trough of the seasonal shape as a share of the average
        # monthly level — "sales swing about N% across the year".
        "seasonal_swing_pct": round(swing / level * 100, 1) if level > 0 else None,
    }
