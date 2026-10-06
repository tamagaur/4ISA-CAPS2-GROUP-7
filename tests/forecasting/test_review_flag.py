"""tests/forecasting/test_review_flag.py — analytics/forecasting/review_flag.py
(the "review before ordering" flag, option D of 3226cc4)."""
from __future__ import annotations

import pandas as pd

from analytics.forecasting.review_flag import collapse_ratio, over_forecast_run, review_flag

CYCLE = pd.Timestamp("2026-03-01")


def _series(values, end="2026-02-01"):
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series([float(v) for v in values], index=idx)


def test_collapse_is_last_3_over_last_12_and_needs_12_months():
    s = _series([100] * 9 + [10, 10, 10])
    assert collapse_ratio(s, CYCLE) == 10 / ((100 * 9 + 30) / 12)
    assert collapse_ratio(_series([100] * 11), CYCLE) is None  # 11 months since the first sale
    # Months before the first sale don't count toward the 12.
    assert collapse_ratio(_series([0] * 5 + [100] * 8), CYCLE) is None


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
    falling = _series([300, 280, 260, 240, 220, 200, 180, 160, 140])  # 9 months: run yes, collapse n/a
    f = review_flag(falling, CYCLE, "short", None)
    assert f["needs_review"] is True and f["reasons"] == ["over_forecast_run"] and f["collapse"] is None

    collapsed = _series([100] * 9 + [10, 10, 40])  # rising last month: no run, but a collapse
    f = review_flag(collapsed, CYCLE, "short", None)
    assert f["reasons"] == ["collapse"] and f["over_run_months"] == 0

    steady = _series([100] * 12)
    assert review_flag(steady, CYCLE, "short", None)["needs_review"] is False
    assert review_flag(_series([100] * 4), CYCLE, None, None)["needs_review"] is None
