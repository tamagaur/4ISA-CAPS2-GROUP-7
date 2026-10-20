"""tests/forecasting/test_returns_and_dead_sku.py - the two bugs from the 2026-10-20 zero-forecast audit.

1. A month where returns exceed sales (net < 0) is zero demand, not negative demand: it must not drag a
   moving average below zero (64957373: Dec -4,348 gave MA3 = -460, floored to 0 for a live product).
2. The dead-SKU test counts POSITIVE SALES in the window, not rows: returns and blank rows are not activity.

Pure pandas, no DB. Fixtures follow fetch_demand's shape (see test_blank_quantity._rows).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import scripts.run_baseline_forecast as rbf
from analytics.classification.fsn import no_sale_in_last_months
from scripts.run_baseline_forecast import moving_average_forecast
from tests.forecasting.test_blank_quantity import _rows


def test_net_negative_month_enters_the_series_as_zero():
    s = rbf.build_series(_rows([2957, -4348, 12]))            # Jan sold, Dec-style net return month, Feb sold
    assert s.tolist() == [2957.0, 0.0, 12.0]
    assert (s.dropna() >= 0).all()


def test_ma3_is_no_longer_dragged_below_zero_by_a_returns_month():
    q = [100, 50, -4348, 12]
    raw = float(moving_average_forecast(pd.Series(q, dtype=float), 1, 3)[0])
    fixed = float(moving_average_forecast(rbf.build_series(_rows(q)), 1, 3)[0])
    assert raw < 0                                             # the bug: the average went negative
    assert fixed == (50 + 0 + 12) / 3                          # the fix: a zero-demand month, product still alive


def test_a_blank_month_stays_missing_not_zero():
    s = rbf.build_series(_rows([10, None, -5, 30]))
    assert np.isnan(s.iloc[1]) and s.iloc[2] == 0.0


def test_positive_months_are_untouched():
    q = [5, 0, 7, 11]
    assert rbf.build_series(_rows(q)).tolist() == [float(x) for x in q]


def test_window_with_only_returns_has_no_sale():
    s = rbf.build_series(_rows([900, 800, -10, -20, -5, -1, -3, -2], start="2025-01"))
    assert no_sale_in_last_months(s.index.strftime("%Y-%m"), s.to_numpy(), "2025-08")   # last 6 months: returns only


def test_window_with_returns_and_blanks_has_no_sale():
    s = rbf.build_series(_rows([900, 800, -10, None, -5, None, -3, None], start="2025-01"))
    assert no_sale_in_last_months(s.index.strftime("%Y-%m"), s.to_numpy(), "2025-08")


def test_runner_dead_test_no_longer_exempts_blank_months():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2] / "scripts/run_baseline_forecast.py").read_text(encoding="utf-8")
    block = src.split("# Activity is a POSITIVE SALE", 1)[1].split("evaluate_sku(series", 1)[0]
    assert "_missing_in_last_months" not in block
