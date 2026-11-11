"""
scripts.restore_abc_purge — undo for the 2026-08 ABC_Classification purge.

Re-inserts every row dumped in reports/abc_purge_backup_2026-08.json back
into ABC_Classification. This is the paired restore for the purge that
removed:
  - principal='delmonte'  — ALL periods (Del Monte out of active scope;
    56/66 periods synthetic/mixed/orphan; routers' MAX(classification_period)
    has no principal filter so any surviving Del Monte period past 2026-02
    poisoned the default view)
  - principal='unilever'  — 2021-01..2022-12 and 2026-03..2026-08
    (synthetic-era periods; real Unilever demand is 2023-01..2026-02)

Del Monte *source* data (sellout_fact, sellout_fact_real) was never
touched, so a full recompute via analytics.classification.orchestrate_abc
is the forward path; this script is only the literal row-level undo.

Usage:
  python -m scripts.restore_abc_purge --dry-run   # insert then ROLLBACK, report counts
  python -m scripts.restore_abc_purge --write     # insert and COMMIT

Restore is idempotent: ON CONFLICT (product_key, classification_period)
DO NOTHING, so re-running against a partially-restored table is safe.
classification_key is NOT restored (it is GENERATED ALWAYS AS IDENTITY);
new surrogate keys are assigned on insert. Every other column, including
computed_at, is restored verbatim.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the repo root, so `analytics` imports when run as a file

BACKUP_PATH = Path(__file__).resolve().parents[1] / "reports" / "abc_purge_backup_2026-08.json"

RESTORE_COLUMNS = (
    "product_key",
    "principal",
    "classification_period",
    "tier",
    "revenue_share",
    "cumulative_share",
    "boundary_flag",
    "computed_at",
)


def _load_backup(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _rows_to_tuples(rows: list[dict]) -> list[tuple]:
    out = []
    for r in rows:
        out.append(tuple(r[c] for c in RESTORE_COLUMNS))
    return out


def restore(dry_run: bool) -> None:
    load_dotenv()
    payload = _load_backup(BACKUP_PATH)
    rows = payload["rows"]
    meta = payload["_meta"]
    print(f"Backup file:       {BACKUP_PATH}")
    print(f"Backup created:    {meta.get('created_utc')}")
    print(f"Rows in file:      {len(rows)}")
    print(f"Grand total meta:  {meta.get('grand_total')}")
    assert len(rows) == meta.get("grand_total"), "file row count != meta.grand_total"

    tuples = _rows_to_tuples(rows)

    from analytics.config import long_read_db_url
    dsn = long_read_db_url()  # analytics.config.long_read_db_url: SUPABASE_DIRECT_URL only when it is the same database (2026-11-11)
    conn = psycopg2.connect(dsn, options="-c statement_timeout=0")
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ABC_Classification")
            before = cur.fetchone()[0]
            execute_values(
                cur,
                """
                INSERT INTO ABC_Classification
                    (product_key, principal, classification_period, tier,
                     revenue_share, cumulative_share, boundary_flag, computed_at)
                VALUES %s
                -- Migration 0017 widened the natural key to include `method`.
                -- The pre-0017 two-column target no longer matches any unique
                -- index, so this statement raised InvalidColumnReference. The
                -- backup predates 0017 and carries no method column, so its
                -- rows land on the DB default ('single') — which is what they
                -- were by construction.
                ON CONFLICT (product_key, classification_period, method) DO NOTHING
                """,
                tuples,
                page_size=200000,
            )
            inserted = cur.rowcount
            cur.execute("SELECT COUNT(*) FROM ABC_Classification")
            after = cur.fetchone()[0]

            print(f"\nRows before:       {before}")
            print(f"INSERT rowcount:   {inserted}")
            print(f"Rows after:        {after}")
            print(f"Net new rows:      {after - before}")

            # per-principal verification against the backup's own meta block
            periods_by_principal = {
                p: set(d["periods"]) for p, d in meta["by_principal"].items()
            }
            all_periods = sorted({per for s in periods_by_principal.values() for per in s})
            cur.execute("""
                SELECT principal, classification_period, COUNT(*) c
                FROM ABC_Classification
                WHERE classification_period = ANY(%s)
                GROUP BY principal, classification_period
            """, (all_periods,))
            live: dict[str, int] = {}
            for pr, per, c in cur.fetchall():
                if per in periods_by_principal.get(pr, ()):
                    live[pr] = live.get(pr, 0) + c
            meta_totals = {p: d["total"] for p, d in meta["by_principal"].items()}
            print(f"\nIn-scope rows now present, by principal: {live}")
            print(f"Backup meta totals, by principal:        {meta_totals}")
            print(f"Match: {live == meta_totals}")

        if dry_run:
            conn.rollback()
            print("\nDRY RUN — transaction ROLLED BACK. Nothing was committed.")
        else:
            conn.commit()
            print("\nCOMMITTED.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Insert then ROLLBACK; report counts only.")
    g.add_argument("--write", action="store_true", help="Insert and COMMIT.")
    args = ap.parse_args()
    restore(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
