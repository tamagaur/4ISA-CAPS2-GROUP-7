"""public.product_demand_view must carry real rows only (migration 0074; CLAUDE.md rule 2, arrangement 2).

The static tests fail if a later edit takes the filter out of the definition. The live test reads the database in a
transaction-scoped READ ONLY and fails, never skips, when the database is not configured.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg2
import pytest
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
FILTER = re.compile(r"\b[us]\.is_demo\s*=\s*false", re.IGNORECASE)


def _definition(sql: str) -> str:
    start = re.search(r"CREATE OR REPLACE VIEW\s+product_demand_view\s+AS", sql, re.IGNORECASE)
    assert start, "no definition of product_demand_view"
    return sql[start.start():sql.index(";", start.end())]


@pytest.mark.parametrize("path", ["analytics/db/migrations/0074_product_demand_view_real_rows.sql", "analytics/db/schema.sql"])
def test_definition_filters_both_branches(path):
    found = {m.group(0)[0].lower() for m in FILTER.finditer(_definition((REPO / path).read_text(encoding="utf-8")))}
    assert found == {"u", "s"}, f"{path}: both branches of the union need is_demo = false, found {sorted(found)}"


def test_no_later_migration_redefines_the_view_without_the_filter():
    for path in sorted((REPO / "analytics/db/migrations").glob("*.sql")):
        if path.name > "0074" and re.search(r"VIEW\s+(public\.)?product_demand_view", path.read_text(encoding="utf-8"), re.IGNORECASE):
            assert len(FILTER.findall(_definition(path.read_text(encoding="utf-8")))) == 2, path.name


def test_live_view_holds_only_real_rows():
    load_dotenv(REPO / ".env")
    url = os.environ.get("SUPABASE_DB_URL")
    assert url, "SUPABASE_DB_URL is not set: this check cannot run, and skipped is not passed"
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("""
            SELECT (SELECT COUNT(*) FROM product_demand_view),
                   (SELECT COUNT(*) FROM unilever_sku_demand_fact_real) + (SELECT COUNT(*) FROM sellout_fact_real)
        """)
        in_view, real = cur.fetchone()
        assert in_view == real, f"the view holds {in_view} rows, the _Real views {real}"
    finally:
        conn.rollback()
        conn.close()
