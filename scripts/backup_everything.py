"""
scripts/backup_everything.py — backs up every schema of ours in the live
database: all table rows AND the structure needed to rebuild the tables.

backup_live_db.py covers `public` only, and its ddl_snapshot.json keeps just
column names/types and the primary key: enough to reload rows into tables
that still exist, not to rebuild them. Views, indexes, foreign keys, check
constraints, defaults, identity columns, comments and permissions were in no
backup. Asked for 2026-09-28 (Audrey): back up everything, including the
ssm_synth_v2 and ssm_pm_cleanup scratch schemas.

Writes:
  backups/full_backup_<timestamp>/
    README.txt               what is here and how to rebuild from it
    data/<schema>/           backup_live_db.py's format, one folder per schema:
                             <table>.parquet + manifest.json + ddl_snapshot.json,
                             except JSON columns are saved as exact JSON text
                             (create_backup's json_as_text - see its comment)
    structure/_database.sql  extensions the schemas use
    structure/<schema>.sql   tables, columns, defaults, identity columns,
                             constraints, indexes, sequences, views, functions,
                             triggers, comments, owners, permissions, RLS

"Every schema of ours" means every schema except Postgres' and Supabase's
own (auth, storage, realtime, vault, ...), which Supabase recreates. The run
still prints row counts for the Supabase tables that would hold app data
(auth.users, storage.objects), so that stays checked rather than assumed.

READ ONLY: every connection is opened with postgresql_readonly, and the
script stops unless the database confirms transaction_read_only = on. So,
unlike backup_live_db.py, it does not restore-test into a scratch schema
(that writes to the live database). It re-opens every file it wrote and
compares it with the live tables instead.

    python -m scripts.backup_everything

Why not pg_dump: it is not installed here (see backup_live_db.py). With the
PostgreSQL 17 client tools installed, `pg_dump --schema-only` is the
standard way to get what structure/ holds.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text

from analytics.config import get_settings, long_read_db_url
from scripts.backup_live_db import BACKUP_ROOT, _list_base_tables, _p, create_backup

# Postgres' and Supabase's own schemas. Every other schema is ours.
MANAGED_SCHEMAS = {
    "information_schema", "auth", "storage", "realtime", "_realtime", "vault", "extensions",
    "graphql", "graphql_public", "pgbouncer", "pgsodium", "pgsodium_masks", "net", "cron",
    "supabase_functions", "supabase_migrations", "_analytics", "pgtle", "topology",
}
# Supabase tables that would hold app data if the app ever used Supabase Auth or Storage.
MANAGED_DATA_TABLES = ("auth.users", "storage.buckets", "storage.objects")
# Supabase's Data API roles. The structure files revoke these (and PUBLIC) before
# re-granting, so a rebuild gets the recorded permissions, not Supabase's defaults.
API_ROLES = ("anon", "authenticated", "service_role")

POLICY_COMMANDS = {"r": "SELECT", "a": "INSERT", "w": "UPDATE", "d": "DELETE", "*": "ALL"}
DEFAULT_ACL_OBJECTS = {"r": "TABLES", "S": "SEQUENCES", "f": "FUNCTIONS", "T": "TYPES"}
ACL_COLUMNS = (
    "CASE WHEN a.grantee = 0 THEN NULL ELSE pg_get_userbyid(a.grantee) END AS grantee, "
    "a.privilege_type, a.is_grantable"
)


def qi(name: str) -> str:
    """Always-quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def lit(value: str) -> str:
    """SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def _readonly_engine():
    engine = create_engine(long_read_db_url()).execution_options(postgresql_readonly=True)
    with engine.connect() as conn:
        if conn.execute(text("SHOW transaction_read_only")).scalar() != "on":
            raise SystemExit("Stopped: could not open a read-only connection, and this script must never write.")
    return engine


def _our_schemas(conn) -> list[str]:
    names = conn.execute(text(
        "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%' ORDER BY nspname"
    )).scalars().all()
    return [n for n in names if n not in MANAGED_SCHEMAS]


def _grants(rows, on: str) -> list[str]:
    """GRANT statements from aclexplode() rows; `on` is e.g. 'TABLE "s"."t"'."""
    privileges: dict[tuple, list[str]] = defaultdict(list)
    for r in rows:
        privileges[(r["grantee"] or "", r["is_grantable"])].append(r["privilege_type"])
    return [
        f"GRANT {', '.join(sorted(privs))} ON {on} TO {qi(grantee) if grantee else 'PUBLIC'}"
        + (" WITH GRANT OPTION;" if grantable else ";")
        for (grantee, grantable), privs in sorted(privileges.items())
    ]


def _header(schema: str | None, ts: str, version: str) -> str:
    what = f'schema "{schema}"' if schema else "database-wide settings"
    rows_at = f" Its rows are in ../data/{schema}/." if schema else ""
    return (
        f"-- Structure of {what}, read from the live database {ts}\n"
        f"-- (PostgreSQL {version}) by scripts/backup_everything.py.{rows_at}\n"
        "--\n"
        "-- For rebuilding into an EMPTY database, e.g. a new Supabase project: run\n"
        "-- _database.sql, then public.sql, then the other schema files, then load\n"
        "-- the rows. Every name is schema-qualified. Nothing here drops or deletes.\n"
        "SET check_function_bodies = false;"
    )


def _database_sql(conn, header: str) -> str:
    out = [header, "\n-- Extensions the schemas may use (a Supabase project already has most of them)."]
    for e in conn.execute(text(
        "SELECT e.extname, n.nspname, e.extversion FROM pg_extension e "
        "JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname <> 'plpgsql' ORDER BY 1"
    )).mappings():
        out.append(f"CREATE EXTENSION IF NOT EXISTS {qi(e['extname'])} WITH SCHEMA {qi(e['nspname'])};"
                   f"  -- version {e['extversion']}")
    return "\n".join(out) + "\n"


def _structure_sql(conn, schema: str, header: str) -> tuple[str, dict, list[str]]:
    """The SQL that recreates one schema, how many objects it wrote, and any
    mismatch against the catalog's own counts. Expects the connection's
    search_path to be empty, so every name the catalog prints is qualified."""

    def q(sql: str, **params):
        return conn.execute(text(sql), params).mappings().all()

    ns = q("SELECT oid, pg_get_userbyid(nspowner) AS owner, obj_description(oid, 'pg_namespace') AS comment "
           "FROM pg_namespace WHERE nspname = :s", s=schema)[0]
    nsp, S = ns["oid"], qi(schema)
    me = conn.execute(text("SELECT current_user")).scalar()
    api_roles = [r for r in API_ROLES if q("SELECT 1 FROM pg_roles WHERE rolname = :r", r=r)]
    revoke_from = ", ".join(["PUBLIC", *(qi(r) for r in api_roles)])
    out = [header]
    counts: dict[str, int] = defaultdict(int)
    problems: list[str] = []

    def section(title: str) -> None:
        out.append(f"\n-- ---- {title} ----")

    def comment(kind: str, target: str, note: str | None) -> None:
        if note:
            out.append(f"COMMENT ON {kind} {target} IS {lit(note)};")
            counts["comments"] += 1

    # -- schema -----------------------------------------------------------------
    section("schema")
    out.append(f"CREATE SCHEMA IF NOT EXISTS {S};")
    out.append(f"ALTER SCHEMA {S} OWNER TO {qi(ns['owner'])};")
    comment("SCHEMA", S, ns["comment"])
    out += _grants(q(f"SELECT {ACL_COLUMNS} FROM pg_namespace n "
                     "CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) a "
                     "WHERE n.oid = :nsp AND a.grantee <> n.nspowner", nsp=nsp), f"SCHEMA {S}")

    # -- enum and domain types --------------------------------------------------
    types = q("""
        SELECT t.typname, t.typtype, pg_get_userbyid(t.typowner) AS owner, t.typnotnull, t.typdefault,
               format_type(t.typbasetype, t.typtypmod) AS base,
               (SELECT string_agg(quote_literal(e.enumlabel), ', ' ORDER BY e.enumsortorder)
                  FROM pg_enum e WHERE e.enumtypid = t.oid) AS labels,
               (SELECT string_agg('CONSTRAINT ' || quote_ident(c.conname) || ' ' || pg_get_constraintdef(c.oid), ' ')
                  FROM pg_constraint c WHERE c.contypid = t.oid) AS checks
        FROM pg_type t WHERE t.typnamespace = :nsp AND t.typtype IN ('e', 'd') ORDER BY t.typname
    """, nsp=nsp)
    if types:
        section("types")
    for t in types:
        name = f"{S}.{qi(t['typname'])}"
        if t["typtype"] == "e":
            out.append(f"CREATE TYPE {name} AS ENUM ({t['labels'] or ''});")
            out.append(f"ALTER TYPE {name} OWNER TO {qi(t['owner'])};")
        else:
            out.append(f"CREATE DOMAIN {name} AS {t['base']}"
                       + (f" DEFAULT {t['typdefault']}" if t["typdefault"] else "")
                       + (" NOT NULL" if t["typnotnull"] else "")
                       + (f" {t['checks']}" if t["checks"] else "") + ";")
            out.append(f"ALTER DOMAIN {name} OWNER TO {qi(t['owner'])};")
        counts["types"] += 1

    # -- functions (before tables: check_function_bodies is off, and column
    # defaults may call them) ---------------------------------------------------
    funcs = q("""
        SELECT p.oid, p.proname, p.prokind, pg_get_functiondef(p.oid) AS def,
               pg_get_userbyid(p.proowner) AS owner, pg_get_function_identity_arguments(p.oid) AS args,
               obj_description(p.oid, 'pg_proc') AS comment
        FROM pg_proc p
        WHERE p.pronamespace = :nsp AND p.prokind IN ('f', 'p', 'w')
          AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass
                          AND d.objid = p.oid AND d.deptype = 'e')
        ORDER BY p.proname, args
    """, nsp=nsp)
    if funcs:
        section("functions")
    for f in funcs:
        kind = "PROCEDURE" if f["prokind"] == "p" else "FUNCTION"
        sig = f"{S}.{qi(f['proname'])}({f['args']})"
        out.append(f["def"].rstrip() + ";")
        out.append(f"ALTER {kind} {sig} OWNER TO {qi(f['owner'])};")
        comment(kind, sig, f["comment"])
        out.append(f"REVOKE ALL ON {kind} {sig} FROM {revoke_from};")
        out += _grants(q(f"SELECT {ACL_COLUMNS} FROM pg_proc p "
                         "CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) a "
                         "WHERE p.oid = :o AND a.grantee <> p.proowner", o=f["oid"]), f"{kind} {sig}")
        counts["functions"] += 1

    # -- sequences --------------------------------------------------------------
    seqs = q("""
        SELECT c.relname, pg_get_userbyid(c.relowner) AS owner, obj_description(c.oid, 'pg_class') AS comment,
               format_type(s.seqtypid, NULL) AS data_type, s.seqstart, s.seqincrement, s.seqmin, s.seqmax,
               s.seqcache, s.seqcycle, pg_sequence_last_value(c.oid) AS last_value,
               d.deptype, tn.nspname AS tbl_schema, t.relname AS tbl, a.attname AS col
        FROM pg_class c
        JOIN pg_sequence s ON s.seqrelid = c.oid
        LEFT JOIN pg_depend d ON d.classid = 'pg_class'::regclass AND d.objid = c.oid
             AND d.refclassid = 'pg_class'::regclass AND d.deptype IN ('a', 'i')
        LEFT JOIN pg_class t ON t.oid = d.refobjid
        LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
        LEFT JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
        WHERE c.relnamespace = :nsp AND c.relkind = 'S'
        ORDER BY c.relname
    """, nsp=nsp)

    def seq_options(r) -> str:
        return (f"START WITH {r['seqstart']} INCREMENT BY {r['seqincrement']} MINVALUE {r['seqmin']} "
                f"MAXVALUE {r['seqmax']} CACHE {r['seqcache']}" + (" CYCLE" if r["seqcycle"] else " NO CYCLE"))

    # Identity columns' sequences are created by their CREATE TABLE; the rest here.
    identity = {(r["tbl"], r["col"]): r for r in seqs if r["deptype"] == "i"}
    standalone = [r for r in seqs if r["deptype"] != "i"]
    if standalone:
        section("sequences")
    for r in standalone:
        name = f"{S}.{qi(r['relname'])}"
        out.append(f"CREATE SEQUENCE {name} AS {r['data_type']} {seq_options(r)};")
        out.append(f"ALTER SEQUENCE {name} OWNER TO {qi(r['owner'])};")
        comment("SEQUENCE", name, r["comment"])

    # -- tables -----------------------------------------------------------------
    tables = q("""
        SELECT c.oid, c.relname, c.relkind, c.relpersistence, c.relispartition,
               array_to_string(c.reloptions, ', ') AS reloptions, c.relrowsecurity, c.relforcerowsecurity,
               pg_get_userbyid(c.relowner) AS owner, obj_description(c.oid, 'pg_class') AS comment,
               EXISTS (SELECT 1 FROM pg_inherits i WHERE i.inhrelid = c.oid) AS has_parent
        FROM pg_class c WHERE c.relnamespace = :nsp AND c.relkind IN ('r', 'p') ORDER BY c.relname
    """, nsp=nsp)
    columns: dict[int, list] = defaultdict(list)
    for c in q("""
        SELECT a.attrelid, a.attname, format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull,
               a.attidentity, a.attgenerated, col_description(a.attrelid, a.attnum) AS comment,
               CASE WHEN a.atthasdef THEN pg_get_expr(ad.adbin, ad.adrelid) END AS default_expr,
               CASE WHEN a.attcollation <> 0 AND a.attcollation <> t.typcollation THEN
                    (SELECT quote_ident(cn.nspname) || '.' || quote_ident(co.collname)
                     FROM pg_collation co JOIN pg_namespace cn ON cn.oid = co.collnamespace
                     WHERE co.oid = a.attcollation) END AS collation
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_type t ON t.oid = a.atttypid
        LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
        WHERE c.relnamespace = :nsp AND c.relkind IN ('r', 'p', 'v', 'm') AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attrelid, a.attnum
    """, nsp=nsp):
        columns[c["attrelid"]].append(c)

    section("tables")
    for t in tables:
        name = f"{S}.{qi(t['relname'])}"
        if t["relkind"] == "p" or t["relispartition"] or t["has_parent"]:
            problems.append(f"{schema}.{t['relname']} is partitioned or inherits another table; "
                            "its CREATE TABLE is written as a plain table - check it by hand")
        lines = []
        for c in columns[t["oid"]]:
            d = f"    {qi(c['attname'])} {c['type']}"
            if c["collation"]:
                d += f" COLLATE {c['collation']}"
            if c["attidentity"]:
                d += " GENERATED ALWAYS AS IDENTITY" if c["attidentity"] == "a" else " GENERATED BY DEFAULT AS IDENTITY"
                seq = identity.get((t["relname"], c["attname"]))
                if seq:
                    d += f" ({seq_options(seq)})"
            elif c["attgenerated"] == "s":
                d += f" GENERATED ALWAYS AS ({c['default_expr']}) STORED"
            elif c["default_expr"] is not None:
                d += f" DEFAULT {c['default_expr']}"
            if c["attnotnull"]:
                d += " NOT NULL"
            lines.append(d)
        unlogged = "UNLOGGED " if t["relpersistence"] == "u" else ""
        options = f" WITH ({t['reloptions']})" if t["reloptions"] else ""
        out.append(f"\nCREATE {unlogged}TABLE {name} (\n" + ",\n".join(lines) + f"\n){options};")
        out.append(f"ALTER TABLE {name} OWNER TO {qi(t['owner'])};")
        comment("TABLE", name, t["comment"])
        for c in columns[t["oid"]]:
            comment("COLUMN", f"{name}.{qi(c['attname'])}", c["comment"])
        counts["tables"] += 1

    owned = [r for r in standalone if r["deptype"] == "a"]
    if owned:
        section("sequence ownership")
    for r in owned:
        out.append(f"ALTER SEQUENCE {S}.{qi(r['relname'])} OWNED BY "
                   f"{qi(r['tbl_schema'])}.{qi(r['tbl'])}.{qi(r['col'])};")

    # -- constraints ------------------------------------------------------------
    cons = q("""
        SELECT c.relname, con.conname, con.contype, pg_get_constraintdef(con.oid) AS def,
               obj_description(con.oid, 'pg_constraint') AS comment
        FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid
        WHERE c.relnamespace = :nsp AND con.contype IN ('p', 'u', 'x', 'c', 'f') AND con.conislocal
        ORDER BY c.relname, position(con.contype::text IN 'puxcf'), con.conname
    """, nsp=nsp)

    def add_constraints(rows) -> None:
        for r in rows:
            table = f"{S}.{qi(r['relname'])}"
            out.append(f"ALTER TABLE ONLY {table} ADD CONSTRAINT {qi(r['conname'])} {r['def']};")
            comment("CONSTRAINT", f"{qi(r['conname'])} ON {table}", r["comment"])

    section("primary keys, unique and check constraints")
    add_constraints([r for r in cons if r["contype"] != "f"])
    counts["constraints"] = sum(r["contype"] != "f" for r in cons)
    counts["constraint_indexes"] = sum(r["contype"] in ("p", "u", "x") for r in cons)

    # -- views, in dependency order ---------------------------------------------
    views = q("""
        SELECT c.oid, c.relname, c.relkind, pg_get_viewdef(c.oid) AS def,
               array_to_string(c.reloptions, ', ') AS reloptions,
               pg_get_userbyid(c.relowner) AS owner, obj_description(c.oid, 'pg_class') AS comment
        FROM pg_class c WHERE c.relnamespace = :nsp AND c.relkind IN ('v', 'm') ORDER BY c.relname
    """, nsp=nsp)
    view_deps = q("""
        SELECT DISTINCT r.ev_class AS view_oid, d.refobjid AS dep_oid
        FROM pg_rewrite r
        JOIN pg_class v ON v.oid = r.ev_class
        JOIN pg_depend d ON d.classid = 'pg_rewrite'::regclass AND d.objid = r.oid
                         AND d.refclassid = 'pg_class'::regclass
        WHERE v.relnamespace = :nsp AND d.refobjid <> r.ev_class
    """, nsp=nsp)
    by_oid = {v["oid"]: v for v in views}
    needs: dict[int, set] = {o: set() for o in by_oid}
    for d in view_deps:
        if d["view_oid"] in needs and d["dep_oid"] in by_oid:
            needs[d["view_oid"]].add(d["dep_oid"])
    ordered, done = [], set()
    while len(ordered) < len(by_oid):  # a view that reads another view comes after it
        ready = [o for o in by_oid if o not in done and needs[o] <= done] or [o for o in by_oid if o not in done]
        for o in sorted(ready, key=lambda o: by_oid[o]["relname"]):
            ordered.append(by_oid[o])
            done.add(o)
    if ordered:
        section("views")
    for v in ordered:
        name = f"{S}.{qi(v['relname'])}"
        body = v["def"].strip().rstrip(";")
        options = f" WITH ({v['reloptions']})" if v["reloptions"] else ""
        kind = "VIEW" if v["relkind"] == "v" else "MATERIALIZED VIEW"
        if kind == "VIEW":
            out.append(f"\nCREATE OR REPLACE VIEW {name}{options} AS\n{body};")
        else:
            out.append(f"\nCREATE MATERIALIZED VIEW {name}{options} AS\n{body}\nWITH NO DATA;")
        out.append(f"ALTER {kind} {name} OWNER TO {qi(v['owner'])};")
        comment(kind, name, v["comment"])
        for c in columns[v["oid"]]:
            comment("COLUMN", f"{name}.{qi(c['attname'])}", c["comment"])
        counts["views"] += 1

    # -- indexes not already created by a primary key / unique constraint --------
    idx = q("""
        SELECT ic.relname, pg_get_indexdef(i.indexrelid) AS def, obj_description(ic.oid, 'pg_class') AS comment
        FROM pg_index i
        JOIN pg_class ic ON ic.oid = i.indexrelid
        JOIN pg_class c ON c.oid = i.indrelid
        WHERE c.relnamespace = :nsp
          AND NOT EXISTS (SELECT 1 FROM pg_constraint con
                          WHERE con.conindid = i.indexrelid AND con.contype IN ('p', 'u', 'x'))
        ORDER BY c.relname, ic.relname
    """, nsp=nsp)
    if idx:
        section("indexes")
    for r in idx:
        out.append(r["def"] + ";")
        comment("INDEX", f"{S}.{qi(r['relname'])}", r["comment"])
    counts["indexes"] = len(idx)

    # -- triggers ---------------------------------------------------------------
    trigs = q("""
        SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid) AS def
        FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
        WHERE c.relnamespace = :nsp AND NOT t.tgisinternal ORDER BY c.relname, t.tgname
    """, nsp=nsp)
    if trigs:
        section("triggers")
    out += [r["def"] + ";" for r in trigs]
    counts["triggers"] = len(trigs)

    # -- foreign keys (last, once every table and unique index exists) ----------
    fks = [r for r in cons if r["contype"] == "f"]
    if fks:
        section("foreign keys")
    add_constraints(fks)
    counts["foreign_keys"] = len(fks)

    # -- row-level security -----------------------------------------------------
    rls = [t for t in tables if t["relrowsecurity"] or t["relforcerowsecurity"]]
    pols = q("""
        SELECT c.relname, po.polname, po.polpermissive, po.polcmd,
               (SELECT string_agg(CASE WHEN r = 0 THEN 'PUBLIC' ELSE quote_ident(pg_get_userbyid(r)) END, ', ')
                  FROM unnest(po.polroles) r) AS roles,
               pg_get_expr(po.polqual, po.polrelid) AS using_expr,
               pg_get_expr(po.polwithcheck, po.polrelid) AS check_expr
        FROM pg_policy po JOIN pg_class c ON c.oid = po.polrelid
        WHERE c.relnamespace = :nsp ORDER BY c.relname, po.polname
    """, nsp=nsp)
    section("row-level security")
    out.append(f"-- {len(rls)} of {len(tables)} tables have row-level security on; {len(pols)} policies.")
    for t in rls:
        name = f"{S}.{qi(t['relname'])}"
        if t["relrowsecurity"]:
            out.append(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY;")
        if t["relforcerowsecurity"]:
            out.append(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY;")
    for p in pols:
        stmt = (f"CREATE POLICY {qi(p['polname'])} ON {S}.{qi(p['relname'])} "
                f"AS {'PERMISSIVE' if p['polpermissive'] else 'RESTRICTIVE'} "
                f"FOR {POLICY_COMMANDS[p['polcmd']]} TO {p['roles']}")
        if p["using_expr"]:
            stmt += f" USING ({p['using_expr']})"
        if p["check_expr"]:
            stmt += f" WITH CHECK ({p['check_expr']})"
        out.append(stmt + ";")
    counts["policies"] = len(pols)

    # -- permissions ------------------------------------------------------------
    rel_acl: dict[str, list] = defaultdict(list)
    for r in q(f"""
        SELECT c.relname, {ACL_COLUMNS}
        FROM pg_class c
        CROSS JOIN LATERAL aclexplode(COALESCE(
            c.relacl, acldefault(CASE WHEN c.relkind = 'S' THEN 's' ELSE 'r' END::"char", c.relowner))) a
        WHERE c.relnamespace = :nsp AND c.relkind IN ('r', 'p', 'v', 'm', 'S') AND a.grantee <> c.relowner
    """, nsp=nsp):
        rel_acl[r["relname"]].append(r)
    section("permissions")
    for keyword, names in (
        ("TABLE", [t["relname"] for t in tables] + [v["relname"] for v in views]),
        ("SEQUENCE", [r["relname"] for r in seqs]),
    ):
        for n in names:
            on = f"{keyword} {S}.{qi(n)}"
            out.append(f"REVOKE ALL ON {on} FROM {revoke_from};")
            out += _grants(rel_acl.get(n, []), on)
    default_acl: dict[tuple, list] = defaultdict(list)
    for r in q(f"""
        SELECT pg_get_userbyid(d.defaclrole) AS for_role, d.defaclobjtype AS objtype, {ACL_COLUMNS}
        FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a
        WHERE d.defaclnamespace = :nsp
    """, nsp=nsp):
        default_acl[(r["for_role"], r["objtype"])].append(r)
    if default_acl:
        out.append("\n-- What new objects in this schema are granted automatically. Lines for a role\n"
                   "-- other than the one that took this backup are commented out: only that role\n"
                   "-- (Supabase's own, for supabase_admin) can set them, and Supabase does.")
    for (for_role, objtype), rows in sorted(default_acl.items()):
        for g in _grants(rows, DEFAULT_ACL_OBJECTS.get(objtype, objtype)):
            line = f"ALTER DEFAULT PRIVILEGES FOR ROLE {qi(for_role)} IN SCHEMA {S} {g}"
            out.append(line if for_role == me else f"-- {line}")

    # -- sequence positions, so new rows don't reuse an existing id --------------
    if seqs:
        section("sequence positions")
    for r in seqs:
        if r["deptype"] == "i":
            target = f"pg_get_serial_sequence({lit(qi(r['tbl_schema']) + '.' + qi(r['tbl']))}, {lit(r['col'])})"
        else:
            target = lit(f"{S}.{qi(r['relname'])}")
        value, called = (r["last_value"], "true") if r["last_value"] is not None else (r["seqstart"], "false")
        out.append(f"SELECT setval({target}, {value}, {called});")
    counts["sequences"] = len(seqs)

    # -- cross-check against the catalog's own counts ---------------------------
    expect = q("""
        SELECT count(*) FILTER (WHERE relkind IN ('r', 'p')) AS tables,
               count(*) FILTER (WHERE relkind IN ('v', 'm')) AS views,
               count(*) FILTER (WHERE relkind IN ('i', 'I')) AS index_relations,
               count(*) FILTER (WHERE relkind = 'S') AS sequences
        FROM pg_class WHERE relnamespace = :nsp
    """, nsp=nsp)[0]
    for key, got in (
        ("tables", counts["tables"]),
        ("views", counts["views"]),
        ("sequences", counts["sequences"]),
        ("index_relations", counts["indexes"] + counts["constraint_indexes"]),
    ):
        if got != expect[key]:
            problems.append(f"{schema}: structure file has {got} {key}, the database has {expect[key]}")
    return "\n".join(out) + "\n", counts, problems


def _not_backed_up(live_tables: list[str], manifest: dict) -> list[str]:
    """Live tables with neither a file nor a recorded reason for leaving them
    out (manifest "excluded": the credential tables, see backup_live_db)."""
    left_out = manifest.get("excluded", {}).get("tables", {})
    return sorted(set(live_tables) - set(manifest["tables"]) - set(left_out))


def _check_data(engine, root: Path, schemas: list[str]) -> tuple[list[str], list[str]]:
    """Re-opens every file written and compares it with its manifest and with
    the live table. Returns (problems, tables that changed since the backup)."""
    problems, changed = [], []
    with engine.connect() as conn:
        for schema in schemas:
            folder = root / "data" / schema
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            tables = manifest["tables"]
            ddl = json.loads((folder / "ddl_snapshot.json").read_text(encoding="utf-8"))
            missing = _not_backed_up(_list_base_tables(conn, schema), manifest)
            if missing:
                problems.append(f"{schema}: tables not in the backup: {', '.join(missing)}")
            for t, info in sorted(tables.items()):
                path = folder / info["file"]
                try:
                    rows = pq.ParquetFile(path).metadata.num_rows
                except Exception as exc:
                    problems.append(f"{schema}.{t}: file unreadable ({exc})")
                    continue
                if rows != info["row_count"]:
                    problems.append(f"{schema}.{t}: file has {rows} rows, manifest says {info['row_count']}")
                col = info["checksum_column"]
                if col:
                    total = float(pd.to_numeric(pd.read_parquet(path, columns=[col])[col], errors="coerce").sum())
                    if info["checksum_value"] is None or not math.isclose(
                        total, info["checksum_value"], rel_tol=1e-9, abs_tol=0.01
                    ):
                        problems.append(f"{schema}.{t}: {col} totals {total} in the file, "
                                        f"{info['checksum_value']} in the manifest")
                json_cols = [c["name"] for c in ddl[t]["columns"] if c["type"].upper() in ("JSON", "JSONB")]
                if json_cols and rows:  # an empty table's file has no columns at all
                    stored = pd.read_parquet(path, columns=json_cols)
                    for c in json_cols:
                        bad = sum(not _is_json_text(v) for v in stored[c].dropna())
                        if bad:
                            problems.append(f"{schema}.{t}.{c}: {bad} values are not valid JSON text")
                live = conn.execute(text(f"SELECT count(*) FROM {qi(schema)}.{qi(t)}")).scalar()
                if live != info["row_count"]:
                    changed.append(f"{schema}.{t}: {info['row_count']} rows backed up, {live} live now")
            _p(f"  {schema}: {len(tables)} tables, {sum(i['row_count'] for i in tables.values()):,} rows - checked")
    return problems, changed


def _is_json_text(value) -> bool:
    try:
        json.loads(value)
        return True
    except (TypeError, ValueError):
        return False


def _supabase_tables(engine) -> list[str]:
    lines = []
    for t in MANAGED_DATA_TABLES:
        with engine.connect() as conn:
            try:
                n = conn.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                lines.append(f"{t}: {n} rows" + ("" if n == 0 else "   <- has data, NOT in this backup"))
            except Exception as exc:
                lines.append(f"{t}: could not count ({type(exc).__name__})")
    return lines


def _readme(ts: str, version: str, summary: list[str], supabase: list[str]) -> str:
    return "\n".join([
        "FULL DATABASE BACKUP - SSM Decision Support Dashboard",
        f"Taken {ts} (UTC) from PostgreSQL {version}, read-only, by scripts/backup_everything.py.",
        "",
        "WHAT IS HERE",
        "  data/<schema>/           every row of every table: one .parquet file per table,",
        "                           manifest.json (row count and a checksum per table),",
        "                           ddl_snapshot.json (column names/types, primary key).",
        "                           JSON columns hold each value's exact JSON text.",
        "  structure/<schema>.sql   the SQL that recreates the schema: tables, columns, defaults,",
        "                           identity columns, primary/unique/check/foreign keys, indexes,",
        "                           views, sequences, comments, owners, permissions, row-level security",
        "  structure/_database.sql  extensions the schemas use",
        "",
        "SCHEMAS",
        *(f"  {line}" for line in summary),
        "",
        "NOT INCLUDED",
        "  Supabase's own schemas (auth, storage, realtime, vault, ...). Supabase recreates",
        "  them, and the dashboard keeps no data there. At backup time:",
        *(f"    {line}" for line in supabase),
        "  Credentials: users.password_hash and the auth_token table (one-time link hashes).",
        "  Each manifest.json lists them under \"excluded\". After a rebuild no account has a",
        "  password, and the live server has no email set up, so no link is emailed and",
        "  \"Forgot password?\" cannot help. To get everyone back in:",
        "    1. Create one admin under a NEW email: python -m backend.scripts.seed_admin",
        "       (it refuses an email that already exists).",
        "    2. Signed in as that admin, open User Management and generate a reset link for",
        "       each person. The page shows the link; send it to them by hand.",
        "",
        "KEEP THIS FOLDER PRIVATE",
        "  It holds SSM client data and the dashboard users' names and emails (no password",
        "  hashes). git ignores backups/, so it is never committed. Keep a second copy",
        "  somewhere safe that is not this laptop, e.g. an encrypted USB drive.",
        "",
        "REBUILDING FROM THIS BACKUP (into an empty database, e.g. a new Supabase project)",
        "  1. In the Supabase SQL Editor run structure/_database.sql, then structure/public.sql,",
        "     then the other structure/*.sql files.",
        "  2. Load each data/<schema>/<table>.parquet file into its table.",
        "     scripts/backup_live_db.py's verify_restore() shows how these files load back",
        "     (identity columns, JSON columns, dimension tables before fact tables).",
        "",
    ])


def main() -> int:
    engine = _readonly_engine()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = BACKUP_ROOT / f"full_backup_{ts}"
    (root / "structure").mkdir(parents=True)

    with engine.connect() as conn:
        schemas = _our_schemas(conn)
        version = conn.execute(text("SHOW server_version")).scalar()
    _p(f"Backing up {', '.join(schemas)} from PostgreSQL {version} (read-only)\n-> {root}\n")

    for schema in schemas:
        create_backup(engine, root / "data" / schema, schema=schema, json_as_text=True)
        _p("")

    _p("Writing the table structure ...")
    problems: list[str] = []
    structure: dict[str, dict] = {}
    with engine.connect() as conn:
        # Empty search_path: the catalog prints every name schema-qualified,
        # the same way pg_dump reads definitions.
        conn.execute(text("SELECT pg_catalog.set_config('search_path', '', true)"))
        (root / "structure" / "_database.sql").write_text(
            _database_sql(conn, _header(None, ts, version)), encoding="utf-8"
        )
        for schema in schemas:
            sql, counts, errs = _structure_sql(conn, schema, _header(schema, ts, version))
            (root / "structure" / f"{schema}.sql").write_text(sql, encoding="utf-8")
            structure[schema] = counts
            problems += errs
            _p(f"  {schema}.sql: {counts['tables']} tables, {counts['views']} views, "
               f"{counts['indexes'] + counts['constraint_indexes']} indexes, "
               f"{counts['constraints']} keys/checks, {counts['foreign_keys']} foreign keys, "
               f"{counts['sequences']} sequences, {counts['functions']} functions, "
               f"{counts['triggers']} triggers, {counts['policies']} policies, {counts['comments']} comments")

    _p("\nChecking every file against the live database ...")
    data_problems, changed = _check_data(engine, root, schemas)
    problems += data_problems
    supabase = _supabase_tables(engine)

    summary = []
    for schema in schemas:
        tables = json.loads((root / "data" / schema / "manifest.json").read_text(encoding="utf-8"))["tables"]
        summary.append(f"{schema:<22} {len(tables):>3} tables, {sum(i['row_count'] for i in tables.values()):>9,} rows, "
                       f"{structure[schema]['views']} views, "
                       f"{structure[schema]['indexes'] + structure[schema]['constraint_indexes']} indexes")
    (root / "README.txt").write_text(_readme(ts, version, summary, supabase), encoding="utf-8")

    _p("\nSupabase's own tables (not in this backup):")
    for line in supabase:
        _p(f"  {line}")
    if changed:
        _p("\nChanged in the live database while the backup ran (re-run for an exact copy):")
        for line in changed:
            _p(f"  {line}")
    _p(f"\nBackup folder: {root}")
    if problems:
        _p("RESULT: FAIL")
        for p in problems:
            _p(f"  - {p}")
        return 1
    _p("RESULT: PASS - every table's rows and structure are backed up, and every file matches its manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
