"""
scripts/rehearse_planning_mart.py — build migration 0046's planning mart in a scratch schema
and prove GET /recommendations answers the same from it as from the per-request joins, before
0046 goes to public.

    python -m scripts.rehearse_planning_mart                # build ssm_planning_rehearsal, compare, drop it
    python -m scripts.rehearse_planning_mart --keep         # leave the scratch schema for inspection
    python -m scripts.rehearse_planning_mart --check-only   # compare the LIVE mart (read only)

The scratch build runs the COMMITTED file, comment/BEGIN/COMMIT lines stripped exactly as the
migration runner strips them, with the four objects it creates or writes (planning_mart,
refresh_planning, refresh_status, refresh_log) moved to the scratch schema; refresh_log gets
an empty scratch copy first. Every source is read from public and the live mart schema, read
only; the only writes land in the scratch schema, which is dropped at the end (CLAUDE.md rule
16) unless --keep.

THE COMPARISON. For every principal scope x cycle (current, all) x decision status the page
can ask for, the endpoint's function is called twice in this process, once reading the mart
and once with the mart turned off (the joins), each in a read-only transaction, and the two
JSON responses must be equal: every field of every row, the freshness block, the LP model and
the stock counts. cycle=all with no status covers every lp_recommendation row, so every row
of the latest LP run is compared. The mart's stored stock_status / urgency columns (which the
endpoint does not read) are checked against the endpoint's urgency for every row too.
Exit 1 on any difference, or when the mart could not be served (a source changed after the build).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import psycopg2
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[1]
MIGRATION = REPO / "analytics" / "db" / "migrations" / "0046_planning_mart.sql"
SCRATCH = "ssm_planning_rehearsal"
MOVED = r"\bmart\.(planning_mart|refresh_planning|refresh_status|refresh_log)\b"

# (principal, cycle, status, from, to). 'current' is cheap either way; 'all' runs the joins
# once per cycle (34 live), so it is asked only as often as it takes to cover every row.
STATUSES = (None, "pending", "accepted", "dismissed")
CASES = [(p, "current", s, None, None) for p in (None, "unilever", "delmonte") for s in STATUSES] + [
    (None, "all", None, None, None),
    ("unilever", "all", None, None, None),
    ("delmonte", "all", None, None, None),
    ("unilever", "all", "pending", None, None),
    (None, "all", None, "2025-01-01", "2025-12-31"),
]


def _connect():
    from analytics.config import get_settings
    return psycopg2.connect(get_settings().supabase_db_url)


def build(cur, schema: str) -> int:
    from scripts.run_canonical_load import _strip_sql_file
    sql = re.sub(MOVED, lambda m: f"{schema}.{m.group(1)}", _strip_sql_file(MIGRATION.read_text(encoding="utf-8")))
    cur.execute("SHOW default_transaction_read_only")
    if cur.fetchone()[0] != "off":
        raise SystemExit("default_transaction_read_only is on for this connection; refusing to build")
    cur.execute("SELECT to_regnamespace(%s)", (schema,))
    if cur.fetchone()[0] is not None:
        raise SystemExit(f"schema {schema} already exists; drop it first (or pass --check-only)")
    cur.execute("SELECT COUNT(*) FROM public.lp_recommendation")
    expected = cur.fetchone()[0]
    print(f"[build] expected planning_mart rows = lp_recommendation rows = {expected}")
    cur.execute(f'CREATE SCHEMA "{schema}"')
    cur.execute(f"""
        CREATE TABLE {schema}.refresh_log (
            refresh_id bigserial PRIMARY KEY, refreshed_at timestamptz NOT NULL DEFAULT now(),
            trigger text NOT NULL, duration_ms integer NOT NULL, row_counts jsonb NOT NULL, params jsonb NOT NULL)
    """)
    t0 = time.time()
    cur.execute(sql)
    cur.execute(f"SELECT COUNT(*), COUNT(DISTINCT recommendation_key) FROM {schema}.planning_mart")
    got, keys = cur.fetchone()
    cur.execute(f"SELECT duration_ms FROM {schema}.refresh_log ORDER BY refresh_id DESC LIMIT 1")
    print(f"[build] {schema}: migration 0046 applied in {time.time() - t0:.1f}s "
          f"(refresh_planning itself {cur.fetchone()[0]} ms); planning_mart rows {got}, distinct keys {keys}")
    if got != expected or keys != expected:
        raise SystemExit(f"row count mismatch: expected {expected}, mart holds {got} ({keys} distinct keys)")
    return got


def _call(schema: str | None, case) -> dict | None:
    """The endpoint's response for one case, as JSON: from the mart in `schema`, or from the
    joins when schema is None. None when the mart refused to serve."""
    from backend import deps, planning_mart
    from backend.data_mode import REAL
    from backend.routers import recommendations as rec

    principal, cycle, status, from_date, to_date = case
    planning_mart.use_schema(schema)
    with Session(deps._get_engine()) as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        try:
            if schema is None:
                out = rec.get_recommendations(status=status, cycle=cycle, from_date=from_date, to_date=to_date,
                                              principal=principal, mode=REAL, db=db, current_user=None)
            else:
                if not planning_mart.usable(db, REAL):
                    raise SystemExit(f"{schema}.planning_mart does not exist")
                out = rec._from_mart(db, status, cycle, from_date, to_date, principal)
            return None if out is None else jsonable_encoder(out)
        finally:
            db.rollback()


def _diff(joins: dict, mart: dict) -> list[str]:
    out = []
    for key in sorted(set(joins) | set(mart)):
        if key == "items":
            continue
        if joins.get(key) != mart.get(key):
            out.append(f"{key}: joins {joins.get(key)!r} != mart {mart.get(key)!r}")
    a = {i["recommendation_key"]: i for i in joins["items"]}
    b = {i["recommendation_key"]: i for i in mart["items"]}
    for key in sorted(set(a) ^ set(b)):
        out.append(f"row {key}: only in {'joins' if key in a else 'mart'}")
    for key in sorted(set(a) & set(b)):
        for field in sorted(set(a[key]) | set(b[key])):
            if a[key].get(field) != b[key].get(field):
                out.append(f"row {key} {field}: joins {a[key].get(field)!r} != mart {b[key].get(field)!r}")
    return out


def compare(schema: str) -> tuple[bool, set[int]]:
    ok = True
    covered: set[int] = set()
    print(f"\n{'principal':<10} {'cycle':<8} {'status':<10} {'range':<22} {'rows':>5} {'diffs':>6}")
    for case in CASES:
        principal, cycle, status, from_date, to_date = case
        mart = _call(schema, case)
        joins = _call(None, case)
        label = (f"{principal or 'all':<10} {cycle:<8} {status or '-':<10} "
                 f"{(from_date + '..' + to_date) if from_date else '-':<22}")
        if mart is None:
            ok = False
            print(f"{label} {'':>5} {'':>6}  FAIL: the mart was not served (out of step with its sources)")
            continue
        diffs = _diff(joins, mart)
        ok &= not diffs
        covered |= {i["recommendation_key"] for i in mart["items"]}
        print(f"{label} {len(joins['items']):>5} {len(diffs):>6}{'' if not diffs else '  FAIL'}")
        for line in diffs[:20]:
            print(f"    {line}")
    return ok, covered


def stored_columns(cur, schema: str, covered: set[int]) -> bool:
    """Every lp_recommendation row was compared; the latest LP run's rows among them; and
    the mart's stored stock_status / urgency agree with the endpoint's urgency."""
    from backend import planning_mart
    from backend.routers import recommendations as rec
    from backend.stock_status import URGENCY

    cur.execute("SELECT recommendation_key, lp_run_key FROM public.lp_recommendation")
    rows = cur.fetchall()
    cur.execute("SELECT MAX(run_key) FROM public.lp_run")
    latest = cur.fetchone()[0]
    of_latest = {k for k, run in rows if run == latest}
    missing = {k for k, _ in rows} - covered
    print(f"\nlp_recommendation rows {len(rows)}, compared {len(covered)}, not compared {len(missing)}")
    print(f"latest lp_run = {latest}: {len(of_latest)} rows, compared {len(of_latest & covered)}")
    planning_mart.use_schema(schema)
    cur.execute(planning_mart.rows_query(None, None, "all", None, None, packed=False,
                                         columns=planning_mart.ROW_COLUMNS + planning_mart.STORED_STATUS_COLUMNS)[0])
    names = [d[0] for d in cur.description]
    wrong = 0
    for values in cur.fetchall():
        row = dict(zip(names, values))
        item = rec._to_item(row, rec._MART_PRESENT)
        if row["mart_urgency"] != item.urgency or URGENCY[row["mart_stock_status"]] != item.urgency:
            wrong += 1
            print(f"    row {row['recommendation_key']}: stored {row['mart_stock_status']}/{row['mart_urgency']}, "
                  f"endpoint {item.urgency}")
    print(f"stored stock_status / urgency differing from the endpoint's: {wrong}")
    cur.execute(f"""SELECT COUNT(*) FROM {schema}.planning_mart WHERE 'NaN' IN (stock_pieces, stock_pesos,
                    forecast_pieces, order_pieces, order_pesos, safety_stock, target_stock, avg_monthly_sales_pesos)""")
    nan = cur.fetchone()[0]
    print(f"NaN values: {nan}")
    return not missing and of_latest <= covered and wrong == 0 and nan == 0


def size(cur, schema: str) -> None:
    cur.execute(f"SELECT COUNT(*), pg_total_relation_size('{schema}.planning_mart') FROM {schema}.planning_mart")
    n, size_bytes = cur.fetchone()
    print(f"\n{schema}.planning_mart: {n} rows, {size_bytes / 1024:.0f} kB (table + indexes + TOAST)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schema", default=None, help=f"default {SCRATCH} (build) or mart (--check-only)")
    p.add_argument("--keep", action="store_true", help="do not drop the scratch schema afterwards")
    p.add_argument("--check-only", action="store_true", help="only compare an existing mart (read only)")
    args = p.parse_args()
    schema = args.schema or ("mart" if args.check_only else SCRATCH)
    if not args.check_only and not schema.startswith("ssm_"):
        p.error("a build goes to a scratch schema named ssm_*; use --check-only to compare live")
    conn = _connect()
    built = False
    try:
        cur = conn.cursor()
        if not args.check_only:
            build(cur, schema)
            conn.commit()
            built = True
        ok, covered = compare(schema)
        cur.execute("SET TRANSACTION READ ONLY")
        ok &= stored_columns(cur, schema, covered)
        size(cur, schema)
        conn.rollback()
    finally:
        if built and not args.keep:
            conn.rollback()
            cur = conn.cursor()
            cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
            conn.commit()
            print(f"\n[drop] {schema} dropped")
        conn.close()
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
