"""tests/forecasting/test_leak_check.py — the pipeline leak check.

MA3 reads the last 3 months of its training window and naive reads the last 1.
In the with/without-synthetic diagnostic the first test origin is a REAL month
with >= 12 real months before it, so neither method can reach a 2021-22
synthetic prefix: their forecasts, and therefore their real-vs-synthetic arm
delta, are ARITHMETICALLY identical.

This documents the leak check. It is NOT evidence that the synthetic data is
non-distorting - a delta of 0 here is guaranteed whatever the prefix contains
(the test feeds it garbage to make that point). A non-zero delta would mean a
bug: prefix months leaking into the test window or into the MASE scale. The
non-distortion claim rests only on the models that CAN see the prefix (ARIMA,
SARIMA, XGBoost).

Pure numpy/pandas - no DB.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import scripts.model_bakeoff as mb
from analytics.forecasting.baseline import MA_WINDOW, moving_average_forecast, naive_forecast

TEST_MONTHS, MIN_TRAIN = 6, 12


def _real() -> pd.Series:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2023-01-01", periods=38, freq="MS")
    return pd.Series(rng.integers(50, 500, size=38).astype(float), index=idx)


def _with_prefix(real: pd.Series, values) -> pd.Series:
    idx = pd.date_range("2021-01-01", periods=24, freq="MS")
    return pd.concat([pd.Series(np.asarray(values, float), index=idx), real])


PREFIXES = {
    "zeros": np.zeros(24),
    "huge": np.full(24, 1e9),
    "noise": np.random.default_rng(1).normal(0, 1e6, 24).clip(0),
}


def test_short_window_models_read_only_the_tail():
    x = np.arange(1.0, 41.0)
    garbage_head = np.concatenate([np.full(24, 1e9), x])
    assert mb.m_ma3(garbage_head) == mb.m_ma3(x) == pytest.approx(39.0)
    assert mb.m_naive(garbage_head) == mb.m_naive(x) == 40.0


def test_deployed_ma3_and_naive_read_only_the_tail():
    assert MA_WINDOW == 3
    x = pd.Series(np.arange(1.0, 41.0))
    head = pd.concat([pd.Series(np.full(24, 1e9)), x], ignore_index=True)
    assert list(moving_average_forecast(head, 1, MA_WINDOW)) == list(moving_average_forecast(x, 1, MA_WINDOW))
    assert list(naive_forecast(head, 1)) == list(naive_forecast(x, 1))


def test_first_origin_leaves_the_prefix_out_of_reach():
    real = _real()
    origins = mb.real_origins(real, TEST_MONTHS, MIN_TRAIN)
    first_pos = real.index.get_loc(origins[0])
    # at least MIN_TRAIN real months sit between any prefix and the first origin
    assert first_pos >= MIN_TRAIN > MA_WINDOW


@pytest.mark.parametrize("name", PREFIXES)
def test_arm_delta_is_zero_for_ma3_and_naive_whatever_the_prefix(name):
    real = _real()
    base = mb.backtest_sku(real, real, TEST_MONTHS, MIN_TRAIN)
    arm = mb.backtest_sku(real, _with_prefix(real, PREFIXES[name]), TEST_MONTHS, MIN_TRAIN)
    for model in ("ma3", "naive"):
        for metric in ("mape", "wape", "smape", "mase"):
            assert arm[model][metric] == base[model][metric], (model, metric)


def test_the_check_has_teeth_full_history_models_do_move():
    """`mean` fits on the whole training window, so the same garbage prefix
    must change it - otherwise the test above would pass vacuously."""
    real = _real()
    base = mb.backtest_sku(real, real, TEST_MONTHS, MIN_TRAIN)
    arm = mb.backtest_sku(real, _with_prefix(real, PREFIXES["huge"]), TEST_MONTHS, MIN_TRAIN)
    assert arm["mean"]["wape"] != base["mean"]["wape"]


def test_mase_scale_ignores_the_prefix():
    """Same forecasts + same scale -> same MASE. If the scale were taken from
    the combined series, the 1e9 prefix would crush MA3's MASE toward 0."""
    real = _real()
    base = mb.backtest_sku(real, real, TEST_MONTHS, MIN_TRAIN)
    arm = mb.backtest_sku(real, _with_prefix(real, PREFIXES["huge"]), TEST_MONTHS, MIN_TRAIN)
    assert arm["ma3"]["mase"] == base["ma3"]["mase"] > 0


def test_cohort_is_decided_by_the_real_series_only():
    """A SKU with too little REAL history stays un-evaluable however long a
    synthetic prefix makes its training series."""
    short_real = _real().iloc[:13]
    assert mb.backtest_sku(short_real, short_real, TEST_MONTHS, MIN_TRAIN) is None
    assert mb.backtest_sku(short_real, _with_prefix(short_real, PREFIXES["noise"]), TEST_MONTHS, MIN_TRAIN) is None
