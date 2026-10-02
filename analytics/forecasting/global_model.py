"""
analytics.forecasting.global_model - one gradient-boosted model trained
across SKUs, forecasting one month ahead.

A per-SKU series here is at most 38 months, too short to fit trees on. This
model pools every SKU in the training pool instead: each (SKU, month) with at
least MIN_HISTORY months of history before it is one training row. Features
and target are divided by the SKU's own last-6-month mean, so a SKU selling
10,000 a month and one selling 50 look alike to the model and it learns the
shape of demand, not its level. (Measured 2026-09-21: the same model without
that scaling gained nothing over MA3.)

Pure functions, no DB access. The caller passes real-only series; the router
(analytics.forecasting.router) enforces that.

Fixed on purpose, not tuned: one configuration, one seed, one thread. Nothing
here was tuned on test months, and nthread=1 (analytics.params.XGB_NTHREAD)
keeps a rerun bit-identical. The stored bake-off artifacts were not all fitted
single-threaded (8 or 4 threads; params.py lists which), so a served-vs-
artifact comparison can differ in the last digits for that reason alone. No
model file is saved - training takes seconds, so the model is refit from the
pool on every run and a missing or stale artifact cannot happen.

Status (2026-09-21): in the long bin the average of this model and MA3 TIES
MA3 on real Tier A data (half-year blocks: no wins, four ties, one loss). It
is served because it is a trained model, not because it is more accurate.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb

from analytics.params import XGB_NTHREAD

PLACEHOLDER_ATTR = "placeholder_months"  # series.attrs key marking is_demo months (see with_placeholder)
MIN_HISTORY = 3                          # months of history before a month can be a training row
MIN_TRAINING_ROWS = 100                  # below this no model is returned (the diagnostics' own floor)
SCALE_WINDOW = 6
SEED = 20260921
PARAMS = {
    "max_depth": 4, "eta": 0.05, "subsample": 0.8, "colsample_bytree": 0.8,
    "objective": "reg:absoluteerror", "seed": SEED, "nthread": XGB_NTHREAD,
}
NUM_ROUNDS = 300

FEATURE_NAMES = (
    "lag1", "lag2", "lag3", "lag4", "lag5", "lag6", "lag12",
    "mean3", "mean12", "std6",          # all ten above are divided by the scale
    "zeros_last6", "months_history", "share_months_with_sale", "month_of_year",
)


def with_placeholder(series: pd.Series, months) -> pd.Series:
    """A copy of `series` with `months` marked as placeholder (is_demo) rows.
    The mark lives in series.attrs[PLACEHOLDER_ATTR]; only a caller that built
    the series from is_demo rows sets it."""
    out = series.copy()
    out.attrs[PLACEHOLDER_ATTR] = frozenset(pd.Timestamp(m) for m in months)
    return out


def assert_real_history(series: pd.Series, allow_placeholder: bool = False) -> None:
    """Raise if the series carries placeholder (is_demo) months. Real months
    pass whatever their date, so SSM's real 2021-22 files replace the
    placeholder with no code change. allow_placeholder=True is for the
    what-if preview only (scripts/preview_router_synth.py); the live router
    never sets it."""
    marked = series.attrs.get(PLACEHOLDER_ATTR)
    if not allow_placeholder and marked and series.index.isin(list(marked)).any():
        raise ValueError(
            f"history contains {int(series.index.isin(list(marked)).sum())} placeholder (is_demo) months: "
            "placeholder rows must never reach a live forecast - read the _Real view"
        )


def from_first_sale(series: pd.Series) -> pd.Series:
    """Months before the first sale are 'not launched yet', not zero demand
    (same rule as analytics.segmentation.traits.from_first_sale)."""
    sold = np.nonzero(series.to_numpy(dtype=float) > 0)[0]
    return series.iloc[sold[0]:] if len(sold) else series.iloc[:0]


def build_features(history: np.ndarray, target_month: pd.Timestamp) -> tuple[np.ndarray | None, float]:
    """(features, scale) for forecasting `target_month` from `history`, the
    months strictly before it, oldest first, starting at the first sale.
    Returns (None, scale) when the last-6-month mean is not positive: there
    is no level to scale by, so this model has no forecast for that month."""
    tr = np.asarray(history, dtype=float)
    scale = float(tr[-SCALE_WINDOW:].mean()) if len(tr) else 0.0
    if not scale > 0:
        return None, scale

    def lag(k: int) -> float:
        return tr[-k] / scale if len(tr) >= k else np.nan

    last6 = tr[-SCALE_WINDOW:]
    feats = [
        lag(1), lag(2), lag(3), lag(4), lag(5), lag(6), lag(12),
        tr[-3:].mean() / scale,
        tr[-12:].mean() / scale if len(tr) >= 12 else np.nan,
        last6.std() / scale,
        float((last6 <= 0).sum()),
        float(len(tr)),
        float((tr > 0).sum() / len(tr)),
        float(target_month.month),
    ]
    return np.asarray(feats, dtype=float), scale


def training_rows(pool: dict, before: pd.Timestamp, allow_placeholder: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Every (SKU, month) in `pool` with month < `before` and at least
    MIN_HISTORY months of history since first sale. Target = that month's
    quantity / scale. `before` is exclusive, so nothing at or after the month
    being forecast can enter training."""
    X, y = [], []
    for series in pool.values():
        assert_real_history(series, allow_placeholder)
        s = from_first_sale(series)
        values = s.to_numpy(dtype=float)
        for t in range(MIN_HISTORY, len(s)):
            month = s.index[t]
            if month >= before:
                break
            feats, scale = build_features(values[:t], month)
            if feats is not None:
                X.append(feats)
                y.append(values[t] / scale)
    if not X:
        return np.empty((0, len(FEATURE_NAMES))), np.empty(0)
    return np.vstack(X), np.asarray(y, dtype=float)


class GlobalForecaster:
    """Holds the training pool and refits per target month on demand. One
    booster per month is cached for the life of the object only."""

    def __init__(self, pool: dict, allow_placeholder: bool = False):
        self.pool = pool
        self.allow_placeholder = allow_placeholder      # preview script only; the live router never sets it
        self._cache: dict[pd.Timestamp, tuple[xgb.Booster | None, int]] = {}

    def booster_for(self, target_month: pd.Timestamp) -> tuple[xgb.Booster | None, int]:
        """(model trained on months strictly before `target_month`, training
        rows). The model is None when the pool is under MIN_TRAINING_ROWS."""
        if target_month not in self._cache:
            X, y = training_rows(self.pool, before=target_month, allow_placeholder=self.allow_placeholder)
            booster = None
            if len(y) >= MIN_TRAINING_ROWS:
                booster = xgb.train(PARAMS, xgb.DMatrix(X, label=y), num_boost_round=NUM_ROUNDS)
            self._cache[target_month] = (booster, int(len(y)))
        return self._cache[target_month]

    def forecast(self, series: pd.Series, target_month: pd.Timestamp) -> tuple[float | None, int, str | None]:
        """(one-step forecast for `target_month`, training rows, reason).
        The forecast is None with a reason when this model cannot produce a
        number; the caller falls back. Only months before `target_month` are
        read from `series`."""
        assert_real_history(series, self.allow_placeholder)
        booster, n_rows = self.booster_for(target_month)
        if booster is None:
            return None, n_rows, f"xgb_unavailable: {n_rows} training rows < {MIN_TRAINING_ROWS}"
        history = from_first_sale(series[series.index < target_month]).to_numpy(dtype=float)
        feats, scale = build_features(history, target_month)
        if feats is None:
            return None, n_rows, "xgb_no_forecast: last-6-month mean is not positive"
        value = float(booster.predict(xgb.DMatrix(feats.reshape(1, -1)))[0]) * scale
        if not np.isfinite(value):
            return None, n_rows, "xgb_no_forecast: non-finite prediction"
        return value, n_rows, None
