"""tests/forecasting/test_blank_quantity.py - a blank (NULL) quantity is a MISSING month: flagged,
never read as 0, skipped by every model and never scored (DEC-31, "unknown is not zero"). The
2026-10-03 model audit found 71 real Unilever product-months with a blank quantity, 69 of them
with a peso amount (a sale happened), all read as 0 pieces by fetch_demand's fillna(0.0).

Pure numpy/pandas + xgboost - no DB. Series are synthetic fixtures; a fake cursor stands in for
the read. "Missing" here is a blank quantity on a row that exists; a month with NO row is still a
zero-sale month (unchanged).
"""
from __future__ import annotations

import pathlib
import re
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

import scripts.run_baseline_forecast as rbf
from analytics.forecasting import global_model as gm, router

REPO = pathlib.Path(__file__).resolve().parents[2]


def _series(values, start="2023-01-01") -> pd.Series:
    return pd.Series(np.asarray(values, float), index=pd.date_range(start, periods=len(values), freq="MS"))


def _values(n: int, seed: int = 7) -> list[float]:
    return list(np.random.default_rng(seed).integers(80, 120, n).astype(float))


def _rows(qty, start="2025-01", absent=()) -> pd.DataFrame:
    """fetch_demand-shaped rows; None = blank quantity; months in `absent` have no row at all."""
    months = pd.period_range(start, periods=len(qty), freq="M").astype(str)
    keep = [m not in absent for m in months]
    df = pd.DataFrame({"product_key": 1, "sku_code": "A", "calendar_month": months,
                       "quantity": [np.nan if q is None else float(q) for q in qty],
                       "is_demo": False, "quantity_blank": [q is None for q in qty], "net_amount": 1000.0})
    return df[keep].reset_index(drop=True)


def _pool(n_skus=40, months=30, seed=1) -> dict:
    rng = np.random.default_rng(seed)
    return {k: _series(rng.integers(50, 500, months).astype(float)) for k in range(n_skus)}


class _FakeCursor:
    def __init__(self, rows):
        self.rows, self.sql = rows, None

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return self.rows


# ---- the read ---------------------------------------------------------------------------------------------------
def test_fetch_demand_keeps_a_blank_quantity_blank():
    cur = _FakeCursor([(1, "A", "2025-01", Decimal("10"), False, False, Decimal("100")),
                       (1, "A", "2025-02", None, False, True, Decimal("250")),
                       (1, "A", "2025-03", None, False, True, None)])
    df = rbf.fetch_demand(cur)
    assert "quantity_sold IS NULL" in cur.sql
    assert df.quantity.iloc[0] == 10.0
    assert df.quantity.iloc[1:].isna().all()                     # never 0
    assert df.quantity_blank.tolist() == [False, True, True]
    flagged = rbf.blank_quantity_rows(df)
    assert flagged.calendar_month.tolist() == ["2025-02", "2025-03"]
    assert flagged.has_peso_amount.tolist() == [True, False]


def test_runner_never_zero_fills_quantity():
    src = (REPO / "scripts/run_baseline_forecast.py").read_text(encoding="utf-8")
    assert not re.search(r'\["quantity"\][^\n]*fillna\(0', src)


# ---- the series -------------------------------------------------------------------------------------------------
def test_blank_row_is_missing_and_no_row_is_zero():
    s = rbf.build_series(_rows([10, 20, None, 40, 50, 60], absent=("2025-04",)))
    assert np.isnan(s.loc["2025-03-01"])                         # blank quantity: missing
    assert s.loc["2025-04-01"] == 0.0                            # no row: a zero-sale month, as before
    assert gm.missing_months(s) == [pd.Timestamp("2025-03-01")]
    assert int(s.isna().sum()) == 1


def test_series_without_blanks_is_unchanged():
    rows = _rows([10, 20, 30, 40, 50, 60], absent=("2025-04",))
    s = rbf.build_series(rows)
    idx = pd.to_datetime(rows.calendar_month + "-01")
    old = pd.Series(rows.quantity.to_numpy(float), index=idx).sort_index().resample("MS").asfreq().fillna(0.0)
    pd.testing.assert_series_equal(s, old, check_freq=False)
    assert gm.MISSING_ATTR not in s.attrs and gm.missing_months(s) == []


def test_missing_mark_keeps_the_placeholder_mark():
    s = gm.with_missing(gm.with_placeholder(_series(_values(6)), [pd.Timestamp("2023-01-01")]),
                        [pd.Timestamp("2023-03-01")])
    assert s.attrs[gm.PLACEHOLDER_ATTR] == frozenset({pd.Timestamp("2023-01-01")})
    assert gm.missing_months(s) == [pd.Timestamp("2023-03-01")]


# ---- the models -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("n_months, missing_pos", [(8, -2), (14, -1), (14, -3), (30, 5)])
def test_route_equals_the_series_with_the_missing_month_removed(n_months, missing_pos):
    full = _series(_values(n_months))
    month = full.index[missing_pos]
    target = full.index[-1] + pd.DateOffset(months=1)
    pool = _pool()
    with_gap = gm.with_missing(full, [month])
    a = router.route(with_gap, target, gm.GlobalForecaster({**pool, "x": with_gap}))
    b = router.route(full.drop(month), target, gm.GlobalForecaster({**pool, "x": full.drop(month)}))
    assert a["value"] == pytest.approx(b["value"]) and a["bin"] == b["bin"]
    assert a["sales_months"] == b["sales_months"] == n_months - 1     # a missing month is not a sales month
    assert a["ma3_value"] == pytest.approx(b["ma3_value"])


def test_ma3_skips_the_missing_month_instead_of_reading_zero():
    s = gm.with_missing(_series([100.0, 100.0, 100.0, 100.0]), [pd.Timestamp("2023-03-01")])
    r = router.route(s, pd.Timestamp("2023-05-01"))
    assert r["ma3_value"] == pytest.approx(100.0)                     # (100 + 100 + 100) / 3, not (100 + 0 + 100) / 3
    assert router.ma3_value(s) == pytest.approx(100.0)


def test_xgboost_never_trains_on_a_missing_month():
    pool = _pool()
    holes = {k: gm.with_missing(s, [s.index[10], s.index[20]]) for k, s in list(pool.items())[:5]}
    gappy = {**pool, **holes}
    dropped = {k: s.dropna() for k, s in gappy.items()}
    target = pd.Timestamp("2025-07-01")
    X, y = gm.training_rows(gappy, before=target)
    X2, y2 = gm.training_rows(dropped, before=target)
    assert np.isfinite(y).all()
    np.testing.assert_array_equal(y, y2)
    np.testing.assert_array_equal(np.nan_to_num(X, nan=-1), np.nan_to_num(X2, nan=-1))
    s = holes[0]
    v1 = gm.GlobalForecaster(gappy).forecast(s, target)[0]
    v2 = gm.GlobalForecaster(dropped).forecast(s.dropna(), target)[0]
    assert v1 == pytest.approx(v2)


# ---- the scores -------------------------------------------------------------------------------------------------
def test_a_missing_actual_is_never_scored():
    s = gm.with_missing(_series(_values(12)), [pd.Timestamp("2023-11-01")])
    scored = router.rolling_one_step(s, list(s.index[-3:]))
    assert pd.Timestamp("2023-11-01") not in set(scored.month)
    assert len(scored) == 2 and scored.actual.notna().all()


def test_evaluate_sku_scores_observed_months_only():
    s = gm.with_missing(_series(_values(20)), [pd.Timestamp("2024-07-01")])     # inside the 20% holdout
    ev = rbf.evaluate_sku(s)
    assert ev["holdout_len"] == 3                                               # 4 holdout months, 1 missing
    for m in rbf.METHODS:
        assert np.isfinite(ev["per_method"][m]["mae"]) and np.isfinite(ev["per_method"][m]["rmse"])


def test_holdout_with_no_observed_month_scores_nothing():
    s = gm.with_missing(_series(_values(5)), [pd.Timestamp("2023-05-01")])      # the 1-month holdout is missing
    ev = rbf.evaluate_sku(s)
    assert ev["holdout_len"] == 0 and ev["holdout_start"] is None
    for m in rbf.METHODS:
        pm = ev["per_method"][m]
        assert pm["mae"] is None and pm["mase"] is None and pm["mase_gate_passed"] is None


def test_one_step_reads_the_last_observed_month():
    s = gm.with_missing(_series([10.0, 20.0, 30.0, 40.0]), [pd.Timestamp("2023-04-01")])
    assert rbf.one_step("naive", s) == 30.0
    assert rbf.one_step("ma3", s) == pytest.approx(20.0)


# ---- the dead-product rule --------------------------------------------------------------------------------------
def test_a_missing_month_in_the_window_is_not_no_sale():
    assert rbf._missing_in_last_months([pd.Timestamp("2026-01-01")], "2026-02")
    assert not rbf._missing_in_last_months([pd.Timestamp("2025-06-01")], "2026-02")   # outside the 6-month window
    assert not rbf._missing_in_last_months([], "2026-02")
