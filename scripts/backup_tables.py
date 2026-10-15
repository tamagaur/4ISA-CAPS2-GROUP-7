"""
scripts/backup_tables.py — scoped backup: named tables only, rows plus the
structure needed to put them back.

Why this exists (reports/SCHEMA_REORG_PLAN.md section 5, prerequisite P4):
Hard Rule 8 wants a backup before a live write, but `scripts/backup_everything.py`
dumps every schema of ours and has twice lost its SSL connection part way
through (26 min on 2026-10-08). A migration that touches 6 tables of 0.35 MB
does not need an 18 MB+ dump of everything to be safe, and a backup that
cannot finish is not a backup. This dumps exactly the tables named on the
command line.

Differences from backup_live_db.create_backup, both deliberate:
  * No credential exclusions. That module drops `auth_token` entirely and
    `users.password_hash`, which is right for a shareable snapshot of the
    whole database and wrong here: these ARE the auth tables, and a restore
    that silently loses every password and invite link is not a restore.
    Everything written lands in `backups/`, which is git-ignored
    (.gitignore:95) — it must never be committed, attached or shared.
  * Rows come out through server-side `COPY ... TO STDOUT` as CSV, not
    through pandas. Nothing parses a value on the way out, so there is no
    Decimal/NaN/JSON round-trip to get wrong (the two defects
    backup_live_db.py documents at its lines 128-155), and the work happens
    in the database (CLAUDE.md efficiency rule 12).

READ ONLY: one transaction, `SET TRANSACTION READ ONLY`, confirmed by asking
the database for `transaction_read_only` before anything is read, and rolled
back at the end. Never `set_session(readonly=True)` (Hard Rule 7).

Writes:
  backups/tables_<timestamp>/
    manifest.json        per table: live row count, CSV data-row count, bytes,
                         sha256, and whether the two counts agree
    data/<table>.csv     COPY ... WITH (FORMAT csv, HEADER) — one file per table
    structure.json       columns (name, type, nullable, default, identity),
                         primary key, foreign keys, indexes (pg_get_indexdef),
                         table and column comments, owner, RLS state, grants

Verification is not optional and not a flag: every CSV is re-opened and its
data rows counted against the live count the same transaction read. A
mismatch makes the run exit 1 and say which table.

    python -m scripts.backup_tables users user_session auth_token \\
        user_mfa user_permission_override audit_log schema_migrations
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

from analytics.config import get_settings, long_read_db_url

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_ROOT = REPO_ROOT / "backups"


def _p(msg: str) -> None:
    print(msg, flush=True)


def _structure(cur, schema: str, tables: list[str]) -> dict:
    """Catalog facts per table, enough to rebuild it where it was."""
    out: dict[str, dict] = {}
    for t in tables:
        qname = f'"{schema}"."{t}"'
        d: dict = {}
        cur.execute(
            """SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS type,
                      a.attnotnull, a.attidentity,
                      pg_get_expr(ad.adbin, ad.adrelid) AS default_expr,
                      col_description(a.attrelid, a.attnum) AS comment
                 FROM pg_attribute a
                 LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
                WHERE a.attrelid = %s::regclass
                  AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY a.attnum""",
            (qname,),
        )
        d["columns"] = [
            {"name": r[0], "type": r[1], "not_null": r[2], "identity": r[3] or None,
             "default": r[4], "comment": r[5]}
            for r in cur.fetchall()
        ]
        cur.execute(
            """SELECT con.conname, pg_get_constraintdef(con.oid), con.contype
                 FROM pg_constraint con
                WHERE con.conrelid = %s::regclass
                ORDER BY con.contype, con.conname""",
            (qname,),
        )
        d["constraints"] = [{"name": r[0], "definition": r[1], "type": r[2]} for r in cur.fetchall()]
        cur.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND tablename = %s "
                    "ORDER BY indexname", (schema, t))
        d["indexes"] = [r[0] for r in cur.fetchall()]
        cur.execute(
            """SELECT c.oid::int, pg_get_userbyid(c.relowner), c.relrowsecurity,
                      c.relforcerowsecurity, obj_description(c.oid, 'pg_class'),
                      (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)
                 FROM pg_class c WHERE c.oid = %s::regclass""",
            (qname,),
        )
        oid, owner, rls, force, comment, policies = cur.fetchone()
        d.update({"oid": oid, "owner": owner, "rls_enabled": rls, "rls_forced": force,
                  "comment": comment, "policy_count": policies})
        cur.execute(
            """SELECT grantee, privilege_type FROM information_schema.role_table_grants
                WHERE table_schema = %s AND table_name = %s ORDER BY grantee, privilege_type""",
            (schema, t),
        )
        grants: dict[str, list[str]] = {}
        for grantee, priv in cur.fetchall():
            grants.setdefault(grantee, []).append(priv)
        d["grants"] = grants
        out[t] = d
    return out


def _csv_data_rows(path: Path) -> int:
    """Data rows in a COPY-written CSV with HEADER: parsed with the csv module,
    so an embedded newline inside a quoted value counts as one row, not two."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        return max(sum(1 for _ in csv.reader(fh)) - 1, 0)


def backup_tables(tables: list[str], schema: str = "public",
                  out_dir: Path | None = None) -> tuple[Path, bool]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = out_dir or BACKUP_ROOT / f"tables_{ts}"
    (out_dir / "data").mkdir(parents=True, exist_ok=True)

    conn = psycopg2.connect(long_read_db_url())
    conn.autocommit = False
    ok = True
    manifest: dict = {"created_utc": ts, "schema": schema, "scoped": True,
                      "includes_credentials": True, "tables": {}}
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SHOW transaction_read_only")
        if cur.fetchone()[0] != "on":
            raise RuntimeError("database did not confirm transaction_read_only = on; refusing to read")
        _p(f"Scoped backup of {len(tables)} table(s) from {schema} -> {out_dir}")

        missing = []
        for t in tables:
            cur.execute("SELECT to_regclass(%s)", (f'"{schema}"."{t}"',))
            if cur.fetchone()[0] is None:
                missing.append(t)
        if missing:
            raise RuntimeError(f"not in {schema}: {', '.join(missing)}")

        for t in tables:
            cur.execute(f'SELECT count(*) FROM "{schema}"."{t}"')
            live = cur.fetchone()[0]
            path = out_dir / "data" / f"{t}.csv"
            with path.open("w", encoding="utf-8", newline="") as fh:
                cur.copy_expert(
                    f'COPY (SELECT * FROM "{schema}"."{t}") TO STDOUT WITH (FORMAT csv, HEADER)', fh
                )
            on_disk = _csv_data_rows(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            match = on_disk == live
            ok = ok and match
            manifest["tables"][t] = {"live_rows": live, "csv_rows": on_disk, "match": match,
                                    "bytes": path.stat().st_size, "sha256": digest,
                                    "file": f"data/{t}.csv"}
            _p(f"  {t:26} live={live:<8} csv={on_disk:<8} {'OK' if match else 'MISMATCH'}  "
               f"{path.stat().st_size} bytes")

        (out_dir / "structure.json").write_text(
            json.dumps(_structure(cur, schema, tables), indent=2, default=str), encoding="utf-8")
        manifest["verified"] = ok
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    finally:
        conn.rollback()
        conn.close()
    _p(f"{'VERIFIED' if ok else 'FAILED'}: every CSV row count {'matches' if ok else 'does NOT match'} live")
    return out_dir, ok


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    schema = "public"
    tables = []
    i = 0
    while i < len(argv):
        if argv[i] == "--schema":
            schema = argv[i + 1]
            i += 2
            continue
        tables.append(argv[i])
        i += 1
    out_dir, ok = backup_tables(tables, schema=schema)
    print(f"\npath: {out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
