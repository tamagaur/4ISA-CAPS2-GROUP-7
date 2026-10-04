"""
tests/test_marts.py — the data marts (migration 0041, analytics/marts.py).

Static checks (no database): the migration writes only inside the `mart` schema, and
mart.refresh()'s defaults are analytics.params' values. Helper checks: a scratch target
skips the refresh, a failed refresh is reported, not raised.

Live checks (read only, skipped without SUPABASE_DB_URL or without the marts): every mart
total equals its source (scripts/rehearse_marts.py's checks); one month's range ranking
reproduces every stored ABC 'single' run; the accuracy mart's actuals are real sales.
MART_TEST_SCHEMA=ssm_mart_rehearsal runs them against a kept rehearsal build instead.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from dotenv import load_dotenv

from analytics import marts
from analytics.params import DEAD_SKU_MONTHS, POSSIBLY_PARTIAL_COUNTS

load_dotenv()
REPO = Path(__file__).resolve().parents[1]
MIGRATION = REPO / "analytics" / "db" / "migrations" / "0041_data_marts.sql"
SCHEMA = os.environ.get("MART_TEST_SCHEMA", "mart")


def _sql() -> str:
    from scripts.run_canonical_load import _strip_sql_file
    return _strip_sql_file(MIGRATION.read_text(encoding="utf-8"))


# ---- static ------------------------------------------------------------------

def test_migration_creates_and_writes_only_inside_the_mart_schema():
    sql = _sql()
    created = re.findall(r"CREATE (?:OR REPLACE )?(?:UNIQUE )?(?:TABLE|VIEW|FUNCTION|INDEX)\s+(?:\w+\s+ON\s+)?([\w.]+)", sql)
    assert created and all(name.startswith("mart.") for name in created if "." in name), created
    for name in created:
        if "." not in name:  # an index's own name; its table follows ON
            assert re.search(rf"INDEX {name} ON mart\.", sql), name
    written = re.findall(r"(?:INSERT INTO|DELETE FROM|UPDATE|TRUNCATE|ALTER TABLE|DROP \w+)\s+([\w.]+)", sql)
    assert written and all(t.startswith("mart.") for t in written), written


def test_refresh_defaults_are_the_params_values():
    sql = _sql()
    assert f"p_idle_months integer DEFAULT {DEAD_SKU_MONTHS}" in sql
    assert "p_partial_counts text[] DEFAULT ARRAY[" + ", ".join(f"'{p}'" for p in POSSIBLY_PARTIAL_COUNTS) + "]" in sql
    assert marts.refresh_params("x") == {"trigger": "x", "idle_months": DEAD_SKU_MONTHS,
                                         "partial": list(POSSIBLY_PARTIAL_COUNTS)}


def test_real_kind_is_exactly_is_demo_false():
    """data_kind = 'real' must be the _Real views' own rule (is_demo = false), so a
    *_real mart read can never include a row the views exclude."""
    body = re.search(r"FUNCTION mart\.data_kind.*?\$\$(.*?)\$\$", _sql(), re.S).group(1)
    assert "WHEN p_is_demo IS NOT TRUE THEN 'real'" in body
    assert "p_fill_source = 'synthetic_v2' THEN 'generated'" in body and "ELSE 'filled'" in body


class _NoQueries:
    def execute(self, *a, **k):
        raise AssertionError("a skipped refresh must not touch the database")


def test_refresh_is_skipped_for_a_scratch_target():
    assert marts.refresh_marts_cursor(_NoQueries(), "load", schema="ssm_scratch") is None


def test_only_mart_or_scratch_schemas_are_accepted():
    with pytest.raises(ValueError):
        marts.refresh_marts_cursor(_NoQueries(), "x", mart_schema="public")


def test_a_failed_refresh_is_reported_not_raised(capsys):
    assert marts.refresh_marts("postgresql://nobody@127.0.0.1:1/none", "run_lp") is None
    assert "REFRESH FAILED" in capsys.readouterr().out


# ---- live, read only ---------------------------------------------------------

live = pytest.mark.skipif(not os.environ.get("SUPABASE_DB_URL"), reason="live DB not configured (SUPABASE_DB_URL unset)")


@pytest.fixture(scope="module")
def cur():
    psycopg2 = pytest.importorskip("psycopg2")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    c = conn.cursor()
    c.execute("SET TRANSACTION READ ONLY")  # transaction-scoped, never session-level (pooler leak)
    c.execute("SELECT to_regnamespace(%s) IS NOT NULL", (SCHEMA,))
    if not c.fetchone()[0]:
        conn.rollback()
        conn.close()
        pytest.skip(f"schema {SCHEMA} not present (migration 0041 not applied)")
    yield c
    conn.rollback()
    conn.close()


@live
def test_every_mart_total_equals_its_source(cur):
    from scripts.rehearse_marts import check
    assert check(cur, SCHEMA)


@live
def test_one_month_range_ranking_reproduces_every_stored_abc_run(cur):
    from backend.marts import PARETO_SQL
    sql = PARETO_SQL.format(kind="s.data_kind = 'real'").replace("mart.", f"{SCHEMA}.")
    for token in ("principal", "start", "end", "a", "b"):
        sql = sql.replace(f":{token}", f"%({token})s")
    cur.execute("SELECT DISTINCT principal, classification_period FROM abc_classification WHERE method = 'single'")
    runs = cur.fetchall()
    assert runs
    for principal, period in runs:
        cur.execute(sql, {"principal": principal, "start": period, "end": period, "a": 0.8, "b": 0.95})
        mine = {r[1]: r[11] for r in cur.fetchall()}
        cur.execute("SELECT product_key, tier FROM abc_classification WHERE method = 'single' "
                    "AND principal = %s AND classification_period = %s", (principal, period))
        assert mine == dict(cur.fetchall()), (principal, period)


@live
def test_accuracy_actuals_are_real_sales(cur):
    cur.execute(f"""
        SELECT COUNT(*) FROM {SCHEMA}.accuracy_mart a
        JOIN {SCHEMA}.sales_mart s ON s.level = 'product' AND s.product_key = a.product_key
             AND s.period = a.month AND s.source_tag = 'real'
        WHERE a.actual_pieces IS DISTINCT FROM CASE WHEN s.pieces_null_rows > 0 THEN NULL ELSE s.pieces END
    """)
    assert cur.fetchone()[0] == 0
    cur.execute(f"SELECT DISTINCT forecast_source FROM {SCHEMA}.accuracy_mart")
    assert {r[0] for r in cur.fetchall()} <= {"stored_run", "backtest_recreated"}
