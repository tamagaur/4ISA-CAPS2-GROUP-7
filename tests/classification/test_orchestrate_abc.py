"""
tests/classification/test_orchestrate_abc.py — Tests for
analytics.classification.orchestrate_abc, the ABC orchestration script.

Uses an in-memory SQLite engine with a minimal schema standing in for
the real Unilever_SKU_Demand_Fact / SellOut_Fact / ABC_Classification
tables — this is NOT a substitute for running against real Supabase
data (see AGAINST_REAL_DATA note in RUNNING.md), it only proves the
Python-level fetch/aggregate/exclude/upsert logic is correct.

  test_null_revenue_excluded_not_zeroed
  test_delmonte_sums_across_regions_to_one_row_per_category
  test_negative_revenue_split_out_not_coerced
  test_full_run_upserts_and_is_idempotent
"""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from analytics.classification.orchestrate_abc import (
    _fetch_delmonte_category_revenue,
    _fetch_unilever_sku_revenue,
    _split_negative_revenue,
    run_abc_for_principal,
)


@pytest.fixture
def sqlite_engine():
    """product_dimension backs the zero-fill universe join in the fetch
    functions; the two base tables carry is_demo so the _real views
    (fetch functions now read *_real, not the base tables directly —
    2026-09-17, Hard Rule 1 fix) have something to filter."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE unilever_sku_demand_fact "
            "(product_key INTEGER, sku_code TEXT, calendar_month TEXT, net_amount REAL, is_demo INTEGER DEFAULT 0)"
        ))
        conn.execute(text(
            "CREATE VIEW unilever_sku_demand_fact_real AS "
            "SELECT * FROM unilever_sku_demand_fact WHERE is_demo = 0"
        ))
        conn.execute(text(
            "CREATE TABLE sellout_fact "
            "(product_key INTEGER, category_path TEXT, region TEXT, _period TEXT, net_amount REAL, is_demo INTEGER DEFAULT 0)"
        ))
        conn.execute(text(
            "CREATE VIEW sellout_fact_real AS "
            "SELECT * FROM sellout_fact WHERE is_demo = 0"
        ))
        conn.execute(text(
            "CREATE TABLE product_dimension (product_key INTEGER PRIMARY KEY, principal TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE abc_classification ("
            "product_key INTEGER, principal TEXT, classification_period TEXT, "
            "method TEXT DEFAULT 'single', run_id TEXT DEFAULT '', "
            "tier TEXT, revenue_share REAL, cumulative_share REAL, "
            "boundary_flag INTEGER DEFAULT 0, "
            "computed_at TEXT DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY (product_key, classification_period, method))"
        ))
    return engine


def test_null_revenue_excluded_not_zeroed(sqlite_engine):
    with sqlite_engine.begin() as conn:
        conn.execute(text("INSERT INTO unilever_sku_demand_fact VALUES (1,'SKU-A','2024-02',80000,0)"))
        conn.execute(text("INSERT INTO unilever_sku_demand_fact VALUES (2,'SKU-B','2024-02',NULL,0)"))
        conn.execute(text("INSERT INTO product_dimension VALUES (1,'unilever')"))
        conn.execute(text("INSERT INTO product_dimension VALUES (2,'unilever')"))
    df, null_count = _fetch_unilever_sku_revenue(sqlite_engine, "2024-02")
    assert len(df) == 1
    assert null_count == 1
    assert 2 not in df["sku_id"].tolist()


def test_delmonte_sums_across_regions_to_one_row_per_category(sqlite_engine):
    """Product_Dimension has no region column for grain='category' rows,
    so two regions sharing a category_path resolve to the same
    product_key — classify_abc() requires exactly one row per sku_id,
    so these must be summed here, not passed through per-region."""
    with sqlite_engine.begin() as conn:
        conn.execute(text("INSERT INTO sellout_fact VALUES (10,'/ACE/BASE','pangasinan','2024-02',40000,0)"))
        conn.execute(text("INSERT INTO sellout_fact VALUES (10,'/ACE/BASE','ilocos','2024-02',20000,0)"))
        conn.execute(text("INSERT INTO product_dimension VALUES (10,'delmonte')"))
    df, _ = _fetch_delmonte_category_revenue(sqlite_engine, "2024-02")
    assert len(df) == 1
    assert df.loc[df["sku_id"] == 10, "total_revenue"].iloc[0] == 60000


def test_negative_revenue_split_out_not_coerced():
    """Pre-existing stale assertion fixed 2026-09-17: the function clamps
    negative rows to 0.0 (see its own docstring), it does not drop them —
    the clamped-to-zero row then flows into _split_zero_revenue()'s
    'inactive' exclusion downstream, same as a genuine zero-sale row."""
    df = pd.DataFrame({"sku_id": [1, 2, 3], "total_revenue": [500.0, -20.0, 300.0]})
    clean, negative_ids = _split_negative_revenue(df)
    assert negative_ids == [2]
    assert len(clean) == 3
    assert (clean["total_revenue"] >= 0).all()
    assert clean.loc[clean["sku_id"] == 2, "total_revenue"].iloc[0] == 0.0


def test_full_run_upserts_and_is_idempotent(sqlite_engine):
    with sqlite_engine.begin() as conn:
        conn.execute(text("INSERT INTO unilever_sku_demand_fact VALUES (1,'SKU-A','2024-02',80000,0)"))
        conn.execute(text("INSERT INTO unilever_sku_demand_fact VALUES (2,'SKU-B','2024-02',15000,0)"))
        conn.execute(text("INSERT INTO product_dimension VALUES (1,'unilever')"))
        conn.execute(text("INSERT INTO product_dimension VALUES (2,'unilever')"))

    report = run_abc_for_principal(sqlite_engine, "unilever", "2024-02")
    assert report.rows_upserted == 2
    assert report.tier_counts.get("B") == 1
    assert report.tier_counts.get("C") == 1

    # Re-running the same period must UPDATE existing rows, not duplicate them.
    run_abc_for_principal(sqlite_engine, "unilever", "2024-02")
    with sqlite_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM abc_classification")).scalar()
    assert count == 2
