"""
scripts/diff_scratch_vs_live.py — READ-ONLY comparison of the `ssm_canonical`
scratch schema (built by run_canonical_load.py) against the live `public`
schema. No writes anywhere — every query is a SELECT. Nothing here decides
a cutover; it produces evidence for Yuan's decision.

Everything runs SQL-side (COUNT, EXCEPT, JOIN) rather than pulling full
tables into pandas and diffing in memory — the first version of this script
did that and stalled for ~2 hours against inventory_fact's ~700k combined
rows (real+demo, both schemas) with zero progress output, almost certainly
from either the sheer row-by-row Python object overhead or connection-pool
contention from many short-lived engine.connect() calls. Fixed 2026-09-14
per Yuan's diagnosis before it even finished once. Every step below prints
immediately (flush=True) so a stall next time is visible, not silent.

Per table: row counts (total, by is_demo) in both schemas via COUNT(*), then
a natural-key-level diff via EXCEPT (keys in live not scratch, and reverse),
then a value comparison via a JOIN restricted to matching keys only. All
facts carry is_demo and both schemas load real+demo combined, so counts are
always split by is_demo, never blended into one number.

inventory_fact holds both principals under different real constraints
(Del Monte: sku_code/snapshot_date/region; Unilever SOH:
sku_code/snapshot_date/COALESCE(region,'')/is_demo, region always NULL) —
diffed using a superset key (principal, sku_code, snapshot_date, region,
is_demo) that's sufficient to identify a row for comparison purposes even
though it isn't the literal DB constraint for either principal alone.

Usage: python -m scripts.diff_scratch_vs_live [--schema ssm_canonical]
"""
from __future__ import annotations

import argparse
import time

from sqlalchemy import Engine, create_engine, text

from analytics.config import get_settings

TABLES = [
    {
        "table": "sales_fact",
        "key": ["invoice_num", "principal", "region"],
        "amount_col": "net_amount",
    },
    {
        "table": "purchase_fact",
        "key": ["invoice_num", "principal", "region"],
        "amount_col": "net_amount",
    },
    {
        "table": "salesreturn_fact",
        "key": ["return_slip_num", "principal", "region", "invoice_num"],
        "amount_col": "net_amount",
    },
    {
        "table": "sellout_fact",
        "key": ["category_path", "region", "_period"],
        "amount_col": "net_amount",
    },
    {
        "table": "inventory_fact",
        # Superset key spanning both principals' real constraints (see
        # module docstring) - good enough to match rows for a diff, not
        # asserted as either principal's literal DB constraint. "region" is
        # in the key for the EXCEPT-based key diff (still meaningful there
        # - it participates in Del Monte's real constraint), but excluded
        # from id_cols below since it's ALWAYS NULL for every Unilever row
        # by design (transform_ssis_soh.py) - requiring it NOT NULL for the
        # amount-diff join would wrongly zero out every Unilever comparison.
        "key": ["principal", "sku_code", "snapshot_date", "region", "is_demo"],
        "id_cols": ["principal", "sku_code", "snapshot_date", "is_demo"],
        "amount_col": "quantity_on_hand",
    },
    {
        "table": "unilever_sku_demand_fact",
        "key": ["sku_code", "calendar_month"],
        "amount_col": "quantity_sold",
    },
]


def _p(msg: str) -> None:
    print(msg, flush=True)


class _Timed:
    """Context manager that prints elapsed seconds for the query it wraps -
    added after the first SQL-side attempt hit a silent-until-timeout
    statement (sales_fact's IS-NOT-DISTINCT-FROM join, see module
    docstring) with no way to tell how long it had actually been running."""

    def __init__(self, label: str) -> None:
        self.label = label

    def __enter__(self) -> "_Timed":
        self.start = time.monotonic()
        return self

    def __exit__(self, *exc) -> None:
        _p(f"    ({self.label}: {time.monotonic() - self.start:.1f}s)")


def _require_scratch_schema(schema: str) -> None:
    if schema == "public":
        raise SystemExit("Refusing to diff against 'public' as the scratch side - "
                          "this script reads live 'public' on the other side already.")


def _table_exists(conn, schema: str, table: str) -> bool:
    q = text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = :schema AND table_name = :table"
    )
    return conn.execute(q, {"schema": schema, "table": table}).first() is not None


def _counts(conn, schema: str, table: str) -> tuple[int, int, int]:
    q = text(
        f'SELECT COUNT(*) FILTER (WHERE is_demo = false) AS real_n, '
        f'COUNT(*) FILTER (WHERE is_demo = true) AS demo_n, '
        f'COUNT(*) AS total_n '
        f'FROM "{schema}"."{table}"'
    )
    row = conn.execute(q).one()
    return int(row.total_n), int(row.real_n), int(row.demo_n)


def _key_expr(alias: str, key: list[str]) -> str:
    return ", ".join(f'{alias}."{c}"' for c in key)


def diff_table(engine: Engine, scratch_schema: str, spec: dict) -> None:
    table = spec["table"]
    key = spec["key"]
    id_cols = spec.get("id_cols", key)
    amount_col = spec["amount_col"]
    key_cols_sql = ", ".join(f'"{c}"' for c in key)

    _p(f"\n=== {table} ===")

    with engine.connect() as conn:
        for schema in (scratch_schema, "public"):
            if not _table_exists(conn, schema, table):
                _p(f"  [{schema}] table does not exist")
                return

        _p("  counting rows (live)...")
        live_total, live_real, live_demo = _counts(conn, "public", table)
        _p(f"  live:    {live_total} rows (real {live_real} / demo {live_demo})")

        _p("  counting rows (scratch)...")
        scr_total, scr_real, scr_demo = _counts(conn, scratch_schema, table)
        _p(f"  scratch: {scr_total} rows (real {scr_real} / demo {scr_demo})")

        # Rows with any null key column can't be matched on key at all -
        # count them separately so they're never silently dropped from the
        # picture (same "never silently drop" posture as the rest of this
        # pipeline), then exclude them from the EXCEPT/JOIN queries below
        # (EXCEPT already treats NULL <> NULL as "different" per standard
        # SQL, which would misreport every quarantined row as a live-only
        # or scratch-only delta - not what we want here).
        null_key_where = " OR ".join(f'"{c}" IS NULL' for c in id_cols)
        for schema, label in ((scratch_schema, "scratch"), ("public", "live")):
            q = text(f'SELECT COUNT(*) FROM "{schema}"."{table}" WHERE {null_key_where}')
            n = conn.execute(q).scalar()
            if n:
                _p(f"  {label}: {n} rows with a null id column, excluded from the key/amount diffs below "
                   f"(Postgres EXCEPT treats NULL as equal to NULL, which would wrongly collapse distinct "
                   f"null-key rows into one - same class of bug already fixed in dedup_facts() upstream)")

        key_notnull_where = " AND ".join(f'"{c}" IS NOT NULL' for c in id_cols)

        _p("  diffing keys (live-only)...")
        q_live_only = text(f"""
            SELECT {key_cols_sql} FROM "public"."{table}"
            WHERE {key_notnull_where}
            EXCEPT
            SELECT {key_cols_sql} FROM "{scratch_schema}"."{table}"
            WHERE {key_notnull_where}
        """)
        with _Timed("live-only EXCEPT"):
            live_only = conn.execute(q_live_only).fetchall()
        _p(f"  keys in live only (missing from scratch): {len(live_only)}")
        if live_only:
            _p(f"    sample (up to 5): {[tuple(r) for r in live_only[:5]]}")

        _p("  diffing keys (scratch-only)...")
        q_scratch_only = text(f"""
            SELECT {key_cols_sql} FROM "{scratch_schema}"."{table}"
            WHERE {key_notnull_where}
            EXCEPT
            SELECT {key_cols_sql} FROM "public"."{table}"
            WHERE {key_notnull_where}
        """)
        with _Timed("scratch-only EXCEPT"):
            scratch_only = conn.execute(q_scratch_only).fetchall()
        _p(f"  keys in scratch only (not yet in live): {len(scratch_only)}")
        if scratch_only:
            _p(f"    sample (up to 5): {[tuple(r) for r in scratch_only[:5]]}")

        _p(f"  comparing {amount_col} on matching keys...")
        # id_cols are guaranteed NOT NULL by key_notnull_where above, so a
        # plain "=" is correct for them AND lets Postgres use the table's
        # real UNIQUE-constraint index for an index/hash join. Reserve the
        # slower, non-index-friendly "IS NOT DISTINCT FROM" for the
        # remaining key columns that are genuinely nullable (e.g.
        # inventory_fact's "region", always NULL for Unilever) - using it
        # on every column (the first attempt) forced a scan-based join that
        # hit Supabase's statement_timeout on sales_fact alone. Found via
        # this script's own first real run, 2026-09-14.
        id_set = set(id_cols)
        join_on = " AND ".join(
            f'l."{c}" = s."{c}"' if c in id_set else f'l."{c}" IS NOT DISTINCT FROM s."{c}"'
            for c in key
        )
        q_diff_amount = text(f"""
            SELECT {_key_expr('l', key)}, l."{amount_col}" AS live_amt, s."{amount_col}" AS scratch_amt
            FROM "public"."{table}" l
            JOIN "{scratch_schema}"."{table}" s ON {join_on}
            WHERE {" AND ".join(f'l."{c}" IS NOT NULL' for c in id_cols)}
              AND round(l."{amount_col}"::numeric, 2) IS DISTINCT FROM round(s."{amount_col}"::numeric, 2)
            LIMIT 1000
        """)
        with _Timed("amount-diff JOIN"):
            differing = conn.execute(q_diff_amount).fetchall()
        _p(f"  matching keys with a differing {amount_col}: {len(differing)}"
           + (" (capped at 1000, more may exist)" if len(differing) == 1000 else ""))
        if differing:
            _p(f"    sample (up to 5): {[tuple(r) for r in differing[:5]]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schema", default="ssm_canonical")
    args = parser.parse_args()
    _require_scratch_schema(args.schema)

    cfg = get_settings()
    engine = create_engine(cfg.supabase_db_url)

    _p(f"=== diff_scratch_vs_live: scratch='{args.schema}' vs live='public' (READ ONLY, SQL-side) ===")
    for spec in TABLES:
        diff_table(engine, args.schema, spec)

    _p("\nDone. No writes were made. This report does not decide a cutover.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
