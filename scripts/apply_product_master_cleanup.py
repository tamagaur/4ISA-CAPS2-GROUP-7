"""scripts/apply_product_master_cleanup.py - the product-master queue (reports/PROJECT_STATE_2026-09.md 17.3), in the
planned order, through apply_dm_fixes_to_public's batch runner (scratch rehearsal with the rollback proven, backup
in a timed child process, public equal to the rehearsal both directions, ledger run_id prefix 'pm_cleanup_').

Plan step 1 (quarantine the 7 banner rows) is SKIPPED (Yuan, 2026-09-29): the 14 banner source rows are already in
etl_quarantine (keys 7553-7566, rule exclude_footer_rows[inventory_sign_off]), the loader's Transform drops them, and
the 7 banner products were removed by the synth v2 cutover's batch 7 on 2026-09-28.

  1  plan step 2  delete the Del Monte category rows nothing references                 expect 93 rows, 181 -> 88
  2  plan step 3  migration 0029: supersedes_product_key (nullable, FK, NOT populated)   expect 0 rows changed
  3  plan step 4  migration 0030: sku_code format CHECKs (last)                          expect 0 rows changed

  python -m scripts.apply_product_master_cleanup --baseline public
  python -m scripts.apply_product_master_cleanup --rehearse ssm_pm_rehearsal --batch N
  python -m scripts.apply_product_master_cleanup --target public --against ssm_pm_rehearsal --batch N --i-have-approval
  python -m scripts.apply_product_master_cleanup --verify public --baseline-file backups/<file>.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import psycopg2

from scripts.apply_dm_fixes_to_public import (REPO, _rows, apply_migration, build_scratch, connect, fingerprint, rollback,
                                              run_batch)
from scripts.apply_synth_v2_cutover import MODEL_TABLES
from scripts.apply_synth_v2_cutover import state as cutover_state
from scripts.apply_synth_v2_cutover import verify as cutover_verify
from scripts.apply_synth_v2_to_public import columns, one

PREFIX = "pm_cleanup_"
# every table with a foreign key to product_dimension (pg_constraint, 2026-09-29)
PRODUCT_FK_TABLES = ["inventory_fact", "sellout_fact", "unilever_sku_demand_fact", "abc_classification", "forecast_result",
                     "lp_recommendation", "sku_traits", "sku_segment"]
UNREFERENCED = " AND ".join(f"NOT EXISTS (SELECT 1 FROM {{T}}.{t} x WHERE x.product_key = p.product_key)" for t in PRODUCT_FK_TABLES)
ORPHAN_CATEGORIES = f"SELECT p.product_key FROM {{T}}.product_dimension p WHERE p.principal = 'delmonte' AND p.grain = 'category' AND {UNREFERENCED}"
MIGRATION_0029 = "0029_product_dimension_supersedes_product_key.sql"
MIGRATION_0030 = "0030_product_dimension_sku_code_format.sql"


def orphan_categories(cur, T):
    for t in PRODUCT_FK_TABLES:
        if not one(cur, "SELECT to_regclass(%s) IS NOT NULL", (f"{T}.{t}",)):
            raise RuntimeError(f"{T}.{t} is missing - the orphan check must see every table that references product_dimension")
    return [r[0] for r in _rows(cur, ORPHAN_CATEGORIES.format(T=T) + " ORDER BY p.product_key")]


def b_orphan_categories(cur, T, check, log):
    keys = orphan_categories(cur, T)
    check("Del Monte category rows nothing references", len(keys), 93)
    cur.execute(f"DELETE FROM {T}.product_dimension WHERE product_key = ANY(%s) RETURNING product_key", (keys,))
    gone = [r[0] for r in cur.fetchall()]
    log["deleted"]["product_dimension"] = {"restore_from_backup": "TRUE", "key": "product_key", "keys": gone, "rows": len(gone)}
    check("category rows deleted", len(gone), 93)
    check("Del Monte category rows left", one(cur, f"SELECT COUNT(*) FROM {T}.product_dimension WHERE principal = 'delmonte' AND grain = 'category'"), 88)
    check("category rows left that nothing references", len(orphan_categories(cur, T)), 0)
    check("rows deleted that were not Del Monte category rows",
          one(cur, f"SELECT COUNT(*) FROM {T}.product_dimension WHERE product_key = ANY(%s)", (gone,)), 0)
    return 93, len(gone)


def _schema_only(migration: str, probe):
    def fn(cur, T, check, log):
        cols = columns(cur, T, "product_dimension")
        before = fingerprint(cur, T, "product_dimension", "TRUE", cols)
        apply_migration(cur, T, migration, log)
        check(f"{migration} recorded", one(cur, f"SELECT COUNT(*) FROM {T}.schema_migrations WHERE filename = %s", (migration,)), 1)
        check("product_dimension rows unchanged (fingerprint over the columns before the migration)",
              fingerprint(cur, T, "product_dimension", "TRUE", cols), before)
        probe(cur, T, check)
        return 0, 0
    return fn


def probe_supersedes(cur, T, check):
    check("supersedes_product_key: type, nullable",
          _rows(cur, """SELECT data_type, is_nullable FROM information_schema.columns WHERE table_schema = %s
                        AND table_name = 'product_dimension' AND column_name = 'supersedes_product_key'""", (T,)), [("bigint", "YES")])
    check("supersedes_product_key: FK to product_dimension(product_key)",
          _rows(cur, """SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = %s::regclass
                        AND conname = 'product_dimension_supersedes_product_key_fkey'""", (f"{T}.product_dimension",)),
          [("FOREIGN KEY (supersedes_product_key) REFERENCES " + ("product_dimension(product_key)" if T == "public"
                                                                  else f"{T}.product_dimension(product_key)"),)])
    check("supersedes_product_key: populated rows (must stay empty)",
          one(cur, f"SELECT COUNT(*) FROM {T}.product_dimension WHERE supersedes_product_key IS NOT NULL"), 0)


def probe_sku_checks(cur, T, check):
    check("sku_code CHECKs present and validated",
          _rows(cur, """SELECT conname, convalidated FROM pg_constraint WHERE conrelid = %s::regclass AND conname LIKE %s ORDER BY 1""",
                (f"{T}.product_dimension", "%sku_code_format")),
          [("product_dimension_delmonte_sku_code_format", True), ("product_dimension_unilever_sku_code_format", True)])
    # each CHECK rejects a bad code (explicit key, so no sequence value is used; rolled back to a savepoint)
    for principal, code, name in (("unilever", "1234567", "product_dimension_unilever_sku_code_format"),
                                  ("delmonte", "PROMO PACK", "product_dimension_delmonte_sku_code_format"),
                                  ("delmonte", "KIKKOMAN", "product_dimension_delmonte_sku_code_format")):
        cur.execute("SAVEPOINT probe")
        try:
            cur.execute(f"""INSERT INTO {T}.product_dimension (product_key, principal, grain, sku_code, status)
                            OVERRIDING SYSTEM VALUE VALUES (-1, %s, 'sku', %s, 'ACTIVE')""", (principal, code))
            got = "accepted"
        except psycopg2.errors.CheckViolation as exc:
            got = exc.diag.constraint_name
        cur.execute("ROLLBACK TO SAVEPOINT probe")
        check(f"{principal} code {code!r} rejected by", got, name)


BATCHES = {
    1: ("delete the Del Monte category rows nothing references (plan step 2)", ["product_dimension"], b_orphan_categories),
    2: ("migration 0029: supersedes_product_key, not populated (plan step 3)", ["product_dimension"], _schema_only(MIGRATION_0029, probe_supersedes)),
    3: ("migration 0030: sku_code format CHECKs (plan step 4)", ["product_dimension"], _schema_only(MIGRATION_0030, probe_sku_checks)),
}

PRODUCT_DIMS_ITEM = "dims: product_dimension kept"  # cutover_verify's product item; replaced by the check below


def baseline(cur, T):
    cols = columns(cur, T, "product_dimension")
    orphans = orphan_categories(cur, T)
    return {"cutover_state": cutover_state(cur, T), "product_columns": cols, "orphans": orphans,
            "product_kept": fingerprint(cur, T, "product_dimension", f"NOT (product_key = ANY('{{{','.join(map(str, orphans))}}}'::bigint[]))", cols)}


def verify(cur, T, base):
    res = [r for r in cutover_verify(cur, T, base["cutover_state"]) if not r[0].startswith(PRODUCT_DIMS_ITEM)]
    orphans = "'{" + ",".join(map(str, base["orphans"])) + "}'::bigint[]"
    res.append(("product_dimension rows other than the 93 unchanged", fingerprint(cur, T, "product_dimension", f"NOT (product_key = ANY({orphans}))",
                                                                              base["product_columns"]), base["product_kept"]))
    res.append(("the 93 category rows gone", one(cur, f"SELECT COUNT(*) FROM {T}.product_dimension WHERE product_key = ANY({orphans})"), 0))
    res.append(("supersedes_product_key populated rows", one(cur, f"SELECT COUNT(*) FROM {T}.product_dimension WHERE supersedes_product_key IS NOT NULL"), 0))
    res.append(("sku_code CHECKs validated", one(cur, """SELECT COUNT(*) FROM pg_constraint WHERE conrelid = %s::regclass
                                                        AND conname LIKE %s AND convalidated""", (f"{T}.product_dimension", "%sku_code_format")), 2))
    return res


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target"); p.add_argument("--rehearse"); p.add_argument("--against"); p.add_argument("--batch", type=int)
    p.add_argument("--baseline", metavar="SCHEMA"); p.add_argument("--verify", metavar="SCHEMA"); p.add_argument("--baseline-file")
    p.add_argument("--rollback"); p.add_argument("--i-have-approval", action="store_true")
    args = p.parse_args()
    conn = connect(); cur = conn.cursor()
    try:
        if args.baseline:
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out = REPO / "backups" / f"pm_cleanup_baseline_{args.baseline}_{ts}.json"
            out.write_text(json.dumps(baseline(cur, args.baseline), indent=1, default=str), encoding="utf-8")
            conn.rollback(); print(f"baseline of {args.baseline} -> {out.relative_to(REPO).as_posix()}")
            return 0
        if args.verify:
            failed = 0
            for name, got, want in verify(cur, args.verify, json.loads(Path(args.baseline_file).read_text(encoding="utf-8"))):
                ok = json.dumps(got, default=str) == json.dumps(want, default=str)
                failed += not ok
                if not ok or name.startswith(("models", "product", "the 93", "supersedes", "sku_code")):
                    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f" (expected {want})"))
            print(f"verify {args.verify}: {'ALL PASS' if not failed else f'{failed} FAILED'}")
            conn.rollback()
            return 1 if failed else 0
        if args.rollback:
            if json.loads((Path(args.rollback) / "manifest.json").read_text(encoding="utf-8"))["target"] == "public" and not args.i_have_approval:
                sys.exit("refusing: a rollback on public needs --i-have-approval")
            return rollback(conn, cur, Path(args.rollback))
        if args.batch not in BATCHES:
            p.error(f"--batch must be one of {sorted(BATCHES)}")
        if args.rehearse:
            if args.rehearse in ("public", "ssm_pm_cleanup"):
                p.error("--rehearse needs its own new scratch schema")
            if not one(cur, "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s", (args.rehearse,)):
                build_scratch(cur, args.rehearse)
                for t in MODEL_TABLES:  # every product_dimension FK table must be present for the orphan check
                    cur.execute(f"CREATE TABLE {args.rehearse}.{t} (LIKE public.{t} INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)")
                    cur.execute(f"INSERT INTO {args.rehearse}.{t} SELECT * FROM public.{t}")
                conn.commit()
                print(f"scratch schema {args.rehearse}: built from public")
            return run_batch(conn, cur, args.rehearse, args.batch, True, None, BATCHES, PREFIX)
        if args.target != "public" or not args.against or not args.i_have_approval:
            p.error("--target public needs --against SCHEMA and --i-have-approval")
        return run_batch(conn, cur, "public", args.batch, False, args.against, BATCHES, PREFIX)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
