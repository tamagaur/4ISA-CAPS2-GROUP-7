"""
analytics.forecasting.diagnostic_metrics — the one place the accuracy
metrics are defined: the deployed path (run_baseline_forecast.py writes
Forecast_Result.mape from mape(), DEC-25; baseline.evaluate_baseline's
MAPE is mape()), the bake-off scripts, the forecast viewer and the xlsx
export.

One negative-actual rule, applied everywhere:
    negative (and zero) actuals are EXCLUDED from MAPE;
    every actual, negative included, is INCLUDED in WAPE and sMAPE.
A negative actual is a returns-dominated month: a percentage of it is
meaningless, but the unit error against it is still a real error.

MASE never computes its own scale. The caller passes the scale, taken from
REAL months only (`naive_scale`), so a synthetic 2021-22 prefix can change
a model's forecasts but never the yardstick they are measured with.
"""
from __future__ import annotations

import numpy as np

# Display convention for is_mape_unstable, not a statistical claim: MAPE
# weights each error by 1/actual_t, WAPE by 1/mean(actual). Below this
# min/mean ratio a single month carries >10x its WAPE weight. Measured on
# the Tier A (as of 2026-02) holdouts, 2026-09-20: every SKU whose MAPE
# blew past 1000% sits at <= 0.056; the next SKU up is at 0.115.
UNSTABLE_MIN_TO_MEAN = 0.10


def _pair(actual, pred) -> tuple[np.ndarray, np.ndarray]:
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    if a.shape != p.shape:
        raise ValueError(f"actual {a.shape} and pred {p.shape} differ in shape")
    return a, p


def mape(actual, pred) -> float:
    """Mean |a-p|/a over the months with actual > 0. NaN if there are none.
    Zero and negative (returns) months are excluded here only — the series
    and every other metric keep them."""
    a, p = _pair(actual, pred)
    ok = a > 0
    return float(np.mean(np.abs(a[ok] - p[ok]) / a[ok])) if ok.any() else float("nan")


def wape(actual, pred) -> float:
    """sum|a-p| / sum|a|, negatives included. NaN if sum|a| is 0."""
    a, p = _pair(actual, pred)
    den = float(np.abs(a).sum())
    return float(np.abs(a - p).sum() / den) if den > 0 else float("nan")


def smape(actual, pred) -> float:
    """Mean 2|a-p| / (|a|+|p|), negatives included; months where both are
    0 contribute nothing (a perfect forecast of nothing). Bounded [0, 2]."""
    a, p = _pair(actual, pred)
    den = np.abs(a) + np.abs(p)
    ok = den > 0
    return float(np.mean(2 * np.abs(a[ok] - p[ok]) / den[ok])) if ok.any() else float("nan")


def mase(actual, pred, scale: float) -> float:
    """mean|a-p| / scale. `scale` is passed in, never computed here — see
    naive_scale. NaN when the scale is missing, non-finite or not positive."""
    a, p = _pair(actual, pred)
    if scale is None or not np.isfinite(scale) or scale <= 0:
        return float("nan")
    return float(np.mean(np.abs(a - p)) / scale)


def rmse(actual, pred) -> float:
    """sqrt(mean (a-p)^2), every actual included. NaN if there are no points."""
    a, p = _pair(actual, pred)
    return float(np.sqrt(np.mean((a - p) ** 2))) if a.size else float("nan")


def naive_scale(real_train) -> float:
    """Mean |lag-1 difference| of the REAL training months before the first
    test origin. Callers must pass real months only — never a series with a
    synthetic prefix attached. 0.0 when there are fewer than 2 months."""
    x = np.asarray(real_train, dtype=float)
    return float(np.mean(np.abs(np.diff(x)))) if len(x) > 1 else 0.0


def is_mape_unstable(actual, ratio: float = UNSTABLE_MIN_TO_MEAN) -> tuple[bool, float]:
    """(unstable, min_abs_actual). Unstable when MAPE cannot be read as a
    typical percentage error for this holdout: some actual is <= 0 (that
    month is dropped from MAPE), or the smallest |actual| is below `ratio`
    of the mean |actual| (one month dominates the average)."""
    a = np.asarray(actual, dtype=float)
    if a.size == 0:
        return True, float("nan")
    abs_a = np.abs(a)
    min_abs = float(abs_a.min())
    mean_abs = float(abs_a.mean())
    unstable = bool((a <= 0).any() or mean_abs == 0 or min_abs < ratio * mean_abs)
    return unstable, min_abs
