"""tests/forecasting/test_calendar.py - the company calendar factor and its
router hook. Synthetic fixtures only, no DB."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.forecasting import calendar, router
from analytics.params import CALENDAR_FACTOR_SHRINK


def _totals(values, start="2023-01-01") -> pd.Series:
    return pd.Series(np.asarray(values, float), index=pd.date_range(start, periods=len(values), freq="MS"))


def _december_dips(years=3, dip=0.5) -> pd.Series:
    """Flat 100 every month, December at `dip` x 100."""
    idx = pd.date_range("2023-01-01", periods=12 * years, freq="MS")
    return pd.Series([100.0 * (dip if m.month == 12 else 1.0) for m in idx], index=idx)


def test_no_earlier_year_means_no_adjustment():
    assert calendar.calendar_factor(_december_dips(1), pd.Timestamp("2023-12-01")) == (1.0, 0)


def test_factor_is_shrunk_halfway_to_one():
    factor, years = calendar.calendar_factor(_december_dips(2), pd.Timestamp("2024-12-01"))
    assert years == 1
    assert factor == pytest.approx(1 + (0.5 - 1) * CALENDAR_FACTOR_SHRINK)


def test_geometric_mean_over_years():
    t = _december_dips(3)
    t[pd.Timestamp("2024-12-01")] = 200.0          # one year x2, one year x0.5 -> geometric mean 1
    factor, years = calendar.calendar_factor(t, pd.Timestamp("2025-12-01"))
    assert years == 2 and factor == pytest.approx(1.0)


def test_reads_only_months_before_target():
    t = _december_dips(2)
    before = calendar.calendar_factor(t, pd.Timestamp("2024-12-01"))
    t[pd.Timestamp("2024-12-01")] = 1e9             # the target month itself must not leak in
    t[pd.Timestamp("2025-01-01")] = 1e9
    assert calendar.calendar_factor(t, pd.Timestamp("2024-12-01")) == before


def test_missing_prior_month_skips_that_year():
    t = _december_dips(2).drop(pd.Timestamp("2023-10-01"))
    assert calendar.calendar_factor(t, pd.Timestamp("2024-12-01")) == (1.0, 0)


def test_company_totals_skip_blank_months_never_zero():
    demand = pd.DataFrame({"calendar_month": ["2023-01", "2023-01", "2023-02"],
                           "quantity": [10.0, np.nan, np.nan]})
    tot = calendar.company_totals(demand)
    assert list(tot.index) == [pd.Timestamp("2023-01-01")] and tot.iloc[0] == 10.0


def test_router_without_totals_is_unchanged():
    s = _totals(range(80, 110))
    m = s.index[-1] + pd.DateOffset(months=1)
    r = router.route(s, m)
    assert "calendar_factor" not in r


def test_router_applies_factor_after_guards_and_keeps_benchmark():
    tot = _december_dips(2)
    m = pd.Timestamp("2024-12-01")
    s = _totals(np.random.default_rng(3).integers(80, 120, 23))      # 23 sales months: medium bin, TSB
    plain = router.route(s, m)
    adj = router.route(s, m, calendar_totals=tot)
    assert adj["value_before_calendar"] == pytest.approx(plain["value"])
    assert adj["value"] == pytest.approx(plain["value"] * adj["calendar_factor"])
    assert adj["ma3_value"] == plain["ma3_value"]                    # benchmark never adjusted


def test_rolling_one_step_passes_totals_through():
    s = _totals(np.random.default_rng(5).integers(80, 120, 24))
    tot = _december_dips(2)
    months = [pd.Timestamp("2024-11-01"), pd.Timestamp("2024-12-01")]
    plain = router.rolling_one_step(s, months)
    adj = router.rolling_one_step(s, months, calendar_totals=tot)
    dec = adj["month"] == pd.Timestamp("2024-12-01")
    assert (adj.loc[dec, "value"].iloc[0] < plain.loc[dec, "value"].iloc[0])
    assert (adj["ma3"].to_numpy() == plain["ma3"].to_numpy()).all()
