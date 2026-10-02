"""
scripts/apply_migration_0035.py — applies
analytics/db/migrations/0035_user_two_factor.sql to the live database ON ITS
OWN, with its schema_migrations row, in one transaction.

Why not `run_canonical_load.py --schema-only`: that applies every pending
migration, and Kelvin's 0032/0033 are still pending on public. This touches
only 0035.

    python scripts/apply_migration_0035.py              check only (read-only)
    python scripts/apply_migration_0035.py --apply      apply it
    add --port 5432 if the pooler's 6543 times out on your network

What it does with --apply, in ONE transaction (any failed check rolls it all
back):
  before  user_mfa doesn't exist and the ledger has no 0035 row
  apply   the file's statements (its own BEGIN/COMMIT stripped, so the ledger
          row commits with them), then the ledger row: filename, the file's
          LF sha256 (the checksum run_canonical_load.py checks), now(), you
  after   user_mfa exists with row-level security on and 0 rows; no other
          table is touched (the file only creates user_mfa)

Undo: the commented rollback at the end of the migration file, plus
DELETE FROM schema_migrations WHERE filename = '0035_user_two_factor.sql'.
Restart the backend after an undo (it remembers "0035 is applied").
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import re
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
MIGRATION = REPO / "analytics" / "db" / "migrations" / "0035_user_two_factor.sql"


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def statements(path: Path) -> str:
    """The file without comment lines and its own BEGIN;/COMMIT;."""
    kept = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--") or stripped.upper() in ("BEGIN;", "COMMIT;"):
            continue
        kept.append(line)
    return "\n".join(kept)


def state(cur) -> dict:
    cur.execute("SELECT to_regclass('public.user_mfa') IS NOT NULL")
    table = cur.fetchone()[0]
    cur.execute("SELECT applied_at FROM public.schema_migrations WHERE filename = %s", (MIGRATION.name,))
    ledger = cur.fetchone()
    rls = rows = None
    if table:
        cur.execute("SELECT relrowsecurity FROM pg_class WHERE oid = 'public.user_mfa'::regclass")
        rls = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM public.user_mfa")
        rows = cur.fetchone()[0]
    return {"table": table, "ledger": ledger is not None, "rls": rls, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="apply it (default: read-only check)")
    parser.add_argument("--port", help="replace the port in SUPABASE_DB_URL, e.g. 5432")
    args = parser.parse_args()

    load_dotenv(REPO / ".env", override=False)
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL is not set (.env).")
        return 2
    if args.port:
        url = re.sub(r":\d+/", f":{args.port}/", url, count=1)

    conn = psycopg2.connect(url, connect_timeout=15, sslmode="require")
    try:
        if not args.apply:
            # Read-only for this transaction only: autocommit off, SET
            # TRANSACTION READ ONLY first, rollback after. Never a
            # session-level read-only (tests/test_no_session_readonly.py).
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                before = state(cur)
            conn.rollback()
            print(f"user_mfa exists: {before['table']}; ledger row for {MIGRATION.name}: {before['ledger']}")
            if before["table"] or before["ledger"]:
                print("Already applied. Nothing to do.")
            else:
                print("Not applied yet. Run again with --apply to apply it.")
            return 0

        with conn.cursor() as cur:
            before = state(cur)
            print(f"before: {before}")
            if before["table"] or before["ledger"]:
                print("Already applied (table or ledger row present). Nothing done.")
                conn.rollback()
                return 1
            cur.execute(statements(MIGRATION))
            cur.execute(
                "INSERT INTO public.schema_migrations (filename, checksum, applied_at, applied_by, target_schema) "
                "VALUES (%s, %s, now(), %s, 'public')",
                (MIGRATION.name, checksum(MIGRATION), getpass.getuser()),
            )
            after = state(cur)
            print(f"after:  {after}")
            if after != {"table": True, "ledger": True, "rls": True, "rows": 0}:
                conn.rollback()
                print("After-check failed: rolled back, nothing changed.")
                return 1
        conn.commit()
        print(f"Applied {MIGRATION.name} and its ledger row. The backend picks it up within a minute.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
