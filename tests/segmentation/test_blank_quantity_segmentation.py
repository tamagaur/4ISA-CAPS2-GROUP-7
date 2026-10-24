"""tests/segmentation/test_blank_quantity_segmentation.py - a blank (NULL) quantity is a MISSING month in both
segmentation paths: flagged, never read as 0, skipped by every trait (DEC-31, "unknown is not zero"). The
2026-10-03 model audit found 71 real Unilever product-months with a blank quantity, 69 of them with a peso
amount; orchestrate_segment._fetch_demand_matrix and backend data_mode.demand_matrix both read them as 0.

A month with NO row is still a zero-sale month (unchanged). No DB: fake rows and patched fetchers.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy import stats

import analytics.segmentation.orchestrate_segment as seg
from analytics.segmentation.traits import (
    average_demand_interval, coefficient_of_variation, first_sale_index, has_restart, history_months,
    longest_positive_run, missing_month_indices, trend_stats,
)
from backend import data_mode

REPO = Path(__file__).resolve().parents[2]
NAN = np.nan
PERIODS = ["2025-01", "2025-02", "2025-03", "2025-04"]


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Db:
    def execute(self, stmt, params=None):
        return _Rows([{"product_key": 1, "period": "2025-01", "qty": 10.0},
                      {"product_key": 1, "period": "2025-02", "qty": None},
                      {"product_key": 1, "period": "2025-04", "qty": -3.0}])


# ---- the matrices -------------------------------------------------------------------------------------------------
def test_batch_matrix_blank_is_missing_no_row_is_zero():
    m = seg._matrix_from_rows([(1, "2025-01", 10.0), (1, "2025-02", None), (1, "2025-04", -3.0)], [1], PERIODS)
    assert np.isnan(m[1][1])                          # blank quantity: missing
    assert m[1][2] == 0.0                             # no row: a zero-sale month, as before
    assert m[1][0] == 10.0 and m[1][3] == -3.0        # negative kept (DEC-15)


def test_preview_matrix_matches_the_batch_matrix():
    matrices, periods = data_mode.demand_matrix(_Db(), [1], "2025-01", "2025-04", data_mode.REAL)
    batch = seg._matrix_from_rows([(1, "2025-01", 10.0), (1, "2025-02", None), (1, "2025-04", -3.0)], [1], PERIODS)
    assert periods == PERIODS
    np.testing.assert_array_equal(matrices[1], batch[1])     # NaN == NaN here


def test_neither_path_zero_fills_a_blank():
    batch = (REPO / "analytics/segmentation/orchestrate_segment.py").read_text(encoding="utf-8")
    preview = (REPO / "backend/data_mode.py").read_text(encoding="utf-8")
    assert "if not pd.isna(row.qty) else 0.0" not in batch
    assert '0.0 if r["qty"] is None' not in preview


# ---- the traits: a missing month is skipped, never read as 0 ------------------------------------------------------
def test_missing_month_is_not_a_sales_month_and_not_a_zero_month():
    assert history_months(np.array([5.0, NAN, 5.0])) == 2
    assert average_demand_interval(np.array([10.0, NAN, 12.0])) == 1.0          # read as 0 it would be 1.5
    assert average_demand_interval(np.array([10.0, 0.0, 12.0])) == 1.5


def test_cv_reads_observed_months_only():
    got = coefficient_of_variation(np.array([10.0, NAN, 12.0, 11.0]))
    assert got == pytest.approx(coefficient_of_variation(np.array([10.0, 12.0, 11.0])))
    assert got != pytest.approx(coefficient_of_variation(np.array([10.0, 0.0, 12.0, 11.0])))


def test_runs_and_restarts_are_not_made_by_a_missing_month():
    assert longest_positive_run(np.array([5.0, NAN, 5.0])) == 2                 # read as 0 it would be 1
    assert has_restart(np.array([5.0, 0.0, NAN, 0.0, 5.0])) is False            # read as 0: a 3-month gap
    assert has_restart(np.array([5.0, 0.0, 0.0, 0.0, 5.0])) is True


def test_first_sale_period_is_not_shifted():
    assert first_sale_index(np.array([NAN, 0.0, 7.0, 8.0])) == 2


def test_trend_skips_the_missing_month_and_keeps_true_month_positions():
    qty = np.array([10.0, 12.0, NAN, 16.0, 18.0, 20.0, 22.0, 24.0])
    label, p, slope = trend_stats(qty)
    keep = ~np.isnan(qty)
    assert label == "up" and np.isfinite(p)
    assert slope == pytest.approx(stats.theilslopes(qty[keep], np.arange(len(qty))[keep])[0])
    assert slope == pytest.approx(2.0)                                           # units per calendar month


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_series_without_blanks_give_the_old_values(seed):
    qty = np.random.default_rng(seed).integers(0, 50, 30).astype(float)
    fs = first_sale_index(qty)
    s = qty[fs:]
    assert trend_stats(qty)[2] == pytest.approx(float(stats.theilslopes(s, np.arange(len(s)))[0]))
    assert coefficient_of_variation(qty) == pytest.approx(float(s.std(ddof=1) / s.mean()))
    assert missing_month_indices(qty) == []


# ---- the flag ------------------------------------------------------------------------------------------------------
def test_build_traits_flags_the_missing_month_and_writes_no_nan(monkeypatch):
    matrices = {1: np.array([10.0, NAN, 12.0, 11.0]), 2: np.array([5.0, 6.0, 7.0, 8.0])}
    monkeypatch.setattr(seg, "_fetch_cohort", lambda *a: [1, 2])
    monkeypatch.setattr(seg, "_fetch_demand_matrix", lambda *a: (matrices, PERIODS))
    monkeypatch.setattr(seg, "_fetch_observed_periods", lambda *a: set(PERIODS))
    monkeypatch.setattr(seg, "_fetch_stability_and_revenue", lambda *a: ({1: 38, 2: 38}, {1: 0.1, 2: 0.2}))
    monkeypatch.setattr(seg, "_fetch_total_periods", lambda *a: 38)
    traits, report = seg.build_traits(None, "unilever", "2025-04", "single", "2025-01", "2025-04", "test-run")
    assert report.missing_quantity == {1: ["2025-02"]}
    row = traits.set_index("product_key").loc[1]
    assert row.history_months == 3 and row.longest_run == 3 and row.adi == 1.0
    assert row.cv == pytest.approx(coefficient_of_variation(np.array([10.0, 12.0, 11.0])))
    assert not traits[["history_months", "longest_run", "cv", "adi"]].isna().any().any()
    assert "missing_quantity_periods" not in seg.TRAIT_TABLE_COLUMNS            # flag only, no new DB column


def test_preview_traits_flag_it_and_match_the_batch_run(monkeypatch):
    qty = np.array([10.0, NAN, 12.0, 11.0])
    monkeypatch.setattr(seg, "_fetch_cohort", lambda *a: [1])
    monkeypatch.setattr(seg, "_fetch_demand_matrix", lambda *a: ({1: qty}, PERIODS))
    monkeypatch.setattr(seg, "_fetch_observed_periods", lambda *a: set(PERIODS))
    monkeypatch.setattr(seg, "_fetch_stability_and_revenue", lambda *a: ({1: 38}, {1: 0.1}))
    monkeypatch.setattr(seg, "_fetch_total_periods", lambda *a: 38)
    batch = seg.build_traits(None, "unilever", "2025-04", "single", "2025-01", "2025-04", "t")[0].iloc[0]
    preview = data_mode.series_traits(qty, PERIODS, set(PERIODS))
    assert preview["missing_quantity_periods"] == ["2025-02"]
    for col in ("history_months", "first_sale_period", "longest_run", "trend", "restart_flag"):
        assert preview[col] == batch[col], col
    for col in ("cv", "adi"):
        assert preview[col] == pytest.approx(batch[col]), col
