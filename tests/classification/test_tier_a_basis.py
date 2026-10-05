"""
tests/classification/test_tier_a_basis.py — the 't12m_new' Tier A basis
(analytics.classification.orchestrate_abc.classify_unilever_t12m_new,
migration 0044, DEC-37) and the setting that says which basis is Tier A
(analytics.params.TIER_A_BASIS / abc_method / abc_method_sql).

In-memory SQLite stand-ins for the _Real view and abc_classification, as in
test_orchestrate_abc.py: proves the rule, not the live data.
"""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from analytics import params
from analytics.classification.orchestrate_abc import (
    _calendar_window,
    classify_unilever_t12m_new,
    run_abc_for_principal,
)

MONTHS = [str(p) for p in pd.period_range("2025-03", "2026-02", freq="M")]


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE unilever_sku_demand_fact (product_key INTEGER, calendar_month TEXT, "
            "net_amount REAL, quantity_sold REAL, is_demo INTEGER DEFAULT 0)"))
        conn.execute(text(
            "CREATE VIEW unilever_sku_demand_fact_real AS SELECT * FROM unilever_sku_demand_fact WHERE is_demo = 0"))
        conn.execute(text(
            "CREATE TABLE abc_classification (product_key INTEGER, principal TEXT, classification_period TEXT, "
            "method TEXT DEFAULT 'single', run_id TEXT DEFAULT '', tier TEXT, revenue_share REAL, "
            "cumulative_share REAL, boundary_flag INTEGER DEFAULT 0, added_as_new INTEGER DEFAULT 0, "
            "computed_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (product_key, classification_period, method))"))
    return eng


def _sell(eng, key, months, amount, qty=1.0):
    with eng.begin() as conn:
        for m in months:
            conn.execute(text("INSERT INTO unilever_sku_demand_fact VALUES (:k, :m, :a, :q, 0)"),
                         {"k": key, "m": m, "a": amount, "q": qty})


def _base(eng):
    """12 months (total 67,200): 1-4 sell 12,000 each -> Class A is 1-4
    (cumulative 17.9 / 35.7 / 53.6 / 71.4%, then 5 at 84.8%). Last 3 months
    (total 30,300): 5 and 6 sell 9,000 each and lead, so Class A is 5, 6, 1, 2.
    5 first sold 2025-12 (new); 6 first sold 2024-06 (not new). 10-19 are
    small products."""
    for k in (1, 2, 3, 4):
        _sell(eng, k, MONTHS, 1000.0)
    for k in range(10, 20):
        _sell(eng, k, MONTHS, 10.0)
    _sell(eng, 5, MONTHS[-3:], 3000.0)
    _sell(eng, 6, ["2024-06"] + MONTHS[-3:], 3000.0)


def test_window_is_twelve_calendar_months():
    assert _calendar_window("2026-02", 12) == MONTHS
    assert _calendar_window("2026-02", 3) == ["2025-12", "2026-01", "2026-02"]


def test_new_product_class_a_on_three_months_is_added(engine):
    _base(engine)
    tiered, _ = classify_unilever_t12m_new(engine, "2026-02")
    t = tiered.set_index("sku_id")
    assert set(t.index[t["tier"] == "A"]) == {1, 2, 3, 4, 5}
    assert t.loc[1, "tier"] == "A" and not t.loc[1, "added_as_new"]
    # 5: Class A on Dec-Feb, first sold inside the 12 months -> added, keeps its 12-month share
    assert t.loc[5, "tier"] == "A" and t.loc[5, "added_as_new"]
    assert t.loc[5, "cumulative_share"] > 0.80
    # 6: Class A on Dec-Feb too, but first sold before the window -> not added
    assert t.loc[6, "tier"] != "A" and not t.loc[6, "added_as_new"]


def test_partial_window_is_not_classified(engine):
    _sell(engine, 1, MONTHS[1:], 1000.0)          # 11 months only: 2025-03 has no row at all
    tiered, _ = classify_unilever_t12m_new(engine, "2026-02")
    assert tiered.empty


def test_negative_month_counts_as_zero_and_blank_drops_the_window(engine):
    _base(engine)
    _sell(engine, 7, MONTHS, 50.0)
    _sell(engine, 7, ["2025-06"], -10_000.0)       # a return month: 0, not -10,000
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO unilever_sku_demand_fact VALUES (8, '2025-05', NULL, 1, 0)"))
    _sell(engine, 8, ["2025-06"], 5000.0)
    tiered, blank = classify_unilever_t12m_new(engine, "2026-02")
    assert tiered.set_index("sku_id").loc[7, "total_revenue"] == pytest.approx(50.0 * 12)
    assert 8 not in set(tiered["sku_id"]) and blank == 1


def test_first_sale_is_by_pieces(engine):
    """A product with pesos but no pieces before the window is still new."""
    _base(engine)
    _sell(engine, 9, ["2024-01"], 5.0, qty=0.0)
    _sell(engine, 9, MONTHS[-3:], 3000.0)
    t = classify_unilever_t12m_new(engine, "2026-02")[0].set_index("sku_id")
    assert t.loc[9, "added_as_new"]


def test_run_writes_method_and_flag(engine):
    _base(engine)
    report = run_abc_for_principal(engine, "unilever", "2026-02", method="t12m_new")
    assert report.error is None and report.added_as_new == 1
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT product_key, tier, added_as_new FROM abc_classification WHERE method = 't12m_new'")).fetchall()
    assert {r[0]: (r[1], bool(r[2])) for r in rows}[5] == ("A", True)
    assert report.rows_upserted == len(rows)


def test_t12m_new_refuses_delmonte(engine):
    with pytest.raises(ValueError, match="unilever only"):
        run_abc_for_principal(engine, "delmonte", "2026-02", method="t12m_new")


def test_setting_picks_each_principals_basis():
    assert params.abc_method("unilever") == params.TIER_A_BASIS
    assert params.abc_method("delmonte") == "single"
    assert params.abc_method_sql("ac") == (
        f"ac.method = CASE ac.principal WHEN 'unilever' THEN '{params.TIER_A_BASIS}' ELSE 'single' END")
    assert params.abc_method_sql().startswith("method = CASE principal ")
