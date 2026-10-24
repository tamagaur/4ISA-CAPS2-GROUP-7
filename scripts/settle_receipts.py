"""
scripts/settle_receipts.py - settle expected receipts against a stock count (migration 0069).

    python -m scripts.settle_receipts                          # dry run on the latest Unilever count: writes nothing
    python -m scripts.settle_receipts --period 2026-03         # dry run for that count
    python -m scripts.settle_receipts --period 2026-03 --write --approved-by NAME --target-public

The rules are analytics/receipt_settlement.py's (and docs/ROLLOVER_DESIGN.md section b). Dry run by default. A write
changes only expected_receipt (state, settled_*, not_visible_in_count, stock_change_pieces): no count, sale, forecast
or plan is touched, nothing is corrected, and running it twice changes nothing the second time.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analytics import receipt_settlement  # noqa: E402


def connect(schema: str):
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor()
    cur.execute("BEGIN")
    return conn, cur


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", help="the count's file month, YYYY-MM (default: the latest Unilever count)")
    ap.add_argument("--schema", default="public")
    ap.add_argument("--write", action="store_true", help="settle (default is a dry run)")
    ap.add_argument("--approved-by", metavar="NAME", help="who approved the write (required with --write)")
    ap.add_argument("--target-public", action="store_true", help="explicit-only: allow --write on the live schema")
    args = ap.parse_args()
    if args.write and not args.approved_by:
        ap.error("--write needs --approved-by NAME")
    if args.write and args.schema == "public" and not args.target_public:
        ap.error("--write on public needs --target-public")
    conn, cur = connect(args.schema)
    try:
        if args.schema != "public":
            cur.execute("SELECT set_config('search_path', %s, true)", (f"{args.schema}, public",))   # this transaction only
        if not args.write:
            cur.execute("SET TRANSACTION READ ONLY")
        period = args.period or receipt_settlement.latest_count_period(cur)
        out = receipt_settlement.settle(cur, period, write=args.write)
        for k, v in out.items():
            print(f"{k:24} {v}")
        if args.write:
            conn.commit()
            print(f"written by {args.approved_by}")
        else:
            conn.rollback()
            print("dry run: nothing written")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
