"""scripts/rehearse_0075.py - run migration 0075 (Data API lockdown) against a restored copy of live, and show what changes.

Why: 0075 is catalog-driven, so what it does to live depends on live's catalog, not on the file. A throwaway built from
schema.sql proves the SQL runs; it does not prove what live loses. This restores a backup of live into a database on the
throwaway server (127.0.0.1:55432 only), fingerprints the privilege catalog, applies 0075, fingerprints again, and also
fingerprints live (one READ ONLY transaction) so the copy can be checked against live BEFORE its delta is believed.

Fingerprint = every privilege the migration can touch: relation ACLs (table, view, sequence) with row-level-security
flag, function ACLs, default ACLs, schema ACLs, for schemas app, public, mart, demo.

    python -m scripts.rehearse_0075 --backup backups/full_backup_<stamp> [--keep]

Prints three comparisons: (1) live vs the copy before 0075 (fidelity: must be empty, else the copy is not live),
(2) the copy before vs after 0075 (the delta), (3) the delta against the two changes the migration's header predicts.
Exit 0 only when (1) is empty and (2) is exactly the two predicted. Never writes to live; drops the copy unless --keep.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2

from analytics.config import long_read_db_url
from scripts import local_pg

COPY_DB = "ssm_rehearse_0075"
MIGRATION = Path(__file__).resolve().parents[1] / "analytics" / "db" / "migrations" / "0075_lock_down_data_api.sql"
SCHEMAS = ("app", "public", "mart", "demo")

# One row per privilege-bearing object. A NULL ACL means "the owner's default" (Postgres stores nothing), and a restore may
# write that default out explicitly; the two are the same privileges, so both sides are expanded with acldefault() and the
# items sorted before they are compared. Default ACLs are compared only for the role the migration runs as (postgres) in these
# schemas or in all: Supabase's own roles (supabase_admin, supabase_auth_admin) and schemas (storage, auth, realtime ...) are not
# restored locally and are not the migration's to change (its header leaves supabase_admin's defaults alone). Grants to anon, authenticated, service_role and PUBLIC are never hidden by this.
FINGERPRINT_SQL = """
SELECT 'relation' AS kind, n.nspname || '.' || c.relname || ' [' || c.relkind::text || '] rls=' || c.relrowsecurity::text AS obj,
       array_to_string(ARRAY(SELECT x::text FROM unnest(COALESCE(c.relacl, acldefault((CASE WHEN c.relkind = 'S' THEN 's' ELSE 'r' END)::"char", c.relowner))) x ORDER BY 1), ',') AS acl
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = ANY(%(s)s) AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
UNION ALL
SELECT 'function', n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       array_to_string(ARRAY(SELECT x::text FROM unnest(COALESCE(p.proacl, acldefault('f'::"char", p.proowner))) x ORDER BY 1), ',')
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = ANY(%(s)s)
UNION ALL
SELECT 'default_acl', pg_get_userbyid(d.defaclrole) || ' in ' || COALESCE(n.nspname, '<all schemas>') || ' type ' || d.defaclobjtype::text,
       array_to_string(ARRAY(SELECT x::text FROM unnest(d.defaclacl) x ORDER BY 1), ',')
  FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
 WHERE pg_get_userbyid(d.defaclrole) = 'postgres' AND (n.nspname IS NULL OR n.nspname = ANY(%(s)s))
UNION ALL
SELECT 'schema', n.nspname,
       array_to_string(ARRAY(SELECT x::text FROM unnest(COALESCE(n.nspacl, acldefault('n'::"char", n.nspowner))) x ORDER BY 1), ',')
  FROM pg_namespace n WHERE n.nspname = ANY(%(s)s)
ORDER BY 1, 2
"""

# What the header of 0075 says live will lose, as (kind, object-substring). Everything else must not move.
PREDICTED = {
    ("function", "public.inventory_fact_count_month"),   # step 3: PUBLIC loses EXECUTE
    ("default_acl", "<all schemas> type f"),               # step 4: new functions are not executable by PUBLIC
}


def fingerprint(conn) -> dict[tuple[str, str], str]:
    with conn.cursor() as cur:
        cur.execute(FINGERPRINT_SQL, {"s": list(SCHEMAS)})
        return {(k, o): a for k, o, a in cur.fetchall()}


def live_fingerprint() -> dict[tuple[str, str], str]:
    conn = psycopg2.connect(long_read_db_url())
    try:
        with conn.cursor() as cur:   # transaction-scoped, never a session-level SET (the :6543 pooler leaks it)
            cur.execute("BEGIN")
            cur.execute("SET TRANSACTION READ ONLY")
        fp = fingerprint(conn)
        conn.rollback()
        return fp
    finally:
        conn.close()


def diff(a: dict, b: dict) -> list[tuple[str, str, str, str]]:
    return [(k, o, a.get((k, o), "<absent>"), b.get((k, o), "<absent>"))
            for (k, o) in sorted(set(a) | set(b)) if a.get((k, o)) != b.get((k, o))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", required=True, type=Path)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    live = live_fingerprint()
    print(f"live: {len(live)} privilege rows fingerprinted (READ ONLY)")

    if not local_pg.is_up():
        local_pg.start()
    mismatches = local_pg.restore(args.backup, db=COPY_DB)
    if mismatches:
        print(f"REFUSED: restore row counts differ from the backup manifest: {mismatches}")
        return 3
    copy = psycopg2.connect(local_pg.local_url(db=COPY_DB))
    copy.autocommit = True
    try:
        before = fingerprint(copy)
        fidelity = diff(live, before)
        print(f"\n(1) live vs restored copy, before 0075: {len(fidelity)} differences")
        for k, o, lv, cv in fidelity:
            print(f"   {k} {o}\n      live: {lv}\n      copy: {cv}")

        with copy.cursor() as cur:
            cur.execute(MIGRATION.read_text(encoding="utf-8"))
        after = fingerprint(copy)
        delta = diff(before, after)
        print(f"\n(2) copy before vs after 0075: {len(delta)} changes")
        for k, o, bv, av in delta:
            print(f"   {k} {o}\n      before: {bv}\n      after:  {av}")

        got = {(k, o.split("(")[0] if k == "function" else o) for k, o, _, _ in delta}
        predicted = {(k, o) for k, o in PREDICTED}
        # the default_acl row's object name carries the owner role; compare on the suffix
        got_norm = {(k, o) for k, o in got if k != "default_acl"} | \
                   {("default_acl", "<all schemas> type f") for k, o in got if k == "default_acl" and o.endswith("<all schemas> type f")}
        ok = not fidelity and got_norm == predicted
        print(f"\n(3) only the two predicted changes: {'YES' if got_norm == predicted else 'NO'}; copy matches live before: "
              f"{'YES' if not fidelity else 'NO'}")
        if got_norm != predicted:
            print(f"   unexpected: {sorted(got_norm - predicted)}   missing: {sorted(predicted - got_norm)}")
        return 0 if ok else 1
    finally:
        copy.close()
        if not args.keep:
            print("dropped" if local_pg.drop_database(COPY_DB) else "COULD NOT DROP " + COPY_DB)


if __name__ == "__main__":
    sys.exit(main())
