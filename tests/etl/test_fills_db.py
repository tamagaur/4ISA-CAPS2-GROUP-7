"""DEC-31 fill step guardrails against a rehearsal schema (a filled copy of public: scripts/rehearse_fills.py --build,
then scripts/fill_missing.py). Skipped unless FILLS_SCRATCH_SCHEMA names that schema. Every test runs in one
transaction that is rolled back - the rehearsal schema is left as it was. Never pointed at public.

  FILLS_SCRATCH_SCHEMA=ssm_fills pytest tests/etl/test_fills_db.py
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

SCHEMA = os.environ.get("FILLS_SCRATCH_SCHEMA")
pytestmark = pytest.mark.skipif(not SCHEMA or SCHEMA == "public", reason="needs FILLS_SCRATCH_SCHEMA (a filled rehearsal schema)")


@pytest.fixture(scope="module")
def engine():
    from analytics.config import get_settings
    return create_engine(get_settings().supabase_db_url)


@pytest.fixture
def conn(engine):
    from scripts import load_slices as ls
    with engine.connect() as c:
        tx = c.begin()
        ls._scope(c, SCHEMA)
        c.execute(text("SET LOCAL statement_timeout = '10min'"))
        try:
            yield c
        finally:
            tx.rollback()


def _fill(conn):
    from scripts import fill_missing as fm
    now = datetime.now(timezone.utc)
    return fm.fill(conn, SCHEMA, f"test-{now:%H%M%S}", "pytest", "2026-09", now, "pytest")


def _n(conn, sql, **p):
    return conn.execute(text(sql), p).scalar()


def test_a_second_run_changes_nothing(conn):
    events = _n(conn, "SELECT count(*) FROM etl_load_event")
    out = _fill(conn)
    assert out["cells_changed"] == 0 and out["swept"] == 0 and out["4_gaps"] == {}
    assert out["ledger"] == {"events": 0, "coverage_rows_written": 0}
    for k in ("1_derived_receipts", "2_unilever_returns", "3_delmonte_split"):
        assert (out[k]["added"], out[k]["removed"]) == (0, 0)
    assert _n(conn, "SELECT count(*) FROM etl_load_event") == events


def test_real_rows_replace_the_fill_and_the_cell_is_never_refilled(conn):
    from scripts import load_slices as ls
    fam = next(f for f in ls.FAMILIES if f.key == "sales_return")
    m = "2024-05"
    filled = _n(conn, "SELECT count(*) FROM salesreturn_fact WHERE principal = 'delmonte' AND _period = :m AND fill_source = 'synthetic_v2_gap'", m=m)
    assert filled > 0
    derived = _n(conn, "SELECT count(*) FROM derived_receipt_fact WHERE _period = :m", m=m)
    assert derived > 0
    # what load_slices.write_slice does in the loading transaction when real rows for the month arrive
    conn.execute(text("""INSERT INTO salesreturn_fact (return_slip_num, invoice_num, principal, region, net_amount, is_demo,
                         _src_file, _src_sheet, _period) VALUES ('T-RS', 'T-INV', 'delmonte', 'ilocos', 1, false, 'test.xlsx', 'S', :m)"""), {"m": m})
    removed = conn.execute(text(f"DELETE FROM salesreturn_fact WHERE {ls.synthetic_where(fam)}"), {"m": m}).rowcount
    assert removed == filled
    conn.execute(text("""INSERT INTO purchase_fact (invoice_num, principal, region, net_amount, is_demo, _src_file, _src_sheet, _period)
                         VALUES ('T-BILL', 'unilever', NULL, 1, false, 'test.xlsx', 'S', :m)"""), {"m": m})
    assert ls.remove_derived(conn, "unilever", "purchase_fact", m) == derived
    out = _fill(conn)
    assert _n(conn, "SELECT count(*) FROM salesreturn_fact WHERE principal = 'delmonte' AND _period = :m AND is_demo", m=m) == 0
    assert _n(conn, "SELECT count(*) FROM derived_receipt_fact WHERE _period = :m", m=m) == 0
    assert ("delmonte", "salesreturn_fact", m) not in out and out["4_gaps"] == {}
    assert _n(conn, "SELECT status FROM etl_coverage WHERE principal = 'delmonte' AND table_name = 'salesreturn_fact' "
                    "AND month = :m", m=m) == "partial"            # one real branch of two
    assert _n(conn, "SELECT status FROM etl_coverage WHERE principal = 'unilever' AND table_name = 'purchase_fact' "
                    "AND month = :m", m=m) == "real"


def test_the_sweep_removes_fills_the_loader_missed(conn):
    """A real row arriving outside the loader's per-workbook-month delete (e.g. a sales row with another invoice month)."""
    m = "2024-07"
    filled = _n(conn, "SELECT count(*) FROM salesreturn_fact WHERE principal = 'delmonte' AND _period = :m AND is_demo", m=m)
    assert filled > 0
    conn.execute(text("""INSERT INTO salesreturn_fact (return_slip_num, invoice_num, principal, region, net_amount, is_demo,
                         _src_file, _src_sheet, _period) VALUES ('T-RS', 'T-INV', 'delmonte', 'ilocos', 1, false, 'test.xlsx', 'S', :m)"""), {"m": m})
    out = _fill(conn)
    assert out["swept"] == filled
    assert _n(conn, "SELECT count(*) FROM salesreturn_fact WHERE principal = 'delmonte' AND _period = :m AND is_demo", m=m) == 0
    ev = conn.execute(text("SELECT synthetic_rows_removed, fill_rows_added FROM etl_load_event WHERE source = 'fill_missing' "
                           "AND principal = 'delmonte' AND table_name = 'salesreturn_fact' AND month = :m "
                           "ORDER BY load_event_key DESC LIMIT 1"), {"m": m}).one()
    assert tuple(ev) == (filled, 0)


def test_a_cell_that_once_held_real_rows_stays_empty(conn):
    m = "2024-06"
    conn.execute(text("DELETE FROM salesreturn_fact WHERE principal = 'delmonte' AND _period = :m"), {"m": m})
    conn.execute(text("""INSERT INTO etl_load_event (run_id, slice, principal, table_name, month, source, status, real_rows_after,
                         run_by, started_at) VALUES ('t', :slice, 'delmonte', 'salesreturn_fact', :m, 'sales_return', 'loaded',
                         5, 'pytest', now())"""), {"m": m, "slice": f"delmonte:salesreturn_fact:{m}:*:sales_return"})
    _fill(conn)
    assert _n(conn, "SELECT count(*) FROM salesreturn_fact WHERE principal = 'delmonte' AND _period = :m", m=m) == 0


def test_a_new_stock_and_sales_month_produces_new_derived_receipts(conn):
    """2026-03 has real stock (both snapshots) but only placeholder sales; real sales for it arrive."""
    assert _n(conn, "SELECT count(*) FROM derived_receipt_fact WHERE _period = '2026-03'") == 0
    conn.execute(text("DELETE FROM unilever_sku_demand_fact WHERE calendar_month = '2026-03'"))
    conn.execute(text("""INSERT INTO unilever_sku_demand_fact (product_key, sku_code, calendar_month, region, quantity_sold, net_amount,
                             _src_file, _src_sheet, is_demo, gsv)
                         SELECT product_key, sku_code, '2026-03', region, quantity_sold, net_amount, 'test.xls', 'S', false, gsv
                         FROM unilever_sku_demand_fact WHERE calendar_month = '2026-02' AND NOT is_demo"""))
    out = _fill(conn)
    n = _n(conn, "SELECT count(*) FROM derived_receipt_fact WHERE _period = '2026-03'")
    assert n > 0 and out["1_derived_receipts"]["added"] == n
    assert _n(conn, "SELECT status FROM etl_coverage WHERE principal = 'unilever' AND table_name = 'purchase_fact' AND month = '2026-03'") == "derived"
    bad = _n(conn, "SELECT count(*) FROM derived_receipt_fact WHERE _period = '2026-03' AND (receipt_pieces <> GREATEST(balance_pieces, 0) "
                   "OR balance_pieces <> closing_pieces - opening_pieces + sold_pieces)")
    assert bad == 0


def test_del_monte_split_totals_equal_real_sell_out_totals(conn):
    off = conn.execute(text("""
        SELECT count(*) FROM (SELECT _period, SUM(net_amount) a, SUM(quantity) q FROM sellout_fact_real WHERE principal = 'delmonte'
                              GROUP BY 1) t
        JOIN (SELECT _period, SUM(net_amount) a, SUM(quantity) q FROM sku_demand_fill GROUP BY 1) s USING (_period)
        WHERE (t.a, t.q) IS DISTINCT FROM (s.a, s.q)""")).scalar()
    months = _n(conn, "SELECT count(DISTINCT _period) FROM sku_demand_fill")
    real_months = _n(conn, "SELECT count(DISTINCT _period) FROM sellout_fact_real WHERE principal = 'delmonte' AND _period <= '2026-09'")
    assert off == 0 and months == real_months == 17
    assert _n(conn, "SELECT count(*) FROM sku_demand_fill WHERE NOT is_demo OR split_level <> 'principal'") == 0
    shares = conn.execute(text("SELECT _period, SUM(stock_share) FROM sku_demand_fill GROUP BY 1")).all()
    assert all(abs(float(s) - 1) < 1e-9 for _, s in shares)


def test_real_views_hold_only_real_rows_and_pass_the_forecast_guard(conn):
    from analytics.forecasting.router import assert_real_rows
    for v in ("sales_fact_real", "purchase_fact_real", "salesreturn_fact_real", "sellout_fact_real", "inventory_fact_real",
              "unilever_sku_demand_fact_real"):
        df = pd.DataFrame(conn.execute(text(f"SELECT is_demo FROM {v}")).all(), columns=["is_demo"])
        assert len(df) > 0
        assert_real_rows(df)                                    # raises on any is_demo row
    for t in ("derived_receipt_fact", "sku_demand_fill"):        # fills never reach a _Real view: they are not in one
        assert _n(conn, "SELECT count(*) FROM information_schema.view_table_usage WHERE view_schema = :s AND table_name = :t",
                  s=SCHEMA, t=t) == 0


def test_the_estimated_received_series_reads_only_the_derived_table(conn):
    from backend.routers.dashboard import _estimated_received_by_period, _received_by_period
    from sqlalchemy.orm import Session
    db = Session(bind=conn)
    periods = ["2023-01", "2023-02", "2026-02", "2026-03"]
    est = _estimated_received_by_period(db, periods, "unilever")
    assert est["2023-01"]["value"] is None and est["2026-03"]["value"] is None       # no real opening stock / no real sales
    assert est["2023-02"]["value"] > 0 and est["2026-02"]["negative_skus"] >= 0
    assert _received_by_period(db, periods, "unilever") == {p: None for p in periods}  # real purchases stay real-only
    assert all(v["value"] is None for v in _estimated_received_by_period(db, periods, "delmonte").values())


def test_a_reviewed_category_map_switches_the_split_to_category_level(conn):
    """Option (a) without rework: a SKU -> category map plus a sell-out category roll-up (here a toy two-group map,
    passed in place of the reviewed CSVs) makes every month category level, totals exact per category and month."""
    from scripts import fill_missing as fm
    skus = [s for (s,) in conn.execute(text("SELECT DISTINCT sku_code FROM inventory_fact_real WHERE principal = 'delmonte' "
                                            "ORDER BY 1")).all()]
    paths = [c for (c,) in conn.execute(text("SELECT DISTINCT category_path FROM sellout_fact_real WHERE principal = 'delmonte' "
                                             "ORDER BY 1")).all()]
    sku_map = {s: ("G1", "G2")[i % 2] for i, s in enumerate(skus)}
    rollup = {c: ("G1", "G2")[i % 2] for i, c in enumerate(paths)}
    out = fm.split_delmonte_sales(conn, "test-cat", "2021-01", "2026-09", fm.Changes(), sku_map=sku_map, rollup=rollup)
    assert out["levels"] == {"principal": 0, "category": 17}
    assert _n(conn, "SELECT count(*) FROM sku_demand_fill WHERE split_level <> 'category' OR category_path IS NULL") == 0
    off = conn.execute(text("""
        SELECT count(*) FROM (
            SELECT f._period, r.g, SUM(f.net_amount) a, SUM(f.quantity) q FROM sellout_fact_real f
            JOIN unnest(CAST(:rp AS text[]), CAST(:rg AS text[])) AS r(p, g) ON r.p = f.category_path
            WHERE f.principal = 'delmonte' GROUP BY 1, 2) t
        FULL JOIN (SELECT _period, category_path AS g, SUM(net_amount) a, SUM(quantity) q FROM sku_demand_fill GROUP BY 1, 2) s
          USING (_period, g)
        WHERE (t.a, t.q) IS DISTINCT FROM (s.a, s.q)"""), {"rp": list(rollup), "rg": list(rollup.values())}).scalar()
    assert off == 0
    assert all(sku_map[s] == c for s, c in conn.execute(text("SELECT sku_code, category_path FROM sku_demand_fill")).all())
