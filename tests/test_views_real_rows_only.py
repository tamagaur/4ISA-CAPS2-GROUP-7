"""public.product_demand_view and public.bo_monitoring_view carry real rows only (migration 0074; CLAUDE.md rule 2, arrangement 2).

The static tests fail if a later edit takes a filter out of a definition. The live tests read the database in a
transaction-scoped READ ONLY and fail, never skip, when the database is not configured.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg2
import pytest
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
MIGRATION = "analytics/db/migrations/0074_views_real_rows_only.sql"
FILTER = re.compile(r"\bis_demo\s*=\s*false", re.IGNORECASE)


def _definition(sql: str, view: str) -> str:
    start = re.search(rf"CREATE OR REPLACE VIEW\s+{view}\s+AS", sql, re.IGNORECASE)
    assert start, f"no definition of {view}"
    return sql[start.start():sql.index(";", start.end())]


@pytest.mark.parametrize("path", [MIGRATION, "analytics/db/schema.sql"])
@pytest.mark.parametrize("view", ["product_demand_view", "bo_monitoring_view"])
def test_definition_filters_both_sources(path, view):
    found = FILTER.findall(_definition((REPO / path).read_text(encoding="utf-8"), view))
    assert len(found) == 2, f"{path}: {view} reads two base tables and needs is_demo = false on both, found {len(found)}"


@pytest.mark.parametrize("view", ["product_demand_view", "bo_monitoring_view"])
def test_no_later_migration_redefines_a_view_without_the_filter(view):
    for path in sorted((REPO / "analytics/db/migrations").glob("*.sql")):
        if path.name > "0074_views_real_rows_only.sql":
            text = path.read_text(encoding="utf-8")
            if re.search(rf"VIEW\s+(public\.)?{view}", text, re.IGNORECASE):
                assert len(FILTER.findall(_definition(text, view))) == 2, path.name


@pytest.fixture
def live():
    load_dotenv(REPO / ".env")
    url = os.environ.get("SUPABASE_DB_URL")
    assert url, "SUPABASE_DB_URL is not set: this check cannot run, and skipped is not passed"
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        yield cur
    finally:
        conn.rollback()
        conn.close()


def test_live_product_demand_view_holds_only_real_rows(live):
    live.execute("""
        SELECT (SELECT COUNT(*) FROM product_demand_view),
               (SELECT COUNT(*) FROM unilever_sku_demand_fact_real) + (SELECT COUNT(*) FROM sellout_fact_real)
    """)
    in_view, real = live.fetchone()
    assert in_view == real, f"the view holds {in_view} rows, the _Real views {real}"


def test_live_bo_monitoring_view_holds_only_real_rows(live):
    live.execute("""
        WITH purchases AS (SELECT principal, region, _period, SUM(net_amount) AS total
                           FROM purchase_fact_real GROUP BY 1, 2, 3)
        SELECT (SELECT COUNT(*) FROM bo_monitoring_view),
               (SELECT COUNT(*) FROM purchases),
               (SELECT COALESCE(SUM(purchase_net_amount), 0) FROM bo_monitoring_view),
               (SELECT COALESCE(SUM(total), 0) FROM purchases),
               (SELECT COALESCE(SUM(bo_net_amount), 0) FROM bo_monitoring_view),
               (SELECT COALESCE(SUM(s.net_amount), 0) FROM salesreturn_fact_real s
                WHERE s.return_type = 'BO' AND EXISTS (
                    SELECT 1 FROM purchases p WHERE p.principal = s.principal AND p.region = s.region
                                                AND p._period = s._period))
    """)
    rows, real_rows, purchase, real_purchase, bo, real_bo = live.fetchone()
    assert (rows, purchase) == (real_rows, real_purchase), f"purchases: view {rows} rows, {purchase}; real {real_rows} rows, {real_purchase}"
    assert bo == real_bo, f"bad-order value: view {bo}, real {real_bo}"
