"""The error card and the category view score one principal because the queries say so, and their coverage is read off the
scored rows (2026-11-17). Before, accuracy_rows_query filtered by month and run only, and the routes wrote coverage ["unilever"]
into the answer whatever the rows were."""
from __future__ import annotations

import inspect

from backend import marts
from backend.routers import dashboard, dashboard_range


def _row(key, principal="unilever"):
    return {"principal": principal, "product_key": key, "month": "2024-01", "forecast_source": "backtest_recreated",
            "run_label": "r", "forecast_pieces": 10.0, "actual_pieces": 8.0, "price_per_piece": 1.0, "direction": "over",
            "run_length": 1, "miss_pieces": 2.0, "possibly_stock_limited": False, "method": "ma3", "avg_monthly_pieces": 8.0,
            "closing_pieces": 5.0, "opening_pieces": 5.0, "category_path": "C", "sku_code": f"S{key}", "product_name": "P"}


def test_both_branches_of_the_rows_query_filter_the_principal_on_the_product_master():
    for run_id in (None, 7):
        sql, params = marts.accuracy_rows_query("2025-03", "2026-02", run_id)
        assert params["principal"] == marts.ACCURACY_PRINCIPAL == "unilever"
        assert "JOIN product_dimension pd ON pd.product_key = a.product_key" in sql
        assert "LEFT JOIN product_dimension" not in sql
        assert "AND pd.principal = :principal" in sql


def test_the_month_and_run_choice_reads_the_principals_rows_only():
    sql, _ = marts.accuracy_rows_query("2025-03", "2026-02")
    assert "SELECT product_key FROM product_dimension WHERE principal = :principal" in sql
    months = sql.split("months AS (", 1)[1].split("),", 1)[0]
    assert "JOIN scoped USING (product_key)" in months
    month_run = sql.split("month_run AS (", 1)[1].split("SELECT a.*", 1)[0]
    assert "JOIN scoped sb ON sb.product_key = b.product_key" in month_run
    assert "JOIN scoped ss ON ss.product_key = s.product_key" in month_run


def test_the_summary_query_inherits_the_filter_and_returns_the_rows_principals():
    sql, params = marts.accuracy_summary_query("2025-03", "2026-02")
    assert params["principal"] == "unilever" and "AND pd.principal = :principal" in sql
    assert "array_agg(DISTINCT principal) AS principals" in sql


def test_coverage_is_the_scored_rows_principals():
    assert marts.accuracy_summary([_row(1), _row(2)], "2024-01", "2024-01", 3)["coverage"] == ["unilever"]
    # a row of another principal would show in the coverage, not be hidden behind a hand-written ["unilever"]
    assert marts.accuracy_summary([_row(1), _row(2, "delmonte")], "2024-01", "2024-01", 3)["coverage"] == ["delmonte", "unilever"]
    assert marts.accuracy_summary([], "2024-01", "2024-01", 3)["coverage"] == []
    agg = marts.accuracy_aggregates_from_query([{"kind": "total", "d": {"product_months": 1, "principals": ["unilever"]}}])
    assert agg["coverage"] == ["unilever"]


def test_no_route_writes_the_cards_coverage_by_hand():
    assert '"coverage": ["unilever"]' not in inspect.getsource(dashboard_range.get_range_accuracy)
    src = inspect.getsource(dashboard.get_dashboard)
    assert 'forecast_accuracy["coverage"] =' not in src
