"""
analytics.forecasting.challenger - the challenger forecast computed beside the served one (2026-11-10).

NEVER SERVED. Nothing here is imported by router.py, the forecast runner's write path or the LP. It exists so a
second forecast can be stored and scored for every product every month, and compared with the served one at the
recalibration point under the rule committed before any comparison (docs/CHALLENGER_SELECTION_RULE.md).

CHALLENGER_ID = "damped_trend_v1"

    bin (router.bin_at)  served (router.LIVE_MODEL)   challenger
    insufficient         none                          none
    short   3-11         MA3                           MA3 (identical to served: too few months to fit a trend)
    medium 12-23         TSB                           damped-trend exponential smoothing
    long   24+           (XGBoost + MA3) / 2           damped-trend exponential smoothing

Why this challenger (scripts/forecast_bias_diagnosis.py, Sep 2025 - Feb 2026, read 2026-11-10): the served forecast
was high in 62.4% of product-months, net +13.9% in pieces; the company total in pieces stepped down from about 2.8M a
month (Mar-Jun 2025) to about 2.1M from Jul 2025; of the 61 products the card shows "too high 3 or more months in a
row", 26 have a forecast that falls at every step of the run while sales sit below their earlier level (lag on a
decline), 4 of the 38 testable ones are one spike held in the 3-month window, and the calendar factor tips 12 into
the flag. Lag on a decline is what a trend term addresses: the forecast moves down with a falling level instead of
trailing it by a step; the damping keeps it from extrapolating a fall forever. A median of 3 would address the spike
mechanism (4 products), not this one.

Disclosed: damped Holt was one of the 17 models of the 2026-09 bake-off (reports/MODEL_BAKEOFF_UNILEVER.md: median
MASE 0.854 against MA3's 0.819 over each product's last 6 months, 89 products) and was not adopted. It was not chosen
here for scoring well; it was chosen for the mechanism, and its earlier score was not better than MA3's.

Same treatment as the served model everywhere except the model itself: the history route() reads (months before the
target, blank months skipped, from the first sale), the same bins, the same guards with the same MA3 fallback
(no value; above the product's own historical maximum; below zero), the same zero floor and the same calendar factor
when the served forecast carries it. The dead-SKU rule is applied by the caller to both, as the runner applies it.

Pure functions, no DB access. statsmodels' fit is deterministic for a given series.
"""
from __future__ import annotations

import math
import warnings

import pandas as pd

from analytics.forecasting.calendar import calendar_factor
from analytics.forecasting.global_model import assert_real_history, from_first_sale
from analytics.forecasting.router import bin_at, ma3_value

CHALLENGER_ID = "damped_trend_v1"
TREND_BINS = ("medium", "long")


def damped_trend_value(history: pd.Series) -> tuple[float | None, str | None]:
    """One-step damped-trend (additive, damped; Holt with damped_trend=True) forecast of `history`, parameters
    estimated by statsmodels. (value, None), or (None, reason) when the fit fails or gives no finite number."""
    from statsmodels.tsa.holtwinters import Holt
    y = pd.Series(history.to_numpy(dtype=float))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            value = float(Holt(y, damped_trend=True, initialization_method="estimated").fit().forecast(1).iloc[0])
    except Exception as exc:  # noqa: BLE001 - a failed fit falls back to MA3 with the reason kept
        return None, f"damped_trend_failed: {type(exc).__name__}: {exc}"
    if not math.isfinite(value):
        return None, f"damped_trend_failed: non-finite forecast {value}"
    return value, None


def challenger_route(series: pd.Series, target_month: pd.Timestamp, calendar_totals: pd.Series | None = None,
                     allow_placeholder: bool = False) -> dict:
    """The challenger's one-step forecast for `target_month`, reading only months before it. Keys: challenger,
    bin, method ('ma3' or 'damped_trend'), value (None for the insufficient bin), ma3_value, backup_fired,
    backup_reason, value_before_calendar / calendar_factor when `calendar_totals` is given."""
    assert_real_history(series, allow_placeholder)
    history = series[series.index < target_month].dropna()
    if len(history) < 1:
        raise ValueError("challenger_route() needs at least one month of history before target_month")
    history = from_first_sale(history) if len(from_first_sale(history)) else history
    bin_name, sales_months = bin_at(history)
    ma3 = ma3_value(history)
    out = {"challenger": CHALLENGER_ID, "bin": bin_name, "sales_months": sales_months, "ma3_value": ma3,
           "backup_fired": False, "backup_reason": None}
    if bin_name == "insufficient":
        return {**out, "method": None, "value": None}
    method, value, reason = "ma3", ma3, None
    if bin_name in TREND_BINS:
        method = "damped_trend"
        value, reason = damped_trend_value(history)
        if reason is None:
            hist_max = float(history.to_numpy(dtype=float).max())
            if value > hist_max:
                reason = f"above_historical_max: {value:.3f} > {hist_max:.3f}"
            elif value < 0:
                reason = f"below_zero: {value:.3f}"
        if reason is not None:
            out.update(backup_fired=True, backup_reason=reason)
            method, value = "ma3", ma3
    value = max(0.0, float(value))
    if calendar_totals is not None:
        factor, years = calendar_factor(calendar_totals, target_month)
        out.update(value_before_calendar=value, calendar_factor=factor, calendar_years=years)
        value = max(0.0, value * factor)
    return {**out, "method": method, "value": value}
