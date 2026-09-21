"""
analytics.forecasting.switching - when a live challenger goes back to MA3.

Rule locked 2026-09-21. A bin's challenger (TSB for medium, the XGBoost+MA3
average for long) reverts to MA3 only if MA3 CLEARS THE BAR against it over a
rolling 6-month window:

    1. the 95% bootstrap interval on
           median per-SKU WAPE(challenger) - median per-SKU WAPE(MA3)
       lies entirely above zero (the challenger is measurably worse), AND
    2. more SKUs do better under MA3 than under the challenger.

A tie keeps the challenger. That is deliberate: the challengers are served
because they are trained models, not because they beat MA3, so "no measurable
difference" is the expected state and not a reason to switch. (A bare "3
losing months in a row" rule was replayed on history and would have fired for
both bins by chance - two tied models each lose about 4 months in 10.)

The evaluator takes already-scored rows; it does not read the DB and nothing
calls it on live data yet. Per-SKU WAPE comes from diagnostic_metrics.wape;
the MA3 column must be router.rolling_one_step's, i.e. baseline's MA3.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.forecasting.diagnostic_metrics import wape

WINDOW_MONTHS = 6
CI_LEVEL = 0.95
N_BOOT = 1000
SEED = 20260921
MIN_ORIGINS_PER_SKU = 3   # a per-SKU WAPE over fewer months is not scored (scripts/model_bakeoff.py's floor)
MIN_SKUS = 5              # under this there is no interval to speak of


def evaluate_switch(scored: pd.DataFrame, window_end: pd.Timestamp) -> dict:
    """Decide revert / keep for one bin.

    `scored`: one row per (SKU, month) already served in this bin, columns
    product_key, month, actual, challenger, ma3. Only the WINDOW_MONTHS
    months ending at `window_end` are read.
    """
    start = window_end - pd.DateOffset(months=WINDOW_MONTHS - 1)
    window = scored[(scored["month"] >= start) & (scored["month"] <= window_end)]

    pairs = []
    for _, g in window.groupby("product_key"):
        if len(g) < MIN_ORIGINS_PER_SKU:
            continue
        c, m = wape(g["actual"], g["challenger"]), wape(g["actual"], g["ma3"])
        if np.isfinite(c) and np.isfinite(m):
            pairs.append((c, m))
    result = {
        "window_start": start, "window_end": window_end, "n_skus": len(pairs), "revert_to_ma3": False,
        "challenger_median_wape": None, "ma3_median_wape": None, "diff_ci": None,
        "skus_better_under_ma3": None, "skus_better_under_challenger": None,
    }
    if len(pairs) < MIN_SKUS:
        return {**result, "reason": f"keep challenger: only {len(pairs)} scorable SKUs, under {MIN_SKUS}"}

    arr = np.asarray(pairs, dtype=float)
    chall, ma3 = arr[:, 0], arr[:, 1]
    idx = np.random.default_rng(SEED).integers(0, len(arr), size=(N_BOOT, len(arr)))
    diff = np.median(chall[idx], axis=1) - np.median(ma3[idx], axis=1)
    tail = (1 - CI_LEVEL) / 2 * 100
    lo, hi = (float(v) for v in np.percentile(diff, [tail, 100 - tail]))
    better_ma3, better_chall = int((ma3 < chall).sum()), int((chall < ma3).sum())

    interval_clears = lo > 0
    more_improve = better_ma3 > better_chall
    revert = interval_clears and more_improve
    if revert:
        reason = "revert: MA3 clears the bar (interval above zero and more SKUs improve under MA3)"
    elif interval_clears:
        reason = "keep challenger: interval favours MA3 but it does not improve more SKUs"
    else:
        reason = "keep challenger: interval includes zero or favours the challenger (a tie keeps the challenger)"
    return {
        **result, "revert_to_ma3": bool(revert), "reason": reason,
        "challenger_median_wape": float(np.median(chall)), "ma3_median_wape": float(np.median(ma3)),
        "diff_ci": (lo, hi), "skus_better_under_ma3": better_ma3, "skus_better_under_challenger": better_chall,
    }
