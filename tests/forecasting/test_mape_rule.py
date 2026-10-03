"""tests/forecasting/test_mape_rule.py — item 5: one MAPE denominator rule.

Only months with actual > 0 enter MAPE, in every place it is computed; a
returns month (actual < 0) is excluded from MAPE but kept in MAE / MASE."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.forecasting.baseline import evaluate_baseline
from analytics.forecasting.diagnostic_metrics import mape


def _series(values, start="2024-01-01"):
    return pd.Series(np.asarray(values, dtype=float), index=pd.date_range(start, periods=len(values), freq="MS"))


def test_a_returns_month_is_out_of_mape_but_in_mae():
    train = _series([10, 12, 11, 13, 12, 14])
    holdout = _series([10, -5, 0, 20], start="2024-07-01")
    forecast = [12.0, 12.0, 12.0, 12.0]
    m = evaluate_baseline(forecast, holdout, train)
    # MAPE over the two months with actual > 0 only: |10-12|/10 and |20-12|/20.
    assert m["mape"] == pytest.approx((0.2 + 0.4) / 2)
    assert m["mape"] == pytest.approx(mape(holdout, forecast))
    # MAE keeps all four months, the -5 returns month included (DEC-15).
    assert m["mae"] == pytest.approx((2 + 17 + 12 + 8) / 4)


def test_no_positive_month_is_nan_not_zero():
    m = evaluate_baseline([1.0, 1.0], _series([0, -3], start="2024-07-01"), _series([1, 2, 3]))
    assert np.isnan(m["mape"])
