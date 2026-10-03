"""Before/after checks for migration 0039. Read-only except --trigger-test, which writes inside one
transaction and ROLLs it BACK. Run from the repository root.

    python verify_0039.py pre            pending migrations + current fill counts (read-only)
    python verify_0039.py post           fill counts, distribution, spot-check vs workbooks (read-only)
    python verify_0039.py trigger-test   insert/update test rows, read what the trigger set, ROLLBACK
"""
import os
import sys
from datetime import date, timedelta

import openpyxl
import psycopg2
from dotenv import load_dotenv

REPO = str(__import__("pathlib").Path(__file__).resolve().parents[3]).replace("\\", "/")
sys.path.insert(0, REPO)
load_dotenv(f"{REPO}/.env")

from analytics.etl.extract.ssis_soh import parse_snapshot_date, period_end_date  # noqa: E402

mode = sys.argv[1]


def connect_readonly():
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    return conn, cur


def fill_counts(cur):
    cur.execute("""
        SELECT principal, is_demo, COUNT(*), COUNT(demand_period), COUNT(days_offset),
               COUNT(*) FILTER (WHERE demand_period IS DISTINCT FROM
                   to_char(to_date(_period, 'YYYY-MM') + interval '1 month', 'YYYY-MM')) AS demand_period_off_rule
        FROM inventory_fact GROUP BY 1, 2 ORDER BY 1, 2""")
    print("principal, is_demo, rows, demand_period filled, days_offset filled, demand_period not = _period+1:")
    for r in cur.fetchall():
        print("  ", r)


if mode == "pre":
    from sqlalchemy import create_engine
    from scripts.run_canonical_load import pending_migrations
    engine = create_engine(os.environ["SUPABASE_DB_URL"])
    print("pending on public:", pending_migrations(engine, "public"))
    engine.dispose()
    conn, cur = connect_readonly()
    cur.execute("SELECT COUNT(*), MAX(filename) FROM schema_migrations")
    print("ledger rows, max filename:", cur.fetchone())
    fill_counts(cur)
    cur.execute("SELECT to_regprocedure('inventory_fact_count_month()') IS NOT NULL")
    print("trigger function present:", cur.fetchone()[0])
    cur.execute("ROLLBACK"); conn.close()

elif mode == "post":
    conn, cur = connect_readonly()
    cur.execute("SELECT filename, applied_at, applied_by, checksum FROM schema_migrations WHERE filename LIKE '0039%'")
    print("ledger 0039:", cur.fetchall())
    fill_counts(cur)
    cur.execute("""SELECT days_offset, COUNT(*), COUNT(DISTINCT _period) FROM inventory_fact
                   WHERE principal = 'unilever' AND NOT is_demo GROUP BY 1 ORDER BY 1""")
    print("real Unilever days_offset -> rows, periods:", cur.fetchall())
    cur.execute("""SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = 'inventory_fact'::regclass AND NOT tgisinternal""")
    print("triggers on inventory_fact:", cur.fetchall())
    # Spot-check: five real Unilever counts against the date in their own workbook's SOH sheet name.
    picks = ["2023-06", "2025-12", "2026-01", "2026-02", "2026-03"]
    cur.execute("""SELECT _period, MIN(snapshot_date), MAX(snapshot_date), MIN(demand_period), MAX(demand_period),
                          MIN(days_offset), MAX(days_offset), MIN(_src_file), MIN(_src_sheet), COUNT(DISTINCT _src_file), COUNT(*)
                   FROM inventory_fact WHERE principal = 'unilever' AND NOT is_demo AND _period = ANY(%s)
                   GROUP BY _period ORDER BY _period""", (picks,))
    print("\nspot-check: period | DB count date | DB demand_period | DB days_offset | sheet name | date in sheet name | rows")
    for (period, d1, d2, dp1, dp2, o1, o2, src, sheet, nfiles, n) in cur.fetchall():
        assert d1 == d2 and dp1 == dp2 and o1 == o2 and nfiles == 1, (period, d1, d2, dp1, dp2, o1, o2, nfiles)
        wb = openpyxl.load_workbook(f"{REPO}/{src}", read_only=True)
        names = [s for s in wb.sheetnames if "SOH" in s.upper()]
        wb.close()
        sheet_date = parse_snapshot_date(sheet)
        expected_offset = (d1 - period_end_date(period)).days
        print(f"  {period} | {d1} | {dp1} | {o1} | {sheet!r} (SOH sheets in file: {names}) | {sheet_date} | {n}"
              f"{'' if sheet_date == d1 else '  <- DB date differs from the sheet name (R4 guard: month end + 1)'}"
              f"  [offset check {'ok' if expected_offset == o1 else 'MISMATCH'}]")
    cur.execute("ROLLBACK"); conn.close()

elif mode == "trigger-test":
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])  # autocommit off: one transaction, rolled back
    cur = conn.cursor()
    cur.execute("SHOW transaction_read_only")
    print("transaction_read_only:", cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM inventory_fact")
    before = cur.fetchone()[0]
    cols = "(sku_code, snapshot_date, _period, principal, is_demo, _src_file, _src_sheet, demand_period, days_offset)"
    # Wrong values passed for both columns on purpose: the trigger must replace them.
    cur.execute(f"""INSERT INTO inventory_fact {cols} VALUES
        ('TRIGGER-TEST-0039-U', DATE '2026-03-02', '2026-02', 'unilever', true, 'trigger-test', 'trigger-test', 'WRONG', 999),
        ('TRIGGER-TEST-0039-D', DATE '2025-12-01', '2025-12', 'delmonte', true, 'trigger-test', 'trigger-test', 'WRONG', 999)
        RETURNING sku_code, _period, snapshot_date, demand_period, days_offset""")
    for r in cur.fetchall():
        print("  inserted:", r)
    cur.execute("""UPDATE inventory_fact SET _period = '2026-01' WHERE sku_code = 'TRIGGER-TEST-0039-U'
                   RETURNING sku_code, _period, snapshot_date, demand_period, days_offset""")
    print("  after UPDATE _period -> 2026-01:", cur.fetchone())
    conn.rollback()
    cur.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE sku_code LIKE 'TRIGGER-TEST-0039%') FROM inventory_fact")
    after, left = cur.fetchone()
    conn.rollback()
    conn.close()
    print(f"rolled back: rows before {before}, after {after}, test rows left {left}")
