"""tests/forecasting/test_diagnostic_metrics.py — hand-computed checks of the
one module allowed to define the diagnostic metrics
(analytics/forecasting/diagnostic_metrics.py).

Every expected value below is worked out by hand in the comment next to it, so
a change in a convention (what a negative actual does, where the MASE scale
comes from) fails here before it changes a bake-off number.

Pure numpy - no DB.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from analytics.forecasting.diagnostic_metrics import (
    is_mape_unstable, mape, mase, naive_scale, smape, wape,
)

ACTUAL = [100.0, 200.0, 50.0]
PRED = [110.0, 180.0, 50.0]          # abs errors 10, 20, 0


def test_wape_hand_computed():
    assert wape(ACTUAL, PRED) == pytest.approx(30 / 350)


def test_mape_hand_computed():
    assert mape(ACTUAL, PRED) == pytest.approx((0.10 + 0.10 + 0.0) / 3)


def test_smape_hand_computed():
    # 2*10/210, 2*20/380, 0
    assert smape(ACTUAL, PRED) == pytest.approx((20 / 210 + 40 / 380 + 0) / 3)


def test_mase_hand_computed_with_passed_scale():
    assert mase(ACTUAL, PRED, scale=5.0) == pytest.approx(10.0 / 5.0)


def test_mase_never_computes_its_own_scale():
    for bad in (0.0, -1.0, float("nan"), float("inf"), None):
        assert math.isnan(mase(ACTUAL, PRED, scale=bad))


# ---- zero actuals ----------------------------------------------------------
def test_zero_actual_is_dropped_from_mape_kept_in_wape_and_smape():
    a, p = [0.0, 100.0], [10.0, 90.0]
    assert mape(a, p) == pytest.approx(0.10)                     # only the 100 month
    assert wape(a, p) == pytest.approx(20 / 100)                 # both errors, sum|a| = 100
    assert smape(a, p) == pytest.approx((2 * 10 / 10 + 2 * 10 / 190) / 2)


def test_all_zero_actuals():
    a, p = [0.0, 0.0], [0.0, 0.0]
    assert math.isnan(mape(a, p)) and math.isnan(wape(a, p)) and math.isnan(smape(a, p))


# ---- the one negative-actual rule -------------------------------------------
def test_negative_actual_excluded_from_mape_included_in_wape_and_smape():
    a, p = [-50.0, 100.0], [0.0, 80.0]                           # abs errors 50, 20
    assert mape(a, p) == pytest.approx(0.20)                     # the -50 month is not there
    assert wape(a, p) == pytest.approx(70 / 150)                 # sum|a| = 50 + 100
    assert smape(a, p) == pytest.approx((2 * 50 / 50 + 2 * 20 / 180) / 2)


def test_only_negative_actuals_gives_nan_mape_but_a_wape():
    a, p = [-10.0, -30.0], [0.0, 0.0]
    assert math.isnan(mape(a, p))
    assert wape(a, p) == pytest.approx(1.0)


# ---- scale ignores a synthetic prefix --------------------------------------
def test_scale_comes_from_real_months_only():
    real_train = np.array([10.0, 14.0, 12.0, 20.0])              # |diffs| 4, 2, 8 -> 14/3
    synthetic_prefix = np.array([5000.0, 1.0, 9000.0, 2.0])      # wild on purpose
    scale = naive_scale(real_train)
    assert scale == pytest.approx(14 / 3)
    # Attaching the prefix would have produced a different yardstick - which is
    # exactly why callers pass real months only and mase() takes the scale in.
    assert naive_scale(np.concatenate([synthetic_prefix, real_train])) != pytest.approx(scale)
    a, p = [20.0, 30.0], [26.0, 22.0]                            # MAE 7
    assert mase(a, p, scale) == pytest.approx(7 / (14 / 3))


def test_naive_scale_short_series():
    assert naive_scale([]) == 0.0 and naive_scale([5.0]) == 0.0


# ---- is_mape_unstable --------------------------------------------------------
def test_stable_holdout():
    unstable, min_abs = is_mape_unstable([100.0, 120.0, 90.0])
    assert unstable is False and min_abs == 90.0


def test_near_zero_actual_is_unstable_and_reports_the_minimum():
    # min 31 vs mean |a| of (31 + 3*20000)/4 = 15007.75 -> ratio 0.002
    unstable, min_abs = is_mape_unstable([31.0, 20000.0, 20000.0, 20000.0])
    assert unstable is True and min_abs == 31.0


def test_non_positive_actual_is_unstable():
    assert is_mape_unstable([0.0, 100.0, 100.0]) == (True, 0.0)
    unstable, min_abs = is_mape_unstable([-124.0, 100.0, 110.0])
    assert unstable is True and min_abs == 100.0                 # min of |actual|


def test_ratio_boundary_is_strict():
    # min/mean = 10 / 100 = 0.10 exactly -> not below the ratio -> stable
    assert is_mape_unstable([10.0, 190.0], ratio=0.10)[0] is False
    assert is_mape_unstable([9.0, 191.0], ratio=0.10)[0] is True


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        wape([1.0, 2.0], [1.0])


def test_rmse_includes_every_actual_and_is_nan_when_empty():
    from analytics.forecasting.diagnostic_metrics import rmse
    assert rmse([3.0, -1.0, 0.0], [0.0, -1.0, 4.0]) == pytest.approx(np.sqrt((9 + 0 + 16) / 3))
    assert np.isnan(rmse([], []))
