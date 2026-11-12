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


# ---- product grain (2026-11-12, analytics/forecasting/calendar.py GRAIN) ----
def _demand(rows):
    """rows: {product_key: {'YYYY-MM': qty}} -> fetch_demand-shaped frame."""
    return pd.DataFrame([{"product_key": k, "calendar_month": m, "quantity": float(q)} for k, ms in rows.items() for m, q in ms.items()])


def _flat(months, level=100.0):
    return {m.strftime("%Y-%m"): level for m in pd.date_range(months[0], months[1], freq="MS")}


def test_product_factor_shrinks_own_ratio_toward_the_typical_product(monkeypatch):
    monkeypatch.setattr(calendar.params, "DECEMBER_DIP_RULE", False)
    a = _flat(("2024-01-01", "2025-05-01"))
    a["2024-06"] = 200.0                                                     # product 1: June doubled last year
    b = _flat(("2024-01-01", "2025-05-01"))                                  # products 2, 3: flat June
    c = _flat(("2024-01-01", "2025-05-01"))
    cal = calendar.ProductCalendar(_demand({1: a, 2: b, 3: c}))
    assert cal.median[pd.Timestamp("2024-06-01")] == pytest.approx(1.0)
    f, years = cal.factor(1, pd.Timestamp("2025-06-01"))
    w = 1 / (1 + calendar.params.CALENDAR_OWN_YEARS_PRIOR)
    assert years == 1 and f == pytest.approx(1 + (np.exp(w * np.log(2.0)) - 1) * CALENDAR_FACTOR_SHRINK)
    assert cal.factor(2, pd.Timestamp("2025-06-01"))[0] == pytest.approx(1.0)
    assert cal.factor(99, pd.Timestamp("2025-06-01"))[0] == pytest.approx(1.0)  # no own year: the typical product alone


def test_product_factor_reads_only_months_before_the_target(monkeypatch):
    monkeypatch.setattr(calendar.params, "DECEMBER_DIP_RULE", False)
    a = _flat(("2024-01-01", "2025-05-01"))
    a["2024-06"] = 200.0
    before = calendar.ProductCalendar(_demand({1: a})).factor(1, pd.Timestamp("2025-06-01"))
    later = dict(a, **{"2025-06": 5000.0, "2025-07": 1.0})
    assert calendar.ProductCalendar(_demand({1: later})).factor(1, pd.Timestamp("2025-06-01")) == before


def test_december_rule_takes_last_decembers_typical_dip_in_full(monkeypatch):
    rows = {k: _flat(("2023-09-01", "2024-11-01")) for k in (1, 2, 3)}
    for k in rows:
        rows[k]["2023-12"] = 60.0                                              # every product fell to 0.6 last December
    cal = calendar.ProductCalendar(_demand(rows))
    monkeypatch.setattr(calendar.params, "DECEMBER_DIP_RULE", True)
    assert cal.factor(1, pd.Timestamp("2024-12-01")) == (pytest.approx(0.6), 1)
    monkeypatch.setattr(calendar.params, "DECEMBER_DIP_RULE", False)
    assert cal.factor(1, pd.Timestamp("2024-12-01"))[0] == pytest.approx(1 + (0.6 - 1) * CALENDAR_FACTOR_SHRINK)


def test_views_and_company_totals_pass_through_calendar_factor(monkeypatch):
    cal = calendar.ProductCalendar(_demand({1: _flat(("2024-01-01", "2025-05-01"))}))
    view = calendar.for_product(cal, 1)
    assert calendar.calendar_factor(view, pd.Timestamp("2025-06-01")) == cal.factor(1, pd.Timestamp("2025-06-01"))
    totals = _december_dips(2)
    assert calendar.for_product(totals, 1) is totals and calendar.for_product(None, 1) is None
    monkeypatch.setattr(calendar.params, "CALENDAR_GRAIN", "company")
    assert isinstance(calendar.calendar_basis(_demand({1: _flat(("2024-01-01", "2024-06-01"))})), pd.Series)
    monkeypatch.setattr(calendar.params, "CALENDAR_GRAIN", "product")
    assert isinstance(calendar.calendar_basis(_demand({1: _flat(("2024-01-01", "2024-06-01"))})), calendar.ProductCalendar)
