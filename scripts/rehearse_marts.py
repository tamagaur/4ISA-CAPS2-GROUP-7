"""
scripts/rehearse_marts.py — build migration 0041's marts in a scratch schema and check
every total against its source, before 0041 goes to public.

    python -m scripts.rehearse_marts                 # build ssm_mart_rehearsal, check, drop it
    python -m scripts.rehearse_marts --keep          # leave the scratch schema for inspection
    python -m scripts.rehearse_marts --check-only --schema mart   # re-run the checks on live

The scratch build runs the COMMITTED file: comment/BEGIN/COMMIT lines stripped exactly as
the migration runner strips them, and the schema name `mart` swapped for the scratch name
(the one token the file uses for its own objects). Sources are read from public, read
only; the only writes land in the scratch schema, which is dropped at the end (CLAUDE.md
rule 16) unless --keep.

Every check is an exact comparison run on the server (EXCEPT both ways or equal sums), so
"0 differences" means the marts carry every source row's pieces, pesos and row count,
split by data kind, with nothing added. Exit 1 if any check fails.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import psycopg2

from analytics.marts import refresh_params

REPO = Path(__file__).resolve().parents[1]
MIGRATION = REPO / "analytics" / "db" / "migrations" / "0041_data_marts.sql"
SCRATCH = "ssm_mart_rehearsal"
SIZE_LIMIT_MB = 60  # the pre-approved ceiling for applying 0041 live (2026-10-04 prompt)

# (name, source query, mart query): each pair must return identical row sets.
# Grouped by principal x month x source tag, carrying sums AND row counts.
CHECKS = [
    ("sales: unilever_sku_demand_fact",
     """SELECT calendar_month, {schema}.source_tag(is_demo, fill_source), SUM(quantity_sold), SUM(net_amount), SUM(gsv), COUNT(*)
        FROM public.unilever_sku_demand_fact GROUP BY 1, 2""",
     """SELECT period, source_tag, SUM(pieces), SUM(pesos), SUM(gsv), SUM(source_rows)
        FROM {schema}.sales_mart WHERE principal = 'unilever' AND level = 'product' GROUP BY 1, 2"""),
    ("sales: sellout_fact (Del Monte category)",
     """SELECT _period, {schema}.source_tag(is_demo, fill_source), SUM(quantity), SUM(net_amount), COUNT(*)
        FROM public.sellout_fact GROUP BY 1, 2""",
     """SELECT period, source_tag, SUM(pieces), SUM(pesos), SUM(source_rows)
        FROM {schema}.sales_mart WHERE principal = 'delmonte' AND level = 'category' GROUP BY 1, 2"""),
    ("sales: sku_demand_fill (Del Monte product split)",
     """SELECT _period, {schema}.source_tag(is_demo, fill_source), SUM(quantity), SUM(net_amount), COUNT(*)
        FROM public.sku_demand_fill GROUP BY 1, 2""",
     """SELECT period, source_tag, SUM(pieces), SUM(pesos), SUM(source_rows)
        FROM {schema}.sales_mart WHERE principal = 'delmonte' AND level = 'product' GROUP BY 1, 2"""),
    ("sales: real view = _Real views (Unilever)",
     """SELECT calendar_month, SUM(quantity_sold), SUM(net_amount) FROM public.unilever_sku_demand_fact_real GROUP BY 1""",
     """SELECT period, SUM(pieces), SUM(pesos) FROM {schema}.sales_mart_real WHERE principal = 'unilever' GROUP BY 1"""),
    ("sales: real view = _Real views (Del Monte sell-out)",
     """SELECT _period, SUM(quantity), SUM(net_amount) FROM public.sellout_fact_real GROUP BY 1""",
     """SELECT period, SUM(pieces), SUM(pesos) FROM {schema}.sales_month WHERE principal = 'delmonte' AND data_kind = 'real' GROUP BY 1"""),
    ("flows: purchases",
     """SELECT principal, _period, {schema}.source_tag(is_demo, fill_source),
               SUM(CASE WHEN principal = 'delmonte' THEN net_amount - COALESCE(tax_amount, 0) ELSE net_amount END), COUNT(*)
        FROM public.purchase_fact GROUP BY 1, 2, 3""",
     """SELECT principal, period, source_tag, pesos, source_rows FROM {schema}.flow_month WHERE flow = 'purchases'"""),
    ("flows: estimated receipts",
     """SELECT principal, _period, SUM(receipt_value), SUM(receipt_pieces), COUNT(*), COUNT(*) FILTER (WHERE flag = 'negative_balance')
        FROM public.derived_receipt_fact GROUP BY 1, 2""",
     """SELECT principal, period, pesos, pieces, source_rows, negative_rows FROM {schema}.flow_month WHERE flow = 'estimated_receipts'"""),
    ("flows: returns",
     """SELECT principal, _period, {schema}.source_tag(is_demo, fill_source), SUM(net_amount), SUM(quantity_pieces), COUNT(*)
        FROM public.salesreturn_fact GROUP BY 1, 2, 3""",
     """SELECT principal, period, source_tag, pesos, pieces, source_rows FROM {schema}.flow_month WHERE flow = 'returns'"""),
    ("inventory: inventory_fact",
     """SELECT principal, _period, {schema}.source_tag(is_demo, fill_source),
               SUM(COALESCE(valuation, quantity_on_hand * unit_cost_per_case)), SUM(quantity_on_hand), SUM(quantity_pieces), COUNT(*)
        FROM public.inventory_fact GROUP BY 1, 2, 3""",
     """SELECT principal, period, source_tag, SUM(pesos), SUM(cases), SUM(loose_pieces), SUM(source_rows)
        FROM {schema}.inventory_mart GROUP BY 1, 2, 3"""),
    ("inventory: pieces = backend/stock_units.STOCK_PIECES_EXPR (Unilever, real)",
     """SELECT inv._period, inv.product_key,
               CASE WHEN pd.pack_size ~ '^[0-9]+(\\.[0-9]+)?$' AND pd.pack_size::numeric > 0
                    THEN SUM(inv.quantity_on_hand) * pd.pack_size::numeric + COALESCE(SUM(inv.quantity_pieces), 0) END
        FROM public.inventory_fact_real inv JOIN public.product_dimension pd ON pd.product_key = inv.product_key
        WHERE inv.principal = 'unilever' GROUP BY inv._period, inv.product_key, pd.pack_size""",
     """SELECT period, product_key, pieces FROM {schema}.inventory_mart_real WHERE principal = 'unilever'"""),
    ("accuracy: one row per forecast history value",
     """SELECT run_id, product_key, month FROM {schema}.forecast_run_value""",
     """SELECT run_id, product_key, month FROM {schema}.accuracy_mart"""),
    ("forecast history: stored run = forecast_result",
     """SELECT product_key, to_char(forecast_date, 'YYYY-MM'), forecast_value, status FROM public.forecast_result""",
     """SELECT v.product_key, v.month, v.forecast_pieces, v.status FROM {schema}.forecast_run_value v
        JOIN {schema}.forecast_run r USING (run_id)
        WHERE r.kind = 'stored_run' AND r.source_generated_at = (SELECT MAX(generated_at) FROM public.forecast_result)"""),
]

# Figures already on record, recomputed from the marts.
RECORDED = [
    # 108 / PHP 1,689,351.75: Unilever products in the 2026-03 count (counted 2026-04-06) with no piece sold
    # 2025-09..2026-02 - reproduced from inventory_fact_real + unilever_sku_demand_fact_real on 2026-10-04.
    ("idle stock at the 2026-03 count: products", "SELECT COUNT(*) FROM {schema}.idle_stock WHERE count_period = '2026-03'", 108),
    ("idle stock at the 2026-03 count: pesos", "SELECT ROUND(SUM(pesos), 2) FROM {schema}.idle_stock WHERE count_period = '2026-03'",
     1689351.75),
]


def _connect():
    from analytics.config import get_settings
    return psycopg2.connect(get_settings().supabase_db_url)


def build(cur, schema: str) -> None:
    from scripts.run_canonical_load import _strip_sql_file
    sql = _strip_sql_file(MIGRATION.read_text(encoding="utf-8"))
    sql = re.sub(r"\bmart\b", schema, sql)
    cur.execute("SHOW default_transaction_read_only")
    if cur.fetchone()[0] != "off":
        raise SystemExit("default_transaction_read_only is on for this connection; refusing to build")
    cur.execute("SELECT to_regnamespace(%s)", (schema,))
    if cur.fetchone()[0] is not None:
        raise SystemExit(f"schema {schema} already exists; drop it first (or pass --check-only)")
    t0 = time.time()
    cur.execute(sql)
    print(f"[build] {schema}: migration 0041 applied in {time.time() - t0:.1f}s")
    t0 = time.time()
    cur.execute(f"SELECT {schema}.refresh(%(trigger)s, %(idle_months)s, %(partial)s)", refresh_params("rehearsal"))
    print(f"[build] second refresh with analytics.params values: {time.time() - t0:.1f}s, rows {cur.fetchone()[0]}")


def check(cur, schema: str) -> bool:
    ok = True
    print(f"\n{'check':<74} {'source rows':>12} {'diffs':>6}")
    for name, src, mart in CHECKS:
        s, m = src.format(schema=schema), mart.format(schema=schema)
        cur.execute(f"SELECT COUNT(*) FROM ({s}) x")
        n = cur.fetchone()[0]
        cur.execute(f"SELECT (SELECT COUNT(*) FROM (({s}) EXCEPT ALL ({m})) a) + (SELECT COUNT(*) FROM (({m}) EXCEPT ALL ({s})) b)")
        diffs = cur.fetchone()[0]
        ok &= diffs == 0
        print(f"{name:<74} {n:>12,} {diffs:>6}{'' if diffs == 0 else '  FAIL'}")
    for name, sql, expected in RECORDED:
        cur.execute(sql.format(schema=schema))
        got = cur.fetchone()[0]
        good = got is not None and float(got) == float(expected)
        ok &= good
        print(f"{name:<74} {'expected':>12} {expected!s:>14}  got {got}{'' if good else '  FAIL'}")
    cur.execute(f"""SELECT COUNT(*) FROM {schema}.sales_mart WHERE pesos = 'NaN' OR pieces = 'NaN'""")
    nan_sales = cur.fetchone()[0]
    cur.execute(f"""SELECT COUNT(*) FROM {schema}.inventory_mart WHERE pesos = 'NaN' OR pieces = 'NaN'""")
    nan_inv = cur.fetchone()[0]
    print(f"{'NaN values (sales_mart, inventory_mart)':<74} {'':>12} {nan_sales + nan_inv:>6}")
    ok &= nan_sales + nan_inv == 0
    return ok


def sizes(cur, schema: str, label: str) -> float:
    """Table + index + TOAST size of every mart table, in MB."""
    cur.execute("""
        SELECT c.relname, c.reltuples::bigint, pg_total_relation_size(c.oid)
        FROM pg_class c WHERE c.relnamespace = to_regnamespace(%s) AND c.relkind = 'r' ORDER BY 3 DESC
    """, (schema,))
    rows = cur.fetchall()
    total = sum(r[2] for r in rows) / 1024 / 1024
    print(f"\n{label}\n{'table':<24} {'rows':>8} {'size':>10}")
    for name, n, size in rows:
        print(f"{name:<24} {max(n, 0):>8,} {size / 1024 / 1024:>8.2f} MB")
    print(f"{'TOTAL':<24} {'':>8} {total:>8.2f} MB (limit {SIZE_LIMIT_MB} MB)")
    return total


def compact(conn, schema: str) -> None:
    """VACUUM FULL every mart table (scratch only): the size with no dead rows."""
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT relname FROM pg_class WHERE relnamespace = to_regnamespace(%s) AND relkind = 'r'", (schema,))
    for (name,) in cur.fetchall():
        cur.execute(f'VACUUM FULL ANALYZE "{schema}"."{name}"')
    conn.autocommit = False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schema", default=SCRATCH, help=f"schema to build/check (default {SCRATCH})")
    p.add_argument("--keep", action="store_true", help="do not drop the scratch schema afterwards")
    p.add_argument("--check-only", action="store_true", help="only run the checks against an existing schema")
    args = p.parse_args()
    if not args.check_only and not args.schema.startswith("ssm_"):
        p.error("a build goes to a scratch schema named ssm_*; use --check-only to check live")
    conn = _connect()
    try:
        cur = conn.cursor()
        if args.check_only:
            cur.execute("SET TRANSACTION READ ONLY")
            ok = check(cur, args.schema)
            total = sizes(cur, args.schema, "SIZE NOW")
            conn.rollback()
        else:
            build(cur, args.schema)
            conn.commit()
            ok = check(cur, args.schema)
            # Built, then refreshed once more: every derived mart holds one set of live and
            # one of dead rows, the most a refresh leaves before VACUUM reclaims them.
            total = sizes(cur, args.schema, "SIZE AFTER TWO BUILDS (live + one refresh of dead rows: the steady-state peak)")
            conn.commit()
            compact(conn, args.schema)
            cur = conn.cursor()
            sizes(cur, args.schema, "SIZE AFTER VACUUM FULL (live rows only)")
            conn.commit()
            if not args.keep:
                cur.execute(f'DROP SCHEMA "{args.schema}" CASCADE')
                conn.commit()
                print(f"\n[drop] {args.schema} dropped")
    finally:
        conn.close()
    ok &= total < SIZE_LIMIT_MB
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
