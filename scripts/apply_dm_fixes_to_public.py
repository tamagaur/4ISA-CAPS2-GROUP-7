"""scripts/apply_dm_fixes_to_public.py - the Del Monte data fixes of 2026-09-28, batch by batch. Same pattern as
scripts/apply_real_recovery_to_public.py (whose helpers it reuses): expected counts stated in code, scratch first,
backup + checksum, apply, verify both directions, ledger entry, rollback proven.

Batches (each its own transaction, recorded in <target>.etl_cutover_ledger under a run_id starting 'dm_fixes_'):
  1  etl_quarantine   the 37 rows of the byte-identical April-2023 sales-return copy       expect +37, 0 fact changes
The rows each batch writes come from the same code the canonical loader runs (scripts/run_canonical_load.py), so a
scratch rebuild of the loader reproduces them.

Per batch:
  --rehearse SCHEMA  a scratch copy of the live tables (built once from public, server-side) -> backup of the
                     batch's tables -> apply + checks -> COMMIT -> undo from the change log -> every backed-up table's
                     md5 and identity sequence equal the backup's (proves the apply touched nothing outside its change
                     log) -> apply again + checks -> COMMIT -> ledger row.
  --target public    refused unless the rehearsal ledger has the batch done. Backup of the batch's tables; their md5
                     must equal the rehearsal's pre-batch backup (public and scratch start from the same rows); apply +
                     checks; the batch's tables equal the rehearsal's both directions (EXCEPT ALL on every column
                     except the table's own identity key and load timestamps); ledger row; COMMIT.
  --rollback DIR     undo one batch from the change log in its backup dir, then re-verify md5 against that backup.
Every run also fingerprints every fact, dimension and model table the batch does not write to, before and after.

CONNECTION ROUTE: the session pooler (the SUPABASE_DB_URL host on port 5432, session mode). The direct host is not
reachable from this machine and the transaction pooler (6543) is never used - apply_real_recovery_to_public.py:29-40.

  python -m scripts.apply_dm_fixes_to_public --rehearse ssm_dm_fixes --batch 1
  python -m scripts.apply_dm_fixes_to_public --target public --against ssm_dm_fixes --batch 1 --i-have-approval
  python -m scripts.apply_dm_fixes_to_public --rollback backups/dm_fixes_<ts>/b1 --i-have-approval
  python -m scripts.apply_dm_fixes_to_public --status --target public
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

import psycopg2
from dotenv import dotenv_values

from scripts.apply_real_recovery_to_public import (LEDGER, LOAD_TIME, ensure_ledger, export_csv, identity_state,
                                                   ledger_rows, reset_sequences, verify_against_backup)
from scripts.apply_synth_v2_to_public import DIMENSIONS, FACTS, REAL_VIEWS, columns, one

REPO = Path(__file__).resolve().parent.parent
RUN_PREFIX = "dm_fixes_"
# copied into the scratch schema: everything a batch writes to or reads from
SCRATCH_TABLES = list(FACTS) + list(DIMENSIONS) + ["etl_quarantine", "schema_migrations", "date_dimension"]
# fingerprinted before and after every batch unless the batch writes to them; ABC read per method, never as a union
ISOLATION = ([(t, "TRUE") for t in list(FACTS) + list(DIMENSIONS) + ["etl_quarantine"]]
             + [("forecast_result", "TRUE"), ("sku_segment", "TRUE"), ("sku_traits", "TRUE"), ("lp_recommendation", "TRUE"),
                ("abc_classification", "method = 'single'"), ("abc_classification", "method IS DISTINCT FROM 'single'")])
IDENT = {**{t: k for t, (k, _) in FACTS.items()}, **{d: k for d, (k, _) in DIMENSIONS.items()}, "etl_quarantine": "quarantine_key"}
SKIP_COMPARE = LOAD_TIME | {"quarantined_at"}


def connect():
    env = dotenv_values(REPO / ".env")
    dsn = env["SUPABASE_DB_URL"].replace(":6543/", ":5432/")
    if ":5432/" not in dsn:
        sys.exit("refusing: could not derive the session-pooler URL (port 5432) from SUPABASE_DB_URL")
    conn = psycopg2.connect(dsn, connect_timeout=30)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET statement_timeout = 0")
    cur.execute("SET idle_in_transaction_session_timeout = 0")
    cur.execute("SET lock_timeout = '30s'")
    conn.commit()
    return conn


def pk_of(cur, T: str, t: str) -> str:
    return one(cur, f"""SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                        WHERE i.indrelid = '{T}.{t}'::regclass AND i.indisprimary""")


def fingerprint(cur, T: str, t: str, where: str) -> list:
    pk = pk_of(cur, T, t)
    cur.execute(f"SELECT COUNT(*), md5(COALESCE(string_agg(md5(x::text), '' ORDER BY x.{pk}), '')) FROM {T}.{t} x WHERE {where}")
    return list(cur.fetchone())


def isolation(cur, T: str, writes: list[str]) -> dict:
    return {f"{t}|{w}": fingerprint(cur, T, t, w) for t, w in ISOLATION
            if t not in writes and one(cur, "SELECT to_regclass(%s) IS NOT NULL", (f"{T}.{t}",))}


def build_scratch(cur, R: str) -> None:
    """Server-side copy of SCRATCH_TABLES, identity sequences mirrored to public's positions (LIKE ... INCLUDING
    IDENTITY starts at 1 and OVERRIDING SYSTEM VALUE never advances it - the 2026-09-15 incident class)."""
    if one(cur, "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s", (R,)):
        raise RuntimeError(f"schema {R} already exists - pick a new name (this script never drops a schema)")
    cur.execute(f"CREATE SCHEMA {R}")
    for t in SCRATCH_TABLES:
        cur.execute(f"CREATE TABLE {R}.{t} (LIKE public.{t} INCLUDING DEFAULTS INCLUDING IDENTITY INCLUDING INDEXES INCLUDING CONSTRAINTS)")
        cur.execute(f"INSERT INTO {R}.{t} OVERRIDING SYSTEM VALUE SELECT * FROM public.{t}")
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s AND is_identity = 'YES'", (R, t))
        for (col,) in cur.fetchall():
            cur.execute(f"SELECT last_value, is_called FROM {one(cur, 'SELECT pg_get_serial_sequence(%s, %s)', (f'public.{t}', col))}")
            last_value, is_called = cur.fetchone()
            cur.execute("SELECT setval(pg_get_serial_sequence(%s, %s), %s, %s)", (f"{R}.{t}", col, last_value, is_called))
    for v, t in zip(REAL_VIEWS, ["sales_fact", "purchase_fact", "salesreturn_fact", "sellout_fact", "inventory_fact", "unilever_sku_demand_fact"]):
        cur.execute(f"CREATE VIEW {R}.{v} AS SELECT * FROM {R}.{t} WHERE is_demo = false")


def backup(cur, T: str, tables: list[str], out_dir: Path, batch_id: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"target": T, "batch": batch_id, "taken_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "tables": {}}
    for t in tables:
        cols = columns(cur, T, t)
        data = export_csv(cur, T, t, cols)
        (out_dir / f"{t}.csv").write_bytes(data)
        manifest["tables"][t] = {"rows": one(cur, f"SELECT COUNT(*) FROM {T}.{t}"), "md5": hashlib.md5(data).hexdigest(),
                                 "columns": cols, "identity": identity_state(cur, T, t)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def undo(cur, T: str, log: dict) -> None:
    """Reverses a batch's change log: inserted fact rows, then inserted dimension rows, then updated values, then
    deleted rows re-inserted with their original keys. Schema objects a batch's migration added stay (additive);
    its schema_migrations row goes."""
    ins = log.get("inserted", {})
    for t in sorted(ins, key=lambda t: t in DIMENSIONS):
        cur.execute(f"DELETE FROM {T}.{t} WHERE {IDENT[t]} = ANY(%s)", (ins[t],))
        if cur.rowcount != len(ins[t]):
            raise RuntimeError(f"undo {t}: deleted {cur.rowcount}, change log has {len(ins[t])}")
    for t, entry in log.get("updated", {}).items():
        for r in entry["old"]:
            cur.execute(f"UPDATE {T}.{t} SET {', '.join(f'{c} = %s' for c in entry['cols'])} WHERE {entry['key']} = %s", (*r[1:], r[0]))
    for t, rows in log.get("deleted", {}).items():
        if rows:
            cols = list(rows[0])
            cur.execute(f"""INSERT INTO {T}.{t} ({', '.join(cols)}) OVERRIDING SYSTEM VALUE
                            SELECT {', '.join(cols)} FROM json_populate_recordset(NULL::{T}.{t}, %s::json)""", (json.dumps(rows),))
    if log.get("migrations_applied"):
        cur.execute(f"DELETE FROM {T}.schema_migrations WHERE filename = ANY(%s)", (log["migrations_applied"],))


def compare(cur, A: str, B: str, t: str) -> list[int]:
    """[rows only in A, rows only in B] on every column both share except the identity key and load timestamps."""
    cols = [c for c in columns(cur, A, t) if c in columns(cur, B, t) and c != IDENT.get(t) and c not in SKIP_COMPARE]
    a, b = (f"SELECT {', '.join(cols)} FROM {s}.{t}" for s in (A, B))
    return [one(cur, f"SELECT COUNT(*) FROM ({a} EXCEPT ALL {b}) x"), one(cur, f"SELECT COUNT(*) FROM ({b} EXCEPT ALL {a}) x")]


# --- the batches: fn(cur, T, check, log) -> (expected, applied); every write is recorded in `log` ----------------

def b1_duplicate_return_file(cur, T, check, log):
    from scripts.run_canonical_load import known_duplicate_file_records
    rule = "extract_known_duplicate_file[sales_return]"
    check("B1 rows of this rule already quarantined", one(cur, f"SELECT COUNT(*) FROM {T}.etl_quarantine WHERE rule = %s", (rule,)), 0)
    records = known_duplicate_file_records()
    keys = []
    for r in records:
        cur.execute(f"""INSERT INTO {T}.etl_quarantine (run_id, table_name, rule, reason, _src_file, _src_sheet, _row_ordinal, is_demo, raw_values)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING quarantine_key""",
                    ("dm_fixes_2026-09-28/b1", r["table_name"], r["rule"], r["reason"], r["_src_file"], r["_src_sheet"],
                     r["_row_ordinal"], r["is_demo"], r["raw_values"]))
        keys.append(cur.fetchone()[0])
    log["inserted"]["etl_quarantine"] = keys
    new = f"SELECT * FROM {T}.etl_quarantine WHERE quarantine_key = ANY(%s)"
    check("B1 rows per sheet", dict(sorted((s, n) for s, n in _rows(cur, f"SELECT _src_sheet, COUNT(*) FROM ({new}) q GROUP BY 1", (keys,)))),
          {"ILOCOS SALES RETURN": 13, "PANGASINAN SALE RETURN": 24})
    check("B1 net_amount of the quarantined rows", one(cur, f"SELECT SUM((raw_values->>'net_amount')::numeric)::text FROM ({new}) q", (keys,)), "98575.85")
    # every quarantined row has exactly one loaded twin from the original file, and every loaded row of it has one
    twins = f"""SELECT COUNT(DISTINCT s.return_key) FROM ({new}) q JOIN {T}.salesreturn_fact s ON NOT s.is_demo
                AND s._src_file = replace(q._src_file, ' (1).xlsx', '.xlsx') AND s._src_sheet = q._src_sheet
                AND s.return_slip_num = q.raw_values->>'return_slip_num' AND s.invoice_num = q.raw_values->>'invoice_num'
                AND s.region = q.raw_values->>'region' AND s.net_amount = (q.raw_values->>'net_amount')::numeric"""
    check("B1 quarantined rows with a loaded twin in the original file", one(cur, twins, (keys,)), 37)
    check("B1 loaded rows of the original file", one(cur, f"SELECT COUNT(*) FROM {T}.salesreturn_fact WHERE NOT is_demo AND _src_file = %s",
                                                     ("data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE RETURN.xlsx",)), 37)
    return 37, len(keys)


def _rows(cur, sql, args=None):
    cur.execute(sql, args)
    return cur.fetchall()


BATCHES = {
    1: ("quarantine record: April-2023 duplicate sales-return file", ["etl_quarantine"], b1_duplicate_return_file),
}


# --- runner -------------------------------------------------------------------------------------------------

def run_batch(conn, cur, T: str, batch_id: int, rehearse: bool, against: str | None) -> int:
    description, writes, fn = BATCHES[batch_id]
    ensure_ledger(conn, cur, T)
    mine = [r for r in ledger_rows(cur, T) if r["run_id"].startswith(RUN_PREFIX)]
    run_id = max((r["run_id"] for r in mine), default=None) or \
        f"{RUN_PREFIX}{'rehearsal_' if rehearse else ''}{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    done = {r["batch_id"] for r in mine if r["run_id"] == run_id and r["status"] == "done"}
    if batch_id in done:
        print(f"batch {batch_id} already done on {run_id}, skipped")
        return 0
    if [b for b in BATCHES if b < batch_id and b not in done]:
        sys.exit(f"refusing batch {batch_id}: earlier batches not done on {run_id}")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = REPO / "backups" / run_id / f"b{batch_id}_{stamp}"
    if not rehearse:
        rehearsed = [r for r in ledger_rows(cur, against) if r["run_id"].startswith(RUN_PREFIX) and r["batch_id"] == batch_id and r["status"] == "done"]
        if not rehearsed:
            sys.exit(f"refusing: batch {batch_id} has not been rehearsed on {against}")
        scratch_backup = Path(rehearsed[-1]["change_log"]["backup_dir"])
    tables = writes + (["schema_migrations"] if "schema_migrations" not in writes else [])
    manifest = backup(cur, T, tables, backup_dir, batch_id)
    conn.commit()
    checks: list = []

    def check(name, got, want):
        checks.append([name, str(got), str(want), str(got) == str(want)])

    def raise_if_failed():
        failed = [c for c in checks if not c[3]]
        if failed:
            raise RuntimeError("; ".join(f"{n}: got {g}, expected {w}" for n, g, w, _ in failed))

    if not rehearse:
        pre = json.loads((scratch_backup / "manifest.json").read_text(encoding="utf-8"))["tables"]
        for t in tables:
            check(f"{t} before the batch: md5 equals the rehearsal's pre-batch md5", manifest["tables"][t]["md5"], pre[t]["md5"])

    def apply() -> dict:
        log = {"inserted": {}, "updated": {}, "deleted": {}, "migrations_applied": []}
        before = isolation(cur, T, writes)
        expected, applied = fn(cur, T, check, log)
        check(f"batch {batch_id} rows applied", applied, expected)
        after = isolation(cur, T, writes)
        for k in before:
            check(f"{k}: untouched", after[k], before[k])
        log["_expected"], log["_applied"] = expected, applied
        return log

    started = datetime.datetime.now(datetime.timezone.utc)
    try:
        log = apply()
        raise_if_failed()
        if rehearse:
            conn.commit()
            undo(cur, T, log)
            proof: list = []
            reset_sequences(cur, T, manifest, proof)
            verify_against_backup(cur, T, backup_dir, manifest, proof)
            for name, got, want, ok in proof:
                checks.append([f"rollback proof: {name}", str(got), str(want), ok])
            conn.commit()
            log = apply()
        else:
            for t in writes:
                check(f"{t}: public vs {against}, rows only in each", compare(cur, T, against, t), [0, 0])
        raise_if_failed()
    except Exception as exc:
        conn.rollback()
        print(f"batch {batch_id} {description}: FAILED, rolled back - {exc}")
        cur.execute(f"""INSERT INTO {T}.{LEDGER} (run_id, target_schema, batch_id, description, table_name, started_at, finished_at, status, change_log)
                        VALUES (%s, %s, %s, %s, %s, %s, now(), 'failed', %s) ON CONFLICT (run_id, batch_id) DO UPDATE
                        SET status = 'failed', finished_at = now(), change_log = EXCLUDED.change_log""",
                    (run_id, T, batch_id, description, ",".join(writes), started, json.dumps({"error": str(exc), "_checks": checks}, default=str)))
        conn.commit()
        return 1
    log["_checks"], log["backup_dir"] = checks, str(backup_dir)
    after_md5 = hashlib.md5(json.dumps({t: fingerprint(cur, T, t, "TRUE") for t in writes}).encode()).hexdigest()
    cur.execute(f"""INSERT INTO {T}.{LEDGER} (run_id, target_schema, batch_id, description, table_name, expected_rows, applied_rows,
                    checksum_before, checksum_after, started_at, finished_at, status, change_log)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), 'done', %s) ON CONFLICT (run_id, batch_id) DO UPDATE
                    SET expected_rows = EXCLUDED.expected_rows, applied_rows = EXCLUDED.applied_rows, checksum_before = EXCLUDED.checksum_before,
                        checksum_after = EXCLUDED.checksum_after, finished_at = now(), status = 'done', change_log = EXCLUDED.change_log""",
                (run_id, T, batch_id, description, ",".join(writes), log["_expected"], log["_applied"],
                 "|".join(f"{t}:{m['md5']}" for t, m in manifest["tables"].items()), after_md5, started, json.dumps(log, default=str)))
    conn.commit()
    (backup_dir / "changes.json").write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")
    for name, got, want, _ in checks:
        print(f"  ok  {name}: {got}")
    print(f"batch {batch_id} {description}: {log['_applied']}/{log['_expected']} rows, {len(checks)} checks ok, committed ({run_id})")
    return 0


def rollback(conn, cur, backup_dir: Path) -> int:
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    log = json.loads((backup_dir / "changes.json").read_text(encoding="utf-8"))
    T, proof = manifest["target"], []
    undo(cur, T, log)
    reset_sequences(cur, T, manifest, proof)
    verify_against_backup(cur, T, backup_dir, manifest, proof)
    failed = [p for p in proof if not p[3]]
    if failed:
        conn.rollback()
        print(f"ROLLED BACK the undo - {failed}")
        return 1
    cur.execute(f"DELETE FROM {T}.{LEDGER} WHERE run_id = %s AND batch_id = %s", (backup_dir.parent.name, manifest["batch"]))
    conn.commit()
    print(f"undone: batch {manifest['batch']} on {T}, {len(proof)} checks ok")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", default=None, help="'public'")
    p.add_argument("--rehearse", default=None, metavar="SCHEMA", help="scratch schema (built from public on first use)")
    p.add_argument("--against", default=None, metavar="SCHEMA", help="--target public: the rehearsal schema to verify against")
    p.add_argument("--batch", type=int, default=None)
    p.add_argument("--rollback", default=None, metavar="BACKUP_DIR")
    p.add_argument("--status", action="store_true")
    p.add_argument("--i-have-approval", action="store_true")
    args = p.parse_args()
    conn = connect()
    cur = conn.cursor()
    try:
        if args.status:
            for r in ledger_rows(cur, args.target or args.rehearse):
                if r["run_id"].startswith(RUN_PREFIX):
                    print(f"  {r['run_id']}  batch {r['batch_id']}  {r['status']:<7} rows {r['applied_rows']}/{r['expected_rows']}  {r['description']}")
            return 0
        if args.rollback:
            if json.loads((Path(args.rollback) / "manifest.json").read_text(encoding="utf-8"))["target"] == "public" and not args.i_have_approval:
                sys.exit("refusing: a rollback on public needs --i-have-approval")
            return rollback(conn, cur, Path(args.rollback))
        if args.batch not in BATCHES:
            p.error(f"--batch must be one of {sorted(BATCHES)}")
        if args.rehearse:
            if args.rehearse in ("public", "ssm_synth_v2", "ssm_pm_cleanup"):
                p.error("--rehearse needs its own new scratch schema")
            if not one(cur, "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s", (args.rehearse,)):
                build_scratch(cur, args.rehearse)
                conn.commit()
                print(f"scratch schema {args.rehearse}: built from public")
            return run_batch(conn, cur, args.rehearse, args.batch, True, None)
        if args.target != "public" or not args.against or not args.i_have_approval:
            p.error("--target public needs --against SCHEMA and --i-have-approval")
        return run_batch(conn, cur, "public", args.batch, False, args.against)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
