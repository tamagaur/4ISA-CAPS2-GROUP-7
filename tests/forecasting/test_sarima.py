"""
tests/forecasting/test_sarima.py — Tests for analytics.forecasting.sarima.

Phase 4 (CLAUDE.md Steps 12–16):
  test_temporal_split_no_leakage  — holdout set contains no training-period dates
  test_mape_gate_flag             — SKUs with MAPE ≥ 20% are flagged, not dropped
  test_forecast_within_range      — one-step forecast is plausible vs. training range
  test_parameter_log_not_empty    — AIC/BIC grid search produces non-empty param log

"""

import numpy as np
import pandas as pd
import pytest

from analytics.forecasting.sarima import (
    MAPE_GATE,
    evaluate_sarima,
    fit_sarima,
    forecast_one_step,
    grid_search_sarima,
    passes_mape_gate,
    train_holdout_split,
)

# Small grid so tests run in well under a second instead of grid-searching
# the full DEFAULT_PARAM_GRID (144 combinations) per test.
_FAST_GRID = {"p": (0, 1), "d": (0, 1), "q": (0,), "P": (0,), "D": (0,), "Q": (0,)}


def _make_series(n=36, seasonal_period=12, seed=0) -> pd.Series:
    """Deterministic synthetic monthly series with trend + seasonality,
    long enough (3 seasonal cycles) for SARIMAX to fit meaningfully."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    trend = 100 + 2 * t
    seasonal = 15 * np.sin(2 * np.pi * t / seasonal_period)
    noise = rng.normal(0, 3, size=n)
    values = trend + seasonal + noise
    index = pd.date_range("2022-01-01", periods=n, freq="MS")
    return pd.Series(values, index=index, name="demand")


def test_temporal_split_no_leakage():
    """Holdout set contains no training-period dates: every holdout
    timestamp comes strictly after every training timestamp."""
    series = _make_series(n=24)
    train, holdout = train_holdout_split(series, holdout_fraction=0.2)

    assert len(train) + len(holdout) == len(series)
    assert train.index.max() < holdout.index.min()
    assert set(train.index).isdisjoint(set(holdout.index))


def test_temporal_split_rejects_unsorted_input():
    series = _make_series(n=12)
    shuffled = series.sample(frac=1.0, random_state=1)
    with pytest.raises(ValueError):
        train_holdout_split(shuffled)


def test_mape_gate_flag():
    """SKUs with MAPE >= 20% are flagged (passes_mape_gate returns False),
    not dropped — the caller still gets a definite answer back, not an
    exception or a missing record."""
    assert passes_mape_gate(0.25) is False
    assert passes_mape_gate(MAPE_GATE) is False  # exactly at the ceiling fails the gate
    assert passes_mape_gate(0.05) is True
    # NaN MAPE (e.g. all-zero holdout) is treated as a fail, not silently
    # passed through.
    assert passes_mape_gate(float("nan")) is False


def test_forecast_within_range():
    """One-step forecast is plausible vs. the training range: for a
    series with a mild trend and no extreme outliers, the one-step-ahead
    forecast should land within a generous multiple of the training
    range, not blow up to an implausible magnitude."""
    series = _make_series(n=36)
    result = fit_sarima(series, sku_id="SKU-TEST", param_grid=_FAST_GRID)
    forecast = forecast_one_step(result)

    train_min, train_max = result.train_series.min(), result.train_series.max()
    span = train_max - train_min
    assert (train_min - span) <= forecast <= (train_max + span)


def test_parameter_log_not_empty():
    """AIC/BIC grid search produces a non-empty, reproducible param log —
    every combination attempted is recorded, whether it converged or not."""
    series = _make_series(n=36)
    train, _holdout = train_holdout_split(series)
    result = grid_search_sarima(train, sku_id="SKU-TEST", param_grid=_FAST_GRID)

    expected_combos = 2 * 2 * 1 * 1 * 1 * 1  # product of _FAST_GRID's ranges
    assert len(result.param_log) == expected_combos
    assert all(entry.aic is not None for entry in result.param_log if entry.converged)
    # the winning result is in fact the lowest AIC among converged entries
    converged_aics = [e.aic for e in result.param_log if e.converged]
    assert result.aic == min(converged_aics)


def test_evaluate_sarima_returns_expected_keys():
    series = _make_series(n=36)
    train, holdout = train_holdout_split(series)
    result = grid_search_sarima(train, sku_id="SKU-TEST", param_grid=_FAST_GRID)
    metrics = evaluate_sarima(result, holdout)

    assert set(metrics) == {"mae", "mape", "rmse", "mase", "mape_gate_passed"}
    assert metrics["mae"] >= 0
    assert metrics["rmse"] >= 0
    assert metrics["mape_gate_passed"] in (0.0, 1.0)
