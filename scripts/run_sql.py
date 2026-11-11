"""scripts/run_sql.py — runs a .sql file, read-only unless told to write a scratch schema.

Rule (security audit 2026-09-30): nothing writes to public except a numbered
migration in analytics/db/migrations/, applied by the ledgered runner
(scripts/run_canonical_load.py). This script is for SELECTs and scratch
schemas only.

  python scripts/run_sql.py FILE.sql
      BEGIN; SET TRANSACTION READ ONLY; <the file>; ROLLBACK.
      The database itself refuses any write, and nothing is committed.

  python scripts/run_sql.py --scratch SCHEMA FILE.sql
      BEGIN; SET LOCAL search_path TO SCHEMA; <the file>; COMMIT.
      public may be read (after FROM or JOIN) but not written. Before running,
      a statement is refused if it names public anywhere else, or touches
      privileges, roles or search_path. Before committing, the transaction's
      own statistics and catalog rows are read back: any row inserted,
      updated or deleted in a public table, or any public table, function or
      type created, changed or dropped, rolls the whole file back. That check
      is a backstop, not a proof - a catalog change it does not look at can
      still slip through - so the refusals above come first.

Every setting is transaction-scoped (SET TRANSACTION / SET LOCAL), never
session-level, so this is safe over Supabase's transaction pooler (:6543),
whose server connections are shared (see backend/deps.py). In both modes a
statement that would end the transaction early (BEGIN, COMMIT, ...) or change a
session setting (SET without LOCAL, RESET, set_config) is refused: it would
escape the read-only transaction or leak onto a shared connection.

Connects with SUPABASE_DB_URL (by SUPABASE_DIRECT_URL only when that names the same database:
analytics.config.long_read_db_url), and never tries another database when that one fails. Prints
each statement's row count, and the rows a query returns (up to MAX_ROWS_SHOWN).
Exit status: 0 done, 2 refused, anything else an error (rolled back).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extensions import TRANSACTION_STATUS_IDLE, TRANSACTION_STATUS_INTRANS
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the repo root, so `analytics` imports when run as a file

MAX_ROWS_SHOWN = 200

# A --scratch run may never target the live schema, Postgres's own or Supabase's.
NOT_SCRATCH = {
    "public", "information_schema", "auth", "storage", "realtime", "_realtime", "vault",
    "extensions", "graphql", "graphql_public", "pgbouncer", "pgsodium", "pgsodium_masks",
    "supabase_functions", "supabase_migrations", "net", "cron", "_analytics",
}
SCRATCH_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")

# Refused in both modes (checked with comments removed).
ALWAYS_REFUSED = [
    (re.compile(r"^\s*(BEGIN|START|COMMIT|END|ROLLBACK|ABORT|SAVEPOINT|RELEASE|PREPARE\s+TRANSACTION)\b", re.I),
     "controls the transaction, which this script owns"),
    (re.compile(r"^\s*SET\b(?!\s+(LOCAL|TRANSACTION|CONSTRAINTS)\b)", re.I),
     "changes a session setting (only SET LOCAL, SET TRANSACTION and SET CONSTRAINTS are allowed)"),
    (re.compile(r"^\s*(RESET|DISCARD)\b", re.I), "changes session state"),
    (re.compile(r"\bset_config\s*\(", re.I), "calls set_config, which can change a session setting"),
]

# Also refused with --scratch, where the database does not stop writes by itself.
SCRATCH_REFUSED = [
    (re.compile(r"\b(GRANT|REVOKE)\b", re.I), "changes privileges"),
    (re.compile(r"\b(CREATE|ALTER|DROP)\s+(ROLE|USER|GROUP)\b", re.I), "changes a role"),
    (re.compile(r"\bSET\s+(LOCAL\s+)?(ROLE|SESSION\s+AUTHORIZATION)\b", re.I), "switches role"),
    (re.compile(r"\bsearch_path\b", re.I), "touches search_path"),
    (re.compile(r"\bALTER\s+(DEFAULT\s+PRIVILEGES|SYSTEM|DATABASE)\b", re.I), "changes database-wide settings"),
    (re.compile(r"\bDELETE\s+FROM\s+(ONLY\s+)?\"?public\"?\s*\.", re.I), "deletes from public"),
]
PUBLIC_MENTION = re.compile(r'(?<![\w$])"?public"?(?![\w$])', re.I)
PUBLIC_READ = re.compile(r'\b(FROM|JOIN)\s+(ONLY\s+|LATERAL\s+)?"?public"?\s*\.', re.I)

# The transaction's own writes to public, read back before COMMIT.
PUBLIC_OBJECT_COUNTS_SQL = """
    SELECT (SELECT count(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace),
           (SELECT count(*) FROM pg_proc  WHERE pronamespace = 'public'::regnamespace),
           (SELECT count(*) FROM pg_type  WHERE typnamespace = 'public'::regnamespace)
"""
# xmin holds the low 32 bits of the writing transaction's id.
PUBLIC_WRITES_SQL = """
    WITH me AS (SELECT (pg_current_xact_id_if_assigned()::text::bigint % 4294967296)::text AS xid)
    SELECT 'rows written in public.' || relname FROM pg_stat_xact_user_tables
     WHERE schemaname = 'public' AND n_tup_ins + n_tup_upd + n_tup_del > 0
    UNION ALL
    SELECT 'public.' || relname || ' created or changed' FROM pg_class, me
     WHERE relnamespace = 'public'::regnamespace AND xmin::text = me.xid
    UNION ALL
    SELECT 'function public.' || proname || ' created or changed' FROM pg_proc, me
     WHERE pronamespace = 'public'::regnamespace AND xmin::text = me.xid
    UNION ALL
    SELECT 'type public.' || typname || ' created or changed' FROM pg_type, me
     WHERE typnamespace = 'public'::regnamespace AND xmin::text = me.xid
"""


class Refused(Exception):
    """The file was not run, or was rolled back, because of the rule above."""


def split_statements(raw: str) -> list[str]:
    # Strip whole comment lines BEFORE splitting on ';' — splitting first and
    # then dropping chunks whose first line starts with '--' silently drops
    # real statements that happen to follow a comment block before the next
    # ';' (found 2026-09-18: it dropped this file's CREATE SCHEMA and backup
    # CREATE TABLE, causing a "schema does not exist" error with no trace).
    # A DO $$ ... $$ block with a ';' inside is split too, so it can't run here.
    sql = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("--"))
    return [s.strip() for s in sql.split(";") if s.strip()]


def _without_comments(stmt: str) -> str:
    # One left-to-right pass, so a '--' inside a string literal stays text.
    return re.sub(
        r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/",
        lambda m: m.group(0) if m.group(0).startswith("'") else " ",
        stmt,
        flags=re.S,
    )


def refusal(stmt: str, scratch: bool) -> str | None:
    """Why this statement may not run, or None."""
    code = _without_comments(stmt)
    for pattern, why in ALWAYS_REFUSED + (SCRATCH_REFUSED if scratch else []):
        if pattern.search(code):
            return why
    if scratch and len(PUBLIC_MENTION.findall(code)) > len(PUBLIC_READ.findall(code)):
        return "names public other than as a table read after FROM or JOIN"
    return None


def check_scratch_schema(name: str) -> None:
    if not SCRATCH_NAME.fullmatch(name) or name in NOT_SCRATCH or name.startswith("pg_"):
        raise Refused(
            f"--scratch {name!r} is refused: give a scratch schema of our own "
            f"(lower-case letters, digits, _), never public, pg_* or a Supabase schema"
        )


def _first_line(stmt: str) -> str:
    return stmt.splitlines()[0][:80]


def run(conn, statements: list[str], scratch: str | None = None, out=print) -> bool:
    """Runs the statements in one transaction. Returns True if it committed
    (--scratch), False if it rolled back (read-only). Raises Refused, or the
    database's own error, after rolling back."""
    if scratch is not None:
        check_scratch_schema(scratch)
    for n, stmt in enumerate(statements, 1):
        why = refusal(stmt, scratch is not None)
        if why:
            raise Refused(f"statement {n} {why}: {_first_line(stmt)}")

    conn.autocommit = True  # client-side only: the explicit BEGIN below opens the one transaction
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            if scratch is None:
                cur.execute("SET TRANSACTION READ ONLY")
            else:
                cur.execute(f'SET LOCAL search_path TO "{scratch}"')
                cur.execute(PUBLIC_OBJECT_COUNTS_SQL)
                before = cur.fetchone()
            for n, stmt in enumerate(statements, 1):
                cur.execute(stmt)
                if conn.info.transaction_status != TRANSACTION_STATUS_INTRANS:
                    raise Refused(f"statement {n} ended the transaction: {_first_line(stmt)}")
                out(f"[{cur.rowcount} rows] {_first_line(stmt)}")
                if cur.description is not None:
                    out("  " + " | ".join(col.name for col in cur.description))
                    for row in cur.fetchmany(MAX_ROWS_SHOWN):
                        out("  " + " | ".join(str(v) for v in row))
            if scratch is None:
                cur.execute("ROLLBACK")
                out("ROLLED BACK (read-only run)")
                return False
            cur.execute(PUBLIC_WRITES_SQL)
            hits = [r[0] for r in cur.fetchall()]
            cur.execute(PUBLIC_OBJECT_COUNTS_SQL)
            after = cur.fetchone()
            for kind, b, a in zip(("relations", "functions", "types"), before, after):
                if a < b:
                    hits.append(f"{b - a} public {kind} dropped")
            if hits:
                raise Refused("the file wrote to public: " + "; ".join(hits))
            cur.execute("COMMIT")
            out("COMMITTED")
            return True
        except BaseException:
            if conn.info.transaction_status != TRANSACTION_STATUS_IDLE:
                cur.execute("ROLLBACK")
                out("ROLLED BACK")
            raise


def connect():
    """analytics.config.long_read_db_url, one URL, no fall-through. Until 2026-11-11 this took the first of DATABASE_URL,
    SUPABASE_DIRECT_URL, SUPABASE_DB_URL that answered: .env's SUPABASE_DIRECT_URL is live, so a --scratch run told
    SUPABASE_DB_URL=<a local copy> wrote its scratch schema on live, and a local copy that did not answer fell through
    to live as well."""
    load_dotenv()
    from analytics.config import long_read_db_url
    url = long_read_db_url()
    try:
        conn = psycopg2.connect(url, connect_timeout=10)
    except psycopg2.OperationalError as exc:
        raise SystemExit(f"could not connect: {str(exc).strip().splitlines()[0]}")
    print("connected with SUPABASE_DB_URL" + (" (by SUPABASE_DIRECT_URL, the same database)" if url != os.environ.get("SUPABASE_DB_URL") else ""))
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path)
    parser.add_argument("--scratch", metavar="SCHEMA", help="write to this scratch schema (never public)")
    args = parser.parse_args(argv)
    statements = split_statements(args.file.read_text(encoding="utf-8"))
    conn = connect()
    try:
        run(conn, statements, scratch=args.scratch)
    except Refused as exc:
        print(f"REFUSED: {exc}")
        return 2
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
