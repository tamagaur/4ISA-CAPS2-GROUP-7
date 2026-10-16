"""tests/forecasting/test_blank_quantity_consumers.py - the three readers that used to read a blank
quantity as 0 (backend/routers/decomposition.py, scripts/model_bakeoff.py, scripts/run_lp.py) now
leave it out, the same rule the forecast runner already follows (test_blank_quantity.py).

"Blank" = a row that exists with quantity_sold NULL. A month with NO row is still a zero-sale month.
Pure numpy/pandas, no DB: a fake session / cursor stands in for the read.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import scripts.model_bakeoff as mb
import scripts.run_lp as rlp
from analytics.forecasting.decomposition import LABEL_NO_PATTERN, stl_summary, yearly_pattern
from backend.routers import decomposition as router


def _periods(n: int, start="2023-01") -> list[str]:
    return list(pd.period_range(start, periods=n, freq="M").astype(str))


def _seasonal(n: int) -> list[float]:
    return [1000 + 300 * math.cos(2 * math.pi * (i - 11) / 12) + (3 if i % 2 else -3) for i in range(n)]


# ---- backend/routers/decomposition.py ---------------------------------------------------------------------------
class _Result:
    def __init__(self, rows=None, scalar=None):
        self._rows, self._scalar = rows, scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class _FakeDb:
    def __init__(self, rows, latest):
        self.rows, self.latest, self.sql = rows, latest, []

    def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        return _Result(rows=self.rows) if "GROUP BY" in str(stmt) else _Result(scalar=self.latest)


def test_router_series_marks_a_blank_month_nan_and_a_missing_row_zero():
    rows = [{"period": "2025-01", "qty": 10}, {"period": "2025-02", "qty": None}, {"period": "2025-04", "qty": 40}]
    db = _FakeDb(rows, "2025-05")
    periods, values = router._monthly_series(db, "unilever_sku_demand_fact_real", 1)
    assert periods == ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]
    assert values[0] == 10.0
    assert math.isnan(values[1])                       # row with blank quantity: NaN, never 0
    assert values[2] == 0.0                            # no row: a zero-sale month, unchanged
    assert values[3] == 40.0 and values[4] == 0.0
    assert "quantity_sold IS NULL" in db.sql[0]        # a blank among several rows blanks the month


# ---- the lag-12 label ---------------------------------------------------------------------------------------------
def test_yearly_pattern_skips_a_blank_month_instead_of_reading_zero():
    y = _seasonal(36)
    with_zero = list(y)
    with_zero[14] = 0.0
    blank = list(y)
    blank[14] = float("nan")
    z, b = yearly_pattern(with_zero), yearly_pattern(blank)
    assert b["blank_months"] == 1 and b["months"] == 35
    assert b["acf_lag12"] is not None and not math.isnan(b["acf_lag12"])
    assert b["acf_lag12"] != z["acf_lag12"]            # the zero is no longer in the test


def test_yearly_pattern_without_a_blank_is_unchanged():
    out = yearly_pattern(_seasonal(36))
    assert out["blank_months"] == 0 and out["months"] == 36 and out["repeats_yearly"] is True


def test_yearly_pattern_counts_only_observed_months_toward_the_minimum():
    y = _seasonal(24)
    y[3] = y[7] = float("nan")
    out = yearly_pattern(y)
    assert out["repeats_yearly"] is None and out["months"] == 22 and out["blank_months"] == 2


def test_a_blank_before_the_first_sale_does_not_count():
    y = [float("nan"), 0.0] + _seasonal(30)
    assert yearly_pattern(y)["blank_months"] == 0


def test_stl_reports_a_blank_month_instead_of_filling_it():
    y = _seasonal(40)
    y[10] = float("nan")
    s = stl_summary(_periods(40), y)
    assert s["available"] is False and s["blank_months"] == 1
    assert "blank" in s["reason"] and "not zero" in s["reason"]


# ---- scripts/model_bakeoff.py -----------------------------------------------------------------------------------
def _g(q, start="2023-01", absent=()):
    months = _periods(len(q), start)
    df = pd.DataFrame({"calendar_month": months, "q": [np.nan if v is None else float(v) for v in q]})
    return df[~df["calendar_month"].isin(absent)]


def test_bakeoff_series_keeps_a_blank_nan_and_a_missing_row_zero():
    s = mb.build_series(_g([10, None, 30, 40, 50], absent=("2023-04",)))
    assert s.loc["2023-02-01"] != s.loc["2023-02-01"]  # NaN
    assert s.loc["2023-04-01"] == 0.0
    assert s.loc["2023-03-01"] == 30.0


def test_bakeoff_does_not_score_a_blank_actual_and_trains_without_it():
    vals = list(np.random.default_rng(3).integers(80, 120, 30).astype(float))
    full = mb.build_series(_g(vals))
    gap = list(vals)
    gap[-2] = None                                     # a blank inside the 6-month test window
    s = mb.build_series(_g(gap))
    out = mb.backtest_sku(s, s, 6, 12)
    assert out is not None
    # MA3 at the last origin reads the three newest OBSERVED months, not a 0
    ref = mb.backtest_sku(full, full, 6, 12)
    assert out["ma3"]["mape"] != ref["ma3"]["mape"]
    assert np.isfinite(out["ma3"]["mape"])


def test_bakeoff_sku_with_too_many_blank_actuals_is_not_evaluable():
    vals = list(np.random.default_rng(4).integers(80, 120, 30).astype(float))
    gap = list(vals)
    for i in (-1, -2, -3, -4):
        gap[i] = None
    s = mb.build_series(_g(gap))
    assert mb.backtest_sku(s, s, 6, 12) is None       # 2 scorable origins left, under the 3 minimum


# ---- scripts/run_lp.py ------------------------------------------------------------------------------------------
class _Cur:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.rows


def _demand(rows):
    return pd.DataFrame(rows, columns=["product_key", "sku_code", "principal", "period", "total_quantity", "total_amount"])


def test_run_lp_demand_history_keeps_a_blank_quantity_nan():
    df = rlp.fetch_demand_history(_Cur([(1, "A", "unilever", "2025-01", 10, 100), (1, "A", "unilever", "2025-02", None, 250)]), [1])
    assert df["total_quantity"].iloc[0] == 10.0
    assert math.isnan(df["total_quantity"].iloc[1])
    assert df["total_amount"].iloc[1] == 250.0         # the peso amount is untouched


def test_run_lp_sigma_ignores_a_blank_month():
    qty = [100, 120, 80, 110, 90, 105]
    rows = [(1, "A", "unilever", p, q, 1.0) for p, q in zip(_periods(6, "2025-01"), qty)]
    clean = rlp._sigma_d_for_product(_demand(rows), "unilever")[0]
    blanked = rows + [(1, "A", "unilever", "2025-07", None, 1.0)]
    with_zero = rows + [(1, "A", "unilever", "2025-07", 0.0, 1.0)]
    s_blank = rlp._sigma_d_for_product(_demand(blanked), "unilever")[0]
    s_zero = rlp._sigma_d_for_product(_demand(with_zero), "unilever")[0]
    assert s_blank == pytest.approx(clean, rel=0.05)   # only the avg business-day count moves, by a month's worth
    assert s_zero > s_blank * 1.5                      # a zero would have inflated sigma


def test_run_lp_all_blank_product_is_refused_not_zero_filled():
    sigma, reason = rlp._sigma_d_for_product(_demand([(1, "A", "unilever", "2025-01", None, 5.0),
                                                      (1, "A", "unilever", "2025-02", None, 5.0)]), "unilever")
    assert sigma is None and "insufficient demand history" in reason


def test_run_lp_prior_year_pieces_skips_a_blank_month():
    hist = _demand([(1, "A", "unilever", "2025-01", 10, 1.0), (1, "A", "unilever", "2025-02", None, 1.0),
                    (1, "A", "unilever", "2025-03", 30, 1.0)])
    p, reason = rlp.product_input(1, "A", "unilever", 5.0, 1.0, {1: (True, 50.0, 2.0)}, hist, prior_year=2025)
    assert reason is None and p.prior_year_pieces == 40.0
