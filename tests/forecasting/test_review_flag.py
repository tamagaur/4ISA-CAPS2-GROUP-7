"""tests/forecasting/test_review_flag.py — analytics/forecasting/review_flag.py
(the "review before ordering" flag, option D of 3226cc4)."""
from __future__ import annotations

import pandas as pd

from analytics.forecasting.review_flag import collapse_ratio, over_forecast_run, review_flag

CYCLE = pd.Timestamp("2026-03-01")


def _series(values, end="2026-02-01"):
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series([float(v) for v in values], index=idx)


def test_collapse_is_last_3_over_last_12():
    s = _series([100] * 9 + [10, 10, 10])
    assert collapse_ratio(s, CYCLE) == 10 / ((100 * 9 + 30) / 12)
    assert collapse_ratio(_series([100] * 20 + [10, 10, 10]), CYCLE) == 10 / ((100 * 9 + 30) / 12)  # 12 is still the longest base


def test_a_young_product_is_measured_on_the_history_it_has():
    young = _series([100] * 6 + [10, 10, 10])  # 9 months since the first sale
    assert collapse_ratio(young, CYCLE) == 10 / ((100 * 6 + 30) / 9)
    f = review_flag(young, CYCLE, "short", None)
    assert f["collapse"] is True and "collapse" in f["reasons"] and f["needs_review"] is True
    # Months before the first sale are not history: the base is the 8 months since it.
    assert collapse_ratio(_series([0] * 5 + [100] * 8), CYCLE) == 1.0


def test_three_months_or_fewer_give_nothing_to_compare():
    for months in (1, 2, 3):
        assert collapse_ratio(_series([100] * months), CYCLE) is None
    assert collapse_ratio(_series([100] * 4), CYCLE) == 1.0


def test_months_after_the_last_sale_count_as_zero():
    s = _series([100] * 12, end="2025-12-01")  # nothing sold in 2026-01 and 2026-02
    assert collapse_ratio(s, CYCLE) == (100 / 3) / (100 * 10 / 12)


def test_only_months_before_the_cycle_are_read():
    s = _series([100] * 12 + [0], end="2026-03-01")  # a 2026-03 row is the cycle itself
    assert collapse_ratio(s, CYCLE) == 1.0


def test_over_forecast_run_counts_back_from_the_month_before():
    # MA3 (short bin) over a falling series over-forecasts every month.
    s = _series([300, 280, 260, 240, 220, 200, 180, 160, 140])
    assert over_forecast_run(s, CYCLE, "short", None) == 6  # capped at the 6-month look-back
    # A rise in the last month breaks the run at once.
    assert over_forecast_run(_series([300, 280, 260, 240, 220, 200, 180, 160, 900]), CYCLE, "short", None) == 0
    # No served model: not assessed, not 0.
    assert over_forecast_run(s, CYCLE, None, None) is None
    assert over_forecast_run(s, CYCLE, "insufficient", None) is None


def test_flag_is_either_rule_and_none_only_when_neither_is_assessable():
    falling = _series([300, 280, 260, 240, 220, 200, 180, 160, 140])  # 9 months: a run, not a collapse
    f = review_flag(falling, CYCLE, "short", None)
    assert f["needs_review"] is True and f["reasons"] == ["over_forecast_run"] and f["collapse"] is False

    collapsed = _series([100] * 9 + [10, 10, 40])  # rising last month: no run, but a collapse
    f = review_flag(collapsed, CYCLE, "short", None)
    assert f["reasons"] == ["collapse"] and f["over_run_months"] == 0

    steady = _series([100] * 12)
    assert review_flag(steady, CYCLE, "short", None)["needs_review"] is False
    assert review_flag(_series([100] * 3), CYCLE, None, None)["needs_review"] is None
