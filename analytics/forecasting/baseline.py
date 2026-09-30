"""
analytics.forecasting.baseline - Per-SKU baseline demand forecasting
(MA3 / Naive / SBA) for Unilever Category A.

Why this module exists
----------------------
SARIMA (analytics.forecasting.sarima) is not defensible on Unilever's real
per-SKU demand - no annual seasonality survives inspection, most series are
short and intermittent, and a paper-exact 80/20 static-split simulation this
session showed MA3 / Naive / SBA together beating it on real Category A SKUs
with materially better accuracy. This module turns that finding into real,
re-runnable production code, following sarima.py's pattern (pure functions
here; the DB-facing runner is scripts/run_baseline_forecast.py).

Three deliberate divergences from sarima.py, each documented at its site:
  1. Eligibility gate is on real observations (`months_with_sales >= 3`),
     never on the zero-filled calendar span.
  2. MASE scale is plain lag-1 (`train.diff().abs().mean()`), NOT
     evaluate_sarima()'s conditional seasonal(12)/lag-1 scale - lag-1 is the
     standard choice for intermittent-demand contexts and no defensible
     annual seasonality exists in this data. See evaluate_baseline().
  3. Two selection methods are reported, never one:
       - oracle_method: lowest holdout MASE (an UPPER BOUND - it peeks at the
         very data it is scored against; no real future SKU has this).
       - rule_method: chosen from training-window-only demand class, so it is
         computable for a genuinely new SKU with no holdout. See RULE_METHOD_MAP.

Implements:
  naive_forecast(train, horizon) -> np.ndarray
  moving_average_forecast(train, horizon, window) -> np.ndarray   (MA3 = window 3)
  sba_forecast(train, horizon, alpha=0.1) -> np.ndarray
  tsb_forecast(train, horizon) -> np.ndarray   (fixed weights; served by router.py, not an oracle/rule candidate)
  demand_class(series) -> str           (smooth/erratic/intermittent/lumpy/unclassifiable)
  evaluate_baseline(forecast, holdout, train) -> dict
  passes_mase_gate(mase) -> bool | None
  RULE_METHOD_MAP: dict[str, str]

Constants:
  MIN_MONTHS_WITH_SALES = 3     eligibility gate (real observations, not span)
  HOLDOUT_FRACTION             analytics.params (0.20)
  MASE_GATE                    analytics.params (1.0): a forecast beating the naive benchmark scores < 1
  SBA_ALPHA = 0.1             UNTUNED this pass - stamped alpha_tuned:false everywhere
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Reuse, do not duplicate - the temporal 80/20 split and its boundary
# validation live in analytics/forecasting/split.py and are shared verbatim.
from analytics.forecasting.split import train_holdout_split  # noqa: F401
from analytics.classification.abc import TIER_A_CUTOFF as ABC_TIER_A_CUTOFF  # noqa: F401
from analytics.forecasting.diagnostic_metrics import mape as _mape
from analytics.params import HOLDOUT_FRACTION, MASE_GATE, SBC_CV2_CUT  # noqa: F401
from analytics.segmentation.traits import average_demand_interval, is_intermittent_adi

MIN_MONTHS_WITH_SALES = 3
MA_WINDOW = 3

# SBA smoothing constant. Flagged untuned: no tuning was attempted this pass.
# Every output location (chat, CSV, model_params) stamps "alpha_tuned": false
# alongside this value so it is never read as a fitted parameter.
SBA_ALPHA = 0.1
SBA_ALPHA_TUNED = False

# TSB (Teunter-Syntetos-Babai) smoothing constants: demand size / demand
# probability. FIXED, not fitted - the values every 2026-09 diagnostic ran
# with (scripts/model_bakeoff.py m_tsb). Locked decision 2026-09-21: do not
# fit these per SKU.
TSB_ALPHA_DEMAND = 0.3
TSB_ALPHA_PROB = 0.1

# Demand-class thresholds: the Syntetos-Boylan-Croston (2005) cut points,
# from analytics.params. CV² here is of the NON-ZERO demand sizes only —
# not sku_traits.cv (every month from the first sale), not the fit
# review's CV(last 12).
_CV2_CUT = SBC_CV2_CUT

# ---------------------------------------------------------------------------
# rule_method mapping - a fixed, named, documented lookup (never inlined).
#
# CAVEAT #1 (population): this mapping is derived from the FULL 1,807-SKU
# catalog (1,096-SKU evaluable subset, all ABC tiers combined - the largest,
# most stable per-class sample available this session), then APPLIED here to
# Tier A only. Different populations. Using the larger sample for a stabler
# rule is defensible; this is stated plainly rather than implying the rule
# came from Tier A itself.
#
# CAVEAT #2 (no MA3 branch): this mapping never selects MA3, even though MA3
# leads every aggregate measure. Full-catalog class x method win counts:
#
#   Class (n)          naive   ma3   sba   croston   tsb
#   smooth (263)          50    68   112        25     8
#   erratic (39)           2    14    16         1     6
#   intermittent (426)    204    81    88        40    13
#   lumpy (358)           152    72    80        18    36
#
# MA3 is never the #1 method in any single class - it is SBA's runner-up in
# smooth/erratic and worse than both naive and SBA in intermittent/lumpy. Its
# aggregate lead comes from being consistently decent everywhere, not from
# owning a segment. A class-conditional rule built by picking each class's #1
# will therefore never surface it, by construction. Expected consequence,
# stated up front: rule_method's overall MASE<1.0 pass rate will likely land
# BELOW MA3-alone's pass rate. The runner prints that comparison explicitly.
#
# unclassifiable (<2 nonzero training months) -> naive (safest default).
# ---------------------------------------------------------------------------
RULE_METHOD_MAP: dict[str, str] = {
    "smooth": "sba",
    "erratic": "sba",
    "intermittent": "naive",
    "lumpy": "naive",
    "unclassifiable": "naive",
}

# Deterministic tie-break for oracle_method: simplest method wins a MASE tie,
# so reruns never disagree with themselves.
TIE_BREAK_ORDER = ("naive", "ma3", "sba")


def naive_forecast(train: pd.Series, horizon: int) -> np.ndarray:
    """Last observed value, carried forward `horizon` steps (static /
    single-origin, matching evaluate_sarima()'s get_forecast(steps=...))."""
    if len(train) < 1:
        raise ValueError("naive_forecast needs at least 1 training observation")
    return np.full(horizon, float(train.iloc[-1]), dtype=float)


def moving_average_forecast(train: pd.Series, horizon: int, window: int = MA_WINDOW) -> np.ndarray:
    """Mean of the last `window` training observations (all of them if the
    series is shorter than `window`), carried forward `horizon` steps."""
    if len(train) < 1:
        raise ValueError("moving_average_forecast needs at least 1 training observation")
    tail = train.iloc[-window:] if len(train) >= window else train
    return np.full(horizon, float(tail.mean()), dtype=float)


def sba_forecast(train: pd.Series, horizon: int, alpha: float = SBA_ALPHA) -> np.ndarray:
    """Syntetos-Boylan Approximation (bias-corrected Croston) point forecast,
    carried forward `horizon` steps. Sequential pass over the whole training
    series; `alpha` smooths both the demand size (z) and the inter-demand
    interval (p). Final forecast = (z / p) * (1 - alpha/2)."""
    z: float | None = None
    p: float | None = None
    q = 1
    forecast = 0.0
    for v in train.to_numpy(dtype=float):
        if v > 0:
            if z is None:
                z, p = v, float(q)
            else:
                z = z + alpha * (v - z)
                p = p + alpha * (q - p)
            forecast = z / p if p else 0.0
            q = 1
        else:
            q += 1
    forecast *= (1 - alpha / 2)
    return np.full(horizon, float(forecast), dtype=float)


def tsb_forecast(train: pd.Series, horizon: int, alpha_demand: float = TSB_ALPHA_DEMAND,
                 alpha_prob: float = TSB_ALPHA_PROB) -> np.ndarray:
    """TSB point forecast (demand size x demand probability), carried forward
    `horizon` steps. Ported line-for-line from scripts/model_bakeoff.py m_tsb
    so the diagnostics that chose it reproduce: both states start from the
    training window's own averages, then one sequential pass updates the
    probability every month and the size only on months with a sale.

    Deliberately NOT registered in build_forecasters / TIE_BREAK_ORDER: TSB is
    served by analytics.forecasting.router for the medium bin, it is not a
    fourth candidate in the naive/ma3/sba oracle and rule picks.

    TSB reads a run of zero months as a product dying - its probability decays
    every such month. It must never be fed a synthetic 2021-22 prefix (the
    zero-padded gap before a 2025 launch took the short bin from 0.265 to
    0.430 median WAPE); the router enforces real-only history."""
    x = train.to_numpy(dtype=float)
    if len(x) < 1:
        raise ValueError("tsb_forecast needs at least 1 training observation")
    demand = x[x > 0].mean() if (x > 0).any() else 0.0
    prob = (x > 0).mean()
    for v in x:
        if v > 0:
            demand += alpha_demand * (v - demand)
            prob += alpha_prob * (1 - prob)
        else:
            prob += alpha_prob * (0 - prob)
    return np.full(horizon, float(demand * prob), dtype=float)


def demand_class(series: pd.Series, gap_months=None) -> str:
    """smooth / erratic / intermittent / lumpy / unclassifiable, via ADI
    (average inter-demand interval) and CV^2 of the nonzero demand sizes.

    Callable on a training-only slice (for rule_method) or on the full series
    (for reporting) - it just measures whatever `series` it is given.

    ADI is traits.average_demand_interval: from the first sale, with the
    principal-wide gap months in `gap_months` (month-start timestamps)
    dropped, never counted as zero-sale months. CV^2 = (std/mean)^2 of the
    nonzero values (sample std, ddof=1). Cut points: SBC 2005, ADI 1.32 and
    CV^2 0.49, the tie going to intermittent / erratic.
    Fewer than 2 nonzero months -> variance is not estimable -> unclassifiable.
    """
    values = series.to_numpy(dtype=float)
    nonzero = values[values > 0]
    n_demand = len(nonzero)
    if n_demand < 2 or nonzero.mean() <= 0:
        return "unclassifiable"

    observed = None if not gap_months else ~series.index.isin(pd.DatetimeIndex(list(gap_months)))
    adi = average_demand_interval(values, observed)
    cv2 = (nonzero.std(ddof=1) / nonzero.mean()) ** 2
    if np.isnan(cv2):
        return "unclassifiable"

    intermittent, erratic = is_intermittent_adi(adi), cv2 >= _CV2_CUT
    if not intermittent:
        return "erratic" if erratic else "smooth"
    return "lumpy" if erratic else "intermittent"


def evaluate_baseline(forecast, holdout: pd.Series, train: pd.Series) -> dict:
    """MAE, MAPE, RMSE, MASE on the holdout, plus the MASE gate result.

    forecast: array-like, same length as `holdout` (aligned positionally).

    MAPE is diagnostic_metrics.mape, the one rule: only holdout months with
    actual > 0 count. A zero month has no percentage error, and a negative
    (returns-dominated) month's percentage is meaningless, so both are
    excluded from MAPE; they stay in the series, MAE, RMSE and MASE (DEC-15:
    negatives are never clamped). If no holdout month qualifies, MAPE is
    NaN, never silently 0%.

    MASE scale - DELIBERATELY DIFFERENT from evaluate_sarima():
        scale = train.diff().abs().mean()          # plain lag-1
    not the conditional seasonal(12)/lag-1 scale sarima.py uses. No
    defensible annual seasonality exists in this data (established this
    session) and lag-1 is the standard denominator for intermittent-demand
    accuracy work.

    If the training window is flat, every lag-1 diff is 0 -> the MASE
    denominator is 0 -> MASE is UNDEFINED. It is returned as an explicit
    None (never a fabricated 0 - which would read as a perfect forecast -
    and never inf), `mase_denominator_zero` is True, and `mase_gate_passed`
    is None. `status` upstream stays 'ok': a real forecast may still exist,
    it just cannot be scored against the naive benchmark.

    Returns: {mae, mape, rmse, mase, mase_gate_passed, mase_denominator_zero}
    """
    predicted = np.asarray(forecast, dtype=float)
    actual = holdout.to_numpy(dtype=float)
    if len(predicted) != len(actual):
        raise ValueError(
            f"evaluate_baseline: forecast length {len(predicted)} != holdout length {len(actual)}"
        )

    errors = actual - predicted
    abs_errors = np.abs(errors)

    mae = float(abs_errors.mean())
    rmse = float(np.sqrt((errors ** 2).mean()))

    mape = _mape(actual, predicted)

    lag1 = train.diff().abs().dropna()
    scale = float(lag1.mean()) if not lag1.empty else 0.0
    mase_denominator_zero = not (scale > 0)

    if mase_denominator_zero:
        mase: float | None = None
        mase_gate_passed: bool | None = None
    else:
        mase = float(mae / scale)
        mase_gate_passed = mase < MASE_GATE

    return {
        "mae": mae,
        "mape": mape,
        "rmse": rmse,
        "mase": mase,
        "mase_gate_passed": mase_gate_passed,
        "mase_denominator_zero": mase_denominator_zero,
    }


def passes_mase_gate(mase, gate: float = MASE_GATE) -> bool | None:
    """MASE gate as a standalone predicate. Returns None when `mase` is
    None or NaN (undefined denominator) - callers must treat that as
    "not scored", never coerce it to False-means-failed or True-means-passed.
    """
    if mase is None:
        return None
    if isinstance(mase, float) and np.isnan(mase):
        return None
    return bool(mase < gate)


# Method name -> forecast callable. horizon and (for sba) alpha are bound by
# the caller. Kept here so the runner and any test share one registry.
def build_forecasters(horizon: int, alpha: float = SBA_ALPHA):
    return {
        "naive": lambda tr: naive_forecast(tr, horizon),
        "ma3": lambda tr: moving_average_forecast(tr, horizon, MA_WINDOW),
        "sba": lambda tr: sba_forecast(tr, horizon, alpha),
    }
