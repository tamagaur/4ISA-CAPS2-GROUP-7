"""scripts/apply_final_bundle.py - the last plan-moving bundle (2026-11-11), as ONE command, rehearsed on a restored copy first.

What it applies, in order (each step is the project's own tool, run as a child process against the target):
  1. backup         python -m scripts.backup_everything (live only; must end "RESULT: PASS")
  2. migrations     python -m scripts.run_canonical_load --schema public --target-public --schema-only
                    -> 0075 (Data API lockdown), 0076 (forecast_challenger table, empty), 0077 (decomposition safety stock follows
                       the level; forecast_run_value.treatment), 0078 (row-level security on the demo schema)
  3. backfill       python -m scripts.accuracy_as_served --backfill-treatment --target-public
                    -> sets the treatment flag on the stored as-served runs (checked against their untreated twins), refreshes the
                       marts, so the error decomposition is rebuilt under 0077
  4. re-plan        python -m scripts.run_lp --retire-stale-pending --replan
                    -> a new lp_run for cycle 2026-03 with safety stock following the level for zero-forecast products too
                       (scripts/run_lp.TREATMENT_QUERY); refreshes the marts again
  5. verify         every measured result equals the rehearsal's (docs/FINAL_BUNDLE_REHEARSAL.json); then bash scripts/check.sh --fast

    python -m scripts.apply_final_bundle --rehearse --backup backups/full_backup_<stamp>
        Restores the backup into ssm_bundle on 127.0.0.1:55432 (refuses any other server), checks every public and mart table of
        the copy equals live's (one READ ONLY transaction on live), runs steps 2-4 on the copy, measures, and writes
        docs/FINAL_BUNDLE_REHEARSAL.json: the start fingerprint, the expected result, the tables that changed, and a hash of
        the files that do the work. Never writes to live.
    python -m scripts.apply_final_bundle --target-public
        Live. Refuses, writing nothing, unless: the working tree is clean; the files hash equals the attestation's; the ledger
        ends at 0074 with exactly 0075-0078 pending; every public and mart table equals the rehearsal's start (so the result
        must equal the rehearsal's). Then steps 1-5. Stops at the first step that fails and says what ran.
    python -m scripts.apply_final_bundle --check
        Read-only: the preflight alone, against whatever SUPABASE_DB_URL names. Exit 0 when the live run would start.

Exit codes: 0 done and verified; 2 refused before anything was written; 1 a step failed or the result differs (stop, report).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import psycopg2  # noqa: E402

ATTESTATION = REPO / "docs" / "FINAL_BUNDLE_REHEARSAL.json"
COPY_DB = "ssm_bundle"
MIGRATIONS_DIR = REPO / "analytics" / "db" / "migrations"
LAST_APPLIED = "0074_views_real_rows_only.sql"
PENDING = ("0075_lock_down_data_api.sql", "0076_forecast_challenger.sql", "0077_decomposition_ss_follows_level.sql",
           "0078_demo_row_level_security.sql")
START_PLAN = {"run_key": 8, "cycle": "2026-03-01", "rows": 110, "pieces": 381484}
SCHEMAS = ("app", "public", "mart", "demo")
EXCLUDED = {"app.audit_log", "app.user_session", "app.auth_token"}   # sign-ins write these; nothing here reads them
KEYED_SEQUENCES = ("public.lp_run_run_key_seq",)                      # the one generated key that appears in a result
# A change to any of these changes what the bundle does, so the attestation is bound to them.
FILES = (
    "scripts/apply_final_bundle.py", "scripts/run_lp.py", "scripts/accuracy_as_served.py", "scripts/run_canonical_load.py",
    "analytics/marts.py", "analytics/params.py", "analytics/forecasting/treatments.py", "analytics/forecasting/router.py",
    "scripts/run_baseline_forecast.py", "scripts/backtest_forecast_run.py",
    *(f"analytics/db/migrations/{f}" for f in PENDING),
)
STEPS = (
    ("migrations", ["-m", "scripts.run_canonical_load", "--schema", "public", "--target-public", "--schema-only"]),
    ("treatment backfill", ["-m", "scripts.accuracy_as_served", "--backfill-treatment", "--target-public"]),
    ("re-plan", ["-m", "scripts.run_lp", "--retire-stale-pending", "--replan"]),
)


def files_hash() -> str:
    h = hashlib.sha256()
    for f in FILES:
        h.update(f.encode() + b"\0" + (REPO / f).read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def say(msg: str) -> None:
    print(msg, flush=True)


# ---- measurements (all read-only) -------------------------------------------------------------------------------

def table_fingerprints(cur) -> dict[str, list]:
    cur.execute("""SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s) ORDER BY 1, 2""", (list(SCHEMAS),))
    out = {}
    for s, t in cur.fetchall():
        if f"{s}.{t}" in EXCLUDED:
            continue
        cur.execute(f'SELECT count(*), md5(coalesce(string_agg(x::text, \',\' ORDER BY x::text), \'\')) FROM "{s}"."{t}" x')
        n, h = cur.fetchone()
        out[f"{s}.{t}"] = [int(n), h]
    # The lp_run key sequence too: the new run's key comes from it, and the pinned chapter queries name that key. A sequence
    # that moved on live since the backup (a run written and rolled back) would give live a different key than the rehearsal.
    # Only the sequences in KEYED_SEQUENCES: a restore sets every sequence to its table's highest key, while live's run ahead
    # of gaps (read 2026-11-11: lp_recommendation 1,919 live, 1,744 restored), and no other generated key is in a result.
    cur.execute("SELECT schemaname, sequencename, last_value, ''::text FROM pg_sequences "
                "WHERE schemaname || '.' || sequencename = ANY(%s) ORDER BY 1, 2", (list(KEYED_SEQUENCES),))
    for s, q, v, _ in cur.fetchall():
        out[f"{s}.{q} (sequence)"] = [None if v is None else int(v), "last_value"]
    return out


def _md5(cur, sql: str, params=None) -> str:
    cur.execute(f"SELECT md5(coalesce(string_agg(t::text, ',' ORDER BY t::text), '')) FROM ({sql}) t", params)
    return cur.fetchone()[0]


def measure(cur) -> dict:
    """The bundle's results, without timestamps or generated keys, so a rehearsal and live can be compared exactly."""
    from analytics.demo_session import definitions_fingerprint
    from scripts.rehearse_0075 import FINGERPRINT_SQL
    r: dict = {}
    cur.execute("SELECT max(filename), count(*) FROM schema_migrations")
    latest, n = cur.fetchone()
    r["ledger_latest"], r["ledger_rows"] = latest, int(n)
    cur.execute("SELECT max(run_key) FROM lp_run")
    run = cur.fetchone()[0]
    cur.execute("""SELECT to_char(min(planning_cycle_date), 'YYYY-MM-DD'), count(*), round(sum(q_i))::bigint,
                          count(*) FILTER (WHERE q_i > 0), round(sum(ss_i), 2)
                   FROM lp_recommendation WHERE lp_run_key = %s""", (run,))
    cycle, rows, pieces, ordering, ss = cur.fetchone()
    r["plan"] = {"run_key": int(run), "cycle": cycle, "rows": int(rows), "pieces": int(pieces or 0), "ordering": int(ordering),
                 "ss_total": float(ss or 0),
                 "rows_md5": _md5(cur, """SELECT product_key, q_i, round(ss_i, 4) AS ss, round(rop_i, 4) AS rop, status,
                                                 q_i_before_pack_rounding, pack_size
                                          FROM lp_recommendation WHERE lp_run_key = %s""", (run,))}
    cur.execute("SELECT count(*) FROM lp_recommendation WHERE status <> 'pending'")
    r["decided_rows_all_cycles"] = int(cur.fetchone()[0])
    cur.execute("SELECT to_regclass('mart.error_decomposition_row') IS NOT NULL")
    if cur.fetchone()[0]:
        has_lf = _has_column(cur, "mart", "error_decomposition_row", "safety_stock_level_factor")
        cur.execute(f"""SELECT count(*), {'count(safety_stock_level_factor)' if has_lf else 'NULL'},
                               round(sum(over_pieces), 2), round(sum(absorbed_pieces), 2), round(sum(beyond_pieces), 2),
                               count(*) FILTER (WHERE exceeds_safety_stock), round(sum(safety_stock_pieces), 2)
                        FROM mart.error_decomposition_row""")
        n, lf, over, absorbed, beyond, exceed, ss_sum = cur.fetchone()
        r["decomposition"] = {"rows": int(n), "level_factor_rows": None if lf is None else int(lf), "over_pieces": float(over or 0),
                              "absorbed_pieces": float(absorbed or 0), "beyond_pieces": float(beyond or 0),
                              "exceed_product_months": int(exceed), "safety_stock_pieces": float(ss_sum or 0),
                              "rows_md5": _md5(cur, """SELECT principal, tier, product_key, month, forecast_run_id, ss_method,
                                                              round(safety_stock_pieces, 4), round(absorbed_pieces, 4),
                                                              round(beyond_pieces, 4), exceeds_safety_stock
                                                       FROM mart.error_decomposition_row""")}
    if _has_column(cur, "mart", "forecast_run_value", "treatment"):
        cur.execute("""SELECT run_id, treatment, count(*) FROM mart.forecast_run_value WHERE treatment IS NOT NULL
                       GROUP BY 1, 2 ORDER BY 1, 2""")
        r["treatments"] = [[int(a), b, int(c)] for a, b, c in cur.fetchall()]
    cur.execute("""SELECT n.nspname, count(*), count(*) FILTER (WHERE c.relrowsecurity) FROM pg_class c
                   JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s) GROUP BY 1 ORDER BY 1""", (list(SCHEMAS),))
    r["rls"] = {s: [int(a), int(b)] for s, a, b in cur.fetchall()}
    cur.execute(FINGERPRINT_SQL, {"s": list(SCHEMAS)})
    r["privileges_md5"] = hashlib.md5("\n".join("|".join(x) for x in cur.fetchall()).encode()).hexdigest()
    r["definitions_md5"] = definitions_fingerprint(cur)[0]
    return r


def _has_column(cur, schema: str, table: str, column: str) -> bool:
    cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = %s AND table_name = %s AND column_name = %s)",
                (schema, table, column))
    return bool(cur.fetchone()[0])


def read_only(url: str, fn):
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")   # transaction-scoped: never a session SET on the :6543 pooler
        # A row's text form depends on the session: timestamptz prints in its TimeZone (UTC on Supabase, the machine's zone
        # on the local server) and floats by extra_float_digits. Both pinned for this transaction only (SET LOCAL), so the
        # same rows give the same fingerprint on live and on a restored copy.
        cur.execute("SET LOCAL TIME ZONE 'UTC'")
        cur.execute("SET LOCAL extra_float_digits = 3")
        cur.execute("SET LOCAL DateStyle = 'ISO, YMD'")
        cur.execute("SET LOCAL IntervalStyle = 'postgres'")
        return fn(cur)
    finally:
        conn.rollback()
        conn.close()


# ---- preflight ----------------------------------------------------------------------------------------------------

def preflight(cur) -> list[str]:
    """Reasons the bundle cannot start on this database; empty = it can."""
    bad = []
    cur.execute("SELECT filename FROM schema_migrations")
    applied = {f for (f,) in cur.fetchall()}
    on_disk = sorted(p.name for p in MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    pending = [f for f in on_disk if f not in applied]
    if max(applied) != LAST_APPLIED:
        bad.append(f"ledger ends at {max(applied)}, expected {LAST_APPLIED}")
    if tuple(pending) != PENDING:
        bad.append(f"pending migrations {pending}, expected {list(PENDING)}")
    cur.execute("""SELECT r.run_key, to_char(r.planning_cycle_date, 'YYYY-MM-DD'),
                          (SELECT count(*) FROM lp_recommendation l WHERE l.lp_run_key = r.run_key),
                          (SELECT round(sum(q_i))::bigint FROM lp_recommendation l WHERE l.lp_run_key = r.run_key)
                   FROM lp_run r ORDER BY r.run_key DESC LIMIT 1""")
    run, cycle, rows, pieces = cur.fetchone()
    got = {"run_key": int(run), "cycle": cycle, "rows": int(rows), "pieces": int(pieces or 0)}
    if got != START_PLAN:
        bad.append(f"newest plan is {got}, expected {START_PLAN}")
    cur.execute("SELECT count(*) FROM lp_recommendation WHERE lp_run_key = %s AND status <> 'pending'", (run,))
    if cur.fetchone()[0]:
        bad.append("rows of the current plan have been decided since the rehearsal's start")
    return bad


def git_state() -> list[str]:
    bad = []
    st = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout
    if st.strip():
        bad.append("the working tree has uncommitted changes to tracked files:\n" + st)
    return bad


# ---- running the steps --------------------------------------------------------------------------------------------

def child_env(url: str | None) -> dict:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    if url:
        env.update({"SUPABASE_DB_URL": url, "SUPABASE_DIRECT_URL": url})
    return env


def run_step(name: str, args: list[str], env: dict, log: list) -> None:
    say(f"\n=== {name}: python {' '.join(args)}")
    p = subprocess.run([sys.executable, *args], cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    tail = "\n".join(out.splitlines()[-25:])
    say(tail)
    log.append({"step": name, "exit": p.returncode, "tail": tail})
    if p.returncode != 0:
        raise StepFailed(f"{name} exited {p.returncode}")
    if name == "backup" and "RESULT: PASS" not in out:
        raise StepFailed("the backup did not end RESULT: PASS")
    if name == "treatment backfill" and "error decomposition refresh FAILED" in out:
        raise StepFailed("the mart refresh kept the old error decomposition (refresh FAILED)")
    if name == "re-plan" and "error decomposition refresh FAILED" in out:
        raise StepFailed("the re-plan's mart refresh kept the old error decomposition (refresh FAILED)")


class StepFailed(RuntimeError):
    pass


def changed(before: dict, after: dict) -> list[str]:
    return sorted(t for t in set(before) | set(after) if before.get(t) != after.get(t))


def rehearse(backup: Path) -> int:
    from analytics.config import long_read_db_url
    from scripts import local_pg
    if not local_pg.is_up():
        local_pg.start()
    url = local_pg.local_url(db=COPY_DB)
    host = urlparse(url)
    if host.hostname not in ("127.0.0.1", "localhost") or host.port != local_pg.PORT:
        raise SystemExit(f"refusing: the rehearsal copy must be on 127.0.0.1:{local_pg.PORT}, got {host.hostname}:{host.port}")
    say(f"restoring {backup} into {COPY_DB} ...")
    mism = local_pg.restore(backup, db=COPY_DB)
    if mism:
        say(f"REFUSED: the restore does not match the backup manifest: {mism}")
        return 2
    say("reading live (one READ ONLY transaction): every table's fingerprint, and the preflight ...")
    live_tables = read_only(long_read_db_url(), table_fingerprints)
    live_start = read_only(long_read_db_url(), measure)
    copy_tables = read_only(url, table_fingerprints)
    copy_start = read_only(url, measure)
    differ = changed(live_tables, copy_tables)
    inputs_differ = [t for t in differ if t.split(".")[0] in ("public", "mart")]
    say(f"copy vs live, before: {len(differ)} table(s) differ {differ}; public/mart: {inputs_differ}")
    start_cmp = {k: (live_start[k], copy_start[k]) for k in live_start if live_start[k] != copy_start.get(k)}
    say(f"copy vs live, measured results before: {'identical' if not start_cmp else start_cmp}")
    if inputs_differ:
        say("REFUSED: the copy is not live (a public or mart table differs); take a fresh backup")
        return 2
    bad = read_only(url, preflight)
    if bad:
        say("REFUSED (preflight on the copy): " + "; ".join(bad))
        return 2
    env, log = child_env(url), []
    try:
        for name, args in STEPS:
            run_step(name, args, env, log)
    except StepFailed as exc:
        say(f"\nREHEARSAL FAILED: {exc}")
        return 1
    after_tables = read_only(url, table_fingerprints)
    result = read_only(url, measure)
    moved = changed(copy_tables, after_tables)
    say(f"\nchanged tables ({len(moved)}): {moved}")
    say(json.dumps(result, indent=1, default=str))
    rec = {
        "written": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backup": backup.name, "copy": f"127.0.0.1:{local_pg.PORT}/{COPY_DB}",
        "files_sha256": files_hash(), "files": list(FILES),
        "copy_equals_live_before": {"tables_compared": len(live_tables), "differ": differ, "public_mart_differ": inputs_differ,
                                    "measured_differ": sorted(start_cmp)},
        "start_tables": {t: v for t, v in copy_tables.items() if t.split(".")[0] in ("public", "mart")},
        "start": copy_start, "expected": result, "changed_tables": moved,
        "steps": [{"step": s["step"], "exit": s["exit"]} for s in log],
    }
    ATTESTATION.write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    say(f"\nwrote {ATTESTATION.relative_to(REPO)} (files sha256 {rec['files_sha256'][:16]}...)")
    return 0


def apply_live(target_public: bool, check_only: bool) -> int:
    from analytics.config import long_read_db_url
    if not ATTESTATION.is_file():
        say(f"REFUSED: no rehearsal attestation at {ATTESTATION.relative_to(REPO)}")
        return 2
    att = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    url = long_read_db_url()
    bad = git_state()
    if att.get("files_sha256") != files_hash():
        bad.append("the files that do the work changed since the rehearsal (files_sha256 differs): re-rehearse")
    bad += read_only(url, preflight)
    say("fingerprinting every public and mart table (READ ONLY) ...")
    now_tables = read_only(url, table_fingerprints)
    drift = sorted(t for t in set(att["start_tables"]) | {t for t in now_tables if t.split(".")[0] in ("public", "mart")}
                   if att["start_tables"].get(t) != now_tables.get(t))
    if drift:
        bad.append(f"{len(drift)} public/mart table(s) differ from the rehearsal's start, so the result could differ: {drift}")
    if bad:
        say("REFUSED, nothing written:\n  - " + "\n  - ".join(bad))
        return 2
    say("preflight passed: the database is the rehearsal's start, the files are the rehearsed files.")
    if check_only:
        return 0
    if not target_public:
        say("REFUSED: writing to public needs --target-public")
        return 2
    env, log = child_env(None), []
    done = []
    try:
        run_step("backup", ["-m", "scripts.backup_everything"], env, log)
        done.append("backup")
        for name, args in STEPS:
            run_step(name, args, env, log)
            done.append(name)
    except StepFailed as exc:
        say(f"\nSTOPPED: {exc}. Steps completed: {done or 'none'}. Do not re-run; bring this output. "
            "The backup (step 1) is the full state before the bundle; each migration header gives its rollback.")
        return 1
    result = read_only(url, measure)
    after_tables = read_only(url, table_fingerprints)
    moved = changed(now_tables, after_tables)
    exp = att["expected"]
    diffs = {k: {"live": result.get(k), "rehearsal": exp.get(k)} for k in exp if result.get(k) != exp.get(k)}
    unexpected = sorted(set(moved) - set(att["changed_tables"]))
    say(json.dumps(result, indent=1, default=str))
    say(f"changed tables: {moved}")
    if diffs or unexpected:
        say(f"\nRESULT DIFFERS from the rehearsal: {json.dumps(diffs, default=str)}; tables not changed in the rehearsal: {unexpected}. "
            "Stop and report; the backup holds the state before.")
        return 1
    say("\nRESULT: identical to the rehearsal. Running scripts/check.sh --fast against live ...")
    rc = subprocess.run(["bash", "scripts/check.sh", "--fast"], cwd=REPO, env=env).returncode
    say(f"check.sh --fast exit {rc}")
    return 0 if rc == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--rehearse", action="store_true", help="restore --backup into ssm_bundle (127.0.0.1:55432) and run the bundle there")
    g.add_argument("--target-public", action="store_true", help="apply to the database SUPABASE_DB_URL names (live)")
    g.add_argument("--check", action="store_true", help="read-only preflight only")
    ap.add_argument("--backup", type=Path, help="with --rehearse: the backups/full_backup_<stamp> folder to restore")
    a = ap.parse_args(argv)
    if a.rehearse:
        if not a.backup:
            ap.error("--rehearse needs --backup")
        return rehearse(a.backup)
    return apply_live(a.target_public, a.check)


if __name__ == "__main__":
    sys.exit(main())
