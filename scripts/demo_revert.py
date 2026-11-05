"""scripts/demo_revert.py - take a database back to exactly the state it was in before a labelled demonstration month (2026-11-05).

    python -m scripts.demo_revert snapshot --tag NAME            # copy every table into schema demo_revert_NAME, fingerprint it
    python -m scripts.demo_revert verify   --tag NAME            # compare now with the snapshot: which tables differ, which do not
    python -m scripts.demo_revert revert   --tag NAME --yes      # put every table back; one transaction; rolls back unless every fingerprint matches
    python -m scripts.demo_revert drop     --tag NAME --yes      # remove the snapshot schema (only after a verified revert)

Why a snapshot and not a list of deletes. A demonstration month (March sales, then ABC, forecast, safety stock, the LP, the marts,
the close) writes into some twenty tables, updates rows in several, and a hand-written undo would be one forgotten table away from
a published figure moving. This copies ALL base tables of app, public, mart and demo, so nothing has to be remembered, and the
revert puts back exactly the rows that differ, whichever table they are in.

What it does NOT put back (EXCLUDED_TABLES). Append-only evidence: app.audit_log (a trigger already forbids update and delete) and
the sign-in records app.user_session and app.auth_token. A person signing in during the demonstration, and the revert's own audit
entry, stay on record. Everything else, including etl_load_event and the notifications a run raises, is put back.

The target. A database on 127.0.0.1 is always allowed. Any other host (live) needs --target-public AND a proof file,
local/demo_revert_proof.json, written by scripts/demo_revert_proof.py after it restored a backup, ran a month, reverted, and
found every fingerprint equal. No proof file, no write to live: that is the gate of the brief. `verify` only reads and needs neither.

How the revert is done. One transaction, session_replication_role = replica for that transaction only (so triggers and foreign-key
checks do not rewrite or reject what is being put back), per table: delete the rows the snapshot does not hold, insert the rows
it holds that are missing, compared as whole-row text; then sequences are set back; then every fingerprint (row count and an md5 of
the sorted rows) is recomputed and must equal the one taken at snapshot time, else the transaction rolls back and nothing moved.
The snapshot lives in the same database (rule 7: a scratch schema, dropped after a verified revert, rule 16).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SCHEMAS = ("app", "public", "mart", "demo")
EXCLUDED_TABLES = {"app.audit_log", "app.user_session", "app.auth_token"}
PROOF_FILE = REPO / "local" / "demo_revert_proof.json"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TAG = re.compile(r"^[a-z0-9_]{1,30}$")


def snap_schema(tag: str) -> str:
    if not TAG.match(tag):
        raise SystemExit("--tag: lowercase letters, digits and underscore, up to 30")
    return f"demo_revert_{tag}"


def snap_table(schema: str, table: str) -> str:
    return f"{schema}__{table}"


def connect(url_env: str):
    url = os.environ.get(url_env) or ""
    if not url:
        try:
            from dotenv import dotenv_values
            url = dotenv_values(REPO / ".env").get(url_env) or ""
        except ImportError:
            pass
    if not url:
        raise SystemExit(f"{url_env} is not set")
    host = urlparse(url).hostname or ""
    conn = psycopg2.connect(url)
    return conn, host in LOCAL_HOSTS


def require_write_allowed(is_local: bool, target_public: bool, proof_file: Path = PROOF_FILE) -> None:
    """A write to anything but the throwaway server needs the flag and a passing proof on this machine."""
    if is_local:
        return
    if not target_public:
        raise SystemExit("REFUSED: this is not the local throwaway server; pass --target-public")
    if not proof_file.is_file() or json.loads(proof_file.read_text(encoding="utf-8")).get("passed") is not True:
        raise SystemExit(f"REFUSED: no passing revert proof at {proof_file}. Run scripts.demo_revert_proof first (the gate of the brief).")


def base_tables(cur) -> list[tuple[str, str]]:
    cur.execute("""SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s) ORDER BY 1, 2""", (list(SCHEMAS),))
    return [(s, t) for s, t in cur.fetchall() if f"{s}.{t}" not in EXCLUDED_TABLES]


def fingerprint(cur, schema: str, table: str) -> tuple[int, str]:
    cur.execute(f'SELECT count(*), md5(coalesce(string_agg(x::text, \',\' ORDER BY x::text), \'\')) FROM "{schema}"."{table}" x')
    n, h = cur.fetchone()
    return int(n), h


def sequences(cur) -> list[tuple[str, str, int, bool]]:
    # A sequence that belongs to an excluded table (audit_log, user_session, auth_token) is left alone: the table keeps its rows through a revert,
    # so setting its sequence back would hand out a key a surviving row already holds (found in the second browser rehearsal: a sign-in after an undo).
    cur.execute('''SELECT s.schemaname, s.sequencename FROM pg_sequences s
                   WHERE s.schemaname = ANY(%s) AND NOT EXISTS (
                       SELECT 1 FROM pg_depend d JOIN pg_class t ON t.oid = d.refobjid JOIN pg_namespace tn ON tn.oid = t.relnamespace
                       WHERE d.objid = (quote_ident(s.schemaname) || '.' || quote_ident(s.sequencename))::regclass AND d.deptype IN ('a', 'i')
                         AND (tn.nspname || '.' || t.relname) = ANY(%s))
                   ORDER BY 1, 2''', (list(SCHEMAS), sorted(EXCLUDED_TABLES)))
    out = []
    for s, q in cur.fetchall():
        cur.execute(f'SELECT last_value, is_called FROM "{s}"."{q}"')
        v, called = cur.fetchone()
        out.append((s, q, int(v), bool(called)))
    return out


def take_snapshot(conn, tag: str) -> dict:
    sch = snap_schema(tag)
    cur = conn.cursor()
    cur.execute("SET LOCAL statement_timeout = 0")
    cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (sch,))
    if cur.fetchone():
        raise SystemExit(f"REFUSED: schema {sch} already exists. Verify or drop it; a snapshot is never overwritten.")
    cur.execute(f'CREATE SCHEMA "{sch}"')
    manifest = {}
    for s, t in base_tables(cur):
        cur.execute(f'CREATE TABLE "{sch}"."{snap_table(s, t)}" AS TABLE "{s}"."{t}"')
        manifest[f"{s}.{t}"] = fingerprint(cur, s, t)
        cur.execute(f'SELECT count(*) FROM "{sch}"."{snap_table(s, t)}"')
        if cur.fetchone()[0] != manifest[f"{s}.{t}"][0]:
            raise SystemExit(f"snapshot of {s}.{t} does not hold its rows; nothing was kept")
    seqs = sequences(cur)
    cur.execute(f'CREATE TABLE "{sch}"._manifest (tbl text PRIMARY KEY, n bigint NOT NULL, md5 text NOT NULL)')
    cur.executemany(f'INSERT INTO "{sch}"._manifest VALUES (%s, %s, %s)', [(k, n, h) for k, (n, h) in manifest.items()])
    cur.execute(f'CREATE TABLE "{sch}"._sequences (sch text, seq text, last_value bigint, is_called boolean)')
    cur.executemany(f'INSERT INTO "{sch}"._sequences VALUES (%s, %s, %s, %s)', seqs)
    conn.commit()
    return manifest


def read_manifest(cur, tag: str) -> dict:
    sch = snap_schema(tag)
    cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (sch,))
    if not cur.fetchone():
        raise SystemExit(f"no snapshot {sch}")
    cur.execute(f'SELECT tbl, n, md5 FROM "{sch}"._manifest')
    return {t: (int(n), h) for t, n, h in cur.fetchall()}


def compare(cur, manifest: dict) -> list[str]:
    """Tables whose count or fingerprint now differs from the snapshot's; empty means identical."""
    return [f"{k}: {n} -> {fingerprint(cur, *k.split('.'))[0]} rows" for k, (n, h) in manifest.items()
            if fingerprint(cur, *k.split('.')) != (n, h)]


def revert(conn, tag: str, after_tables=None) -> list[str]:
    """`after_tables(cur)`, when given, runs inside the same transaction after the tables are back and returns a list of problems (it may also
    change things: scripts/demo_session puts the view and function definitions back there). Any problem rolls everything back."""
    sch = snap_schema(tag)
    cur = conn.cursor()
    manifest = read_manifest(cur, tag)
    cur.execute("SET LOCAL statement_timeout = 0")
    cur.execute("SET LOCAL session_replication_role = replica")
    touched = []
    for key in manifest:
        s, t = key.split(".")
        snap = f'"{sch}"."{snap_table(s, t)}"'
        cur.execute(f'SELECT count(*) FROM "{s}"."{t}" x WHERE NOT EXISTS (SELECT 1 FROM {snap} y WHERE y::text = x::text)')
        extra = cur.fetchone()[0]
        cur.execute(f'SELECT count(*) FROM {snap} y WHERE NOT EXISTS (SELECT 1 FROM "{s}"."{t}" x WHERE x::text = y::text)')
        missing = cur.fetchone()[0]
        if not extra and not missing:
            continue
        cur.execute("""SELECT a.attname FROM pg_attribute a WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
                          AND a.attgenerated = '' ORDER BY a.attnum""", (f'"{s}"."{t}"',))
        cols = ", ".join(f'"{r[0]}"' for r in cur.fetchall())
        cur.execute(f'DELETE FROM "{s}"."{t}" x WHERE NOT EXISTS (SELECT 1 FROM {snap} y WHERE y::text = x::text)')
        cur.execute(f'INSERT INTO "{s}"."{t}" ({cols}) OVERRIDING SYSTEM VALUE SELECT {cols} FROM {snap} y '
                    f'WHERE NOT EXISTS (SELECT 1 FROM "{s}"."{t}" x WHERE x::text = y::text)')
        touched.append(f"{key}: removed {extra}, put back {missing}")
    cur.execute(f'SELECT sch, seq, last_value, is_called FROM "{sch}"._sequences')
    for s, q, v, called in cur.fetchall():
        cur.execute("SELECT setval(%s::regclass, %s, %s)", (f'"{s}"."{q}"', v, called))
    still = compare(cur, manifest) + (list(after_tables(cur)) if after_tables else [])
    if still:
        conn.rollback()
        raise SystemExit("ROLLED BACK, nothing moved. After the revert these still differ: " + "; ".join(still))
    conn.commit()
    return touched


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["snapshot", "verify", "revert", "drop"])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--target-public", action="store_true", help="allow a write to a database that is not the local throwaway server")
    ap.add_argument("--url-env", default="SUPABASE_DB_URL")
    args = ap.parse_args(argv)
    conn, is_local = connect(args.url_env)
    try:
        if args.cmd == "verify":
            conn.autocommit = False
            cur = conn.cursor()
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = 0")
            diff = compare(cur, read_manifest(cur, args.tag))
            conn.rollback()
            print("IDENTICAL to the snapshot" if not diff else "DIFFERS:\n  " + "\n  ".join(diff))
            return 0 if not diff else 1
        require_write_allowed(is_local, args.target_public)
        if args.cmd == "snapshot":
            m = take_snapshot(conn, args.tag)
            print(f"snapshot {snap_schema(args.tag)}: {len(m)} tables, {sum(n for n, _ in m.values()):,} rows")
        elif args.cmd == "revert":
            if not args.yes:
                raise SystemExit("revert needs --yes")
            touched = revert(conn, args.tag)
            print("reverted; every fingerprint equals the snapshot's.\n  " + ("\n  ".join(touched) if touched else "(nothing had changed)"))
        else:
            if not args.yes:
                raise SystemExit("drop needs --yes")
            if compare(conn.cursor(), read_manifest(conn.cursor(), args.tag)):
                conn.rollback()
                raise SystemExit("REFUSED: the database still differs from the snapshot; revert first")
            conn.cursor().execute(f'DROP SCHEMA "{snap_schema(args.tag)}" CASCADE')
            conn.commit()
            print("snapshot schema dropped")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
