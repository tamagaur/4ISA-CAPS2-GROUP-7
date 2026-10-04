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

THE LABEL (2026-10-04). The panel used to call STL strength >= 0.6 "Strong
seasonality". At our lengths (36-38 months) that band reads 15-18% of
series with no seasonality at all as strong; 13 of the 16 products it
labelled were not significant on the lag-12 test (reports/diagnostics/
forecast_error_business_2026-10-03/README.md sections 6 and 10,
kelvin/forecast-error-business b4f6b77). yearly_pattern() is the label now:
DEC-23's lag-12 autocorrelation test, ACF(12) > 1.96 / sqrt(n) on 24+
months from the first sale (rule R1 there, positive side only; under 1%
false alarms). STL
strength and its peak/trough months stay as the chart's description; the
panel names peak months only for a product that repeats yearly.

Pure functions, no DB.
"""
from __future__ import annotations

import numpy as np
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.stattools import acf

from analytics.params import YEARLY_ACF_MIN_MONTHS, YEARLY_ACF_Z

PERIOD = 12
LABEL_REPEATS = "Repeats yearly"
LABEL_NO_PATTERN = "No reliable yearly pattern"
LABEL_SHORT = f"Not enough history (needs {YEARLY_ACF_MIN_MONTHS} months)"
MIN_MONTHS = 3 * PERIOD
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _strength(component: np.ndarray, resid: np.ndarray) -> float:
    denom = np.var(component + resid)
    if denom <= 0:
        return 0.0
    return float(max(0.0, 1.0 - np.var(resid) / denom))


def yearly_pattern(values: list[float]) -> dict:
    """The seasonality label for a zero-filled monthly series (ascending, no
    gaps), read from the first sale on: {label, repeats_yearly, acf_lag12,
    acf_bound, months, min_months}. repeats_yearly is None (with
    LABEL_SHORT) under YEARLY_ACF_MIN_MONTHS months, and False for a series
    that never varies (ACF is undefined there).

    One-sided on purpose: ACF(12) must be ABOVE +bound. b4f6b77's rule R1
    tests |ACF(12)|, which on its Tier A cohort makes no difference (all 3
    hits are positive), but across all 1,807 Unilever SKUs 3 of the 10 that
    pass |ACF(12)| are negative (checked 2026-10-04): a month tends to run
    opposite to the same month a year earlier, which is not "repeats
    yearly"."""
    y = np.asarray(values, dtype=float)
    sold = np.flatnonzero(y > 0)
    y = y[int(sold[0]):] if sold.size else y[:0]
    n = len(y)
    out = {"label": LABEL_SHORT, "repeats_yearly": None, "acf_lag12": None, "acf_bound": None,
           "months": int(n), "min_months": YEARLY_ACF_MIN_MONTHS}
    if n < YEARLY_ACF_MIN_MONTHS:
        return out
    bound = YEARLY_ACF_Z / np.sqrt(n)
    out["acf_bound"] = round(float(bound), 3)
    if np.std(y) <= 0:
        return {**out, "label": LABEL_NO_PATTERN, "repeats_yearly": False}
    r12 = float(acf(y, nlags=PERIOD, fft=False)[PERIOD])
    repeats = bool(r12 > bound)
    return {**out, "label": LABEL_REPEATS if repeats else LABEL_NO_PATTERN,
            "repeats_yearly": repeats, "acf_lag12": round(r12, 3)}


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
