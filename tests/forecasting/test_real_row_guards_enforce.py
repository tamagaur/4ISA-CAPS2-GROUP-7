"""tests/forecasting/test_real_row_guards_enforce.py - the DEC-27 real-row
guards see what the runner actually reads.

assert_real_rows (router) looks for an is_demo column and assert_real_history
(global model) for the series' placeholder mark. Both were no-ops on the live
path while fetch_demand returned no is_demo column and build_series never set
the mark; these tests pin that the runner's own frame and series now carry
both, and that real-only data comes out exactly as before.

No DB: fetch_demand runs against a fake cursor.
"""
from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

import scripts.run_baseline_forecast as runner
from analytics.forecasting import global_model as gm, router

MONTHS = [str(p) for p in pd.period_range("2023-01", "2024-06", freq="M")]


class FakeCursor:
    def __init__(self, rows):
        self.rows, self.sql = rows, None

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return self.rows


def _rows(demo_months=(), skip=("2023-07",)):
    """(product_key, sku_code, calendar_month, SUM(quantity_sold), bool_or(is_demo), bool_or(quantity_sold IS NULL),
    SUM(net_amount)) as psycopg2 returns them: one SKU, a gap month (zero-filled by build_series), NUMERIC as
    Decimal, no blank quantity (blank quantities: tests/forecasting/test_blank_quantity.py)."""
    return [(101, "SKU101", m, Decimal(80 + i), m in demo_months, False, Decimal(1000 + i))
            for i, m in enumerate(MONTHS) if m not in skip]


def _old_build_series(sku_df: pd.DataFrame) -> pd.Series:
    """build_series as it was before DEC-27's mark (the reference for 'unchanged output')."""
    idx = pd.to_datetime(sku_df["calendar_month"] + "-01")
    s = pd.Series(sku_df["quantity"].to_numpy(dtype=float), index=idx).sort_index()
    return s.resample("MS").asfreq().fillna(0.0)


def _next(series: pd.Series) -> pd.Timestamp:
    return series.index[-1] + pd.DateOffset(months=1)


def test_fetch_demand_reads_the_real_view_and_returns_is_demo():
    cur = FakeCursor(_rows())
    df = runner.fetch_demand(cur)
    assert "Unilever_SKU_Demand_Fact_Real" in cur.sql and "bool_or(is_demo) AS is_demo" in cur.sql
    assert "GROUP BY product_key, sku_code, calendar_month" in cur.sql      # grain unchanged
    assert list(df.columns) == ["product_key", "sku_code", "calendar_month", "quantity", "is_demo",
                                "quantity_blank", "net_amount"]


def test_a_demo_row_from_fetch_demand_trips_assert_real_rows():
    df = runner.fetch_demand(FakeCursor(_rows(demo_months=("2023-02",))))
    with pytest.raises(ValueError, match="is_demo"):
        router.assert_real_rows(df)


def test_real_only_fetch_demand_passes_assert_real_rows():
    router.assert_real_rows(runner.fetch_demand(FakeCursor(_rows())))


def test_build_series_marks_demo_months_and_the_router_refuses_them():
    df = runner.fetch_demand(FakeCursor(_rows(demo_months=("2023-01", "2023-02"))))
    series = runner.build_series(df)
    assert series.attrs[gm.PLACEHOLDER_ATTR] == {pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01")}
    with pytest.raises(ValueError, match="placeholder"):
        gm.assert_real_history(series)
    with pytest.raises(ValueError, match="placeholder"):
        router.route(series, _next(series))
    with pytest.raises(ValueError, match="placeholder"):
        gm.GlobalForecaster({101: series}).booster_for(_next(series))


def test_the_write_paths_served_forecasts_refuses_a_demo_month():
    """_write_forecast_result's own chain: fetch_demand -> groupby -> served_forecasts -> build_series -> route."""
    demand = runner.fetch_demand(FakeCursor(_rows(demo_months=("2023-03",))))
    demand_by_key = {k: g for k, g in demand.groupby("product_key")}
    df = pd.DataFrame({"product_key": [101], "status": ["ok"]})
    with pytest.raises(ValueError, match="placeholder"):
        runner.served_forecasts(df, demand_by_key, pd.Timestamp("2024-07-01"))


def test_real_only_series_is_identical_to_the_old_build_series():
    df = runner.fetch_demand(FakeCursor(_rows()))
    new, old = runner.build_series(df), _old_build_series(df)
    pd.testing.assert_series_equal(new, old)
    assert new.attrs == {} and len(new) == len(MONTHS) and new[pd.Timestamp("2023-07-01")] == 0.0
    # a frame without the column (any other caller) is handled the same way
    pd.testing.assert_series_equal(runner.build_series(df.drop(columns="is_demo")), old)
    gm.assert_real_history(new)
    assert router.route(new, _next(new))["value"] is not None
