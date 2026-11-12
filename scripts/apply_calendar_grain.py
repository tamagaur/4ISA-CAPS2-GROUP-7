"""scripts/apply_calendar_grain.py - the calendar factor at product grain (2026-11-12) put live, as ONE command, rehearsed first.

analytics.params.CALENDAR_GRAIN = "product" and DECEMBER_DIP_RULE = True are already set in the code
(analytics/forecasting/calendar.py ProductCalendar: each product's own month ratios pulled toward the typical product's, halfway
to 1; December takes last December's typical-product dip in full when it was a dip). This writes what they change:
  1. backup         python -m scripts.backup_everything (live only; must end "RESULT: PASS")
  2. forecast       python -m scripts.run_baseline_forecast --calendar-factor --write
                    -> Forecast_Result for 2026-03 rebuilt with each product's own calendar factor (its holdout MASE, the plan's
                       entry test, with it); marts refreshed
  3. review flags   python -m scripts.compute_review_flags --calendar-factor --write
  4. backtests      python -m scripts.accuracy_as_served --write-run --target-public
                    -> two NEW as-served runs labelled ", product calendar": the error card's default and its twin
  5. tier runs      python -m scripts.accuracy_as_served --write-tier-runs --target-public
  6. re-plan        python -m scripts.run_lp --retire-stale-pending --replan
  7. verify         every measured result equals the rehearsal's (docs/CALENDAR_GRAIN_REHEARSAL.json); then
                    bash scripts/check.sh --fast

No migration. Nothing is deleted: runs 15-18 and lp_run 9 stay stored (a re-plan supersedes, as every re-plan does).

    python -m scripts.apply_calendar_grain --rehearse --backup backups/full_backup_<stamp>
        Restores the backup into ssm_grain on 127.0.0.1:55432 (refuses any other server), checks every public and mart table
        equals live's (one READ ONLY transaction on live), runs steps 2-6 there, measures, writes the attestation. Never
        writes to live.
    python -m scripts.apply_calendar_grain --target-public
        Live. Refuses, writing nothing, unless the tree is clean, the files hash to the attestation, the preflight passes and
        every public and mart table equals the rehearsal's start. Then steps 1-7. Stops at the first failure.
    python -m scripts.apply_calendar_grain --check
        Read-only preflight against whatever SUPABASE_DB_URL names. Exit 0 when the live run would start.

Exit codes: 0 done and verified; 2 refused before anything was written; 1 a step failed or the result differs.
Ported from scripts/apply_forecastability_gate.py (kelvin/forecastability-gate), itself from apply_spike_cap.py.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import apply_final_bundle as fb  # noqa: E402  (the measuring and fingerprinting it was rehearsed with)

ATTESTATION = REPO / "docs" / "CALENDAR_GRAIN_REHEARSAL.json"
COPY_DB = "ssm_grain"
LAST_APPLIED = "0078_demo_row_level_security.sql"
START_PLAN = {"run_key": 9, "cycle": "2026-03-01", "rows": 110, "pieces": 378700}
GRAIN_LABEL = "%, product calendar%"
FILES = (
    "scripts/apply_calendar_grain.py", "scripts/apply_final_bundle.py", "analytics/params.py",
    "analytics/forecasting/router.py", "analytics/forecasting/global_model.py", "analytics/forecasting/calendar.py",
    "analytics/forecasting/treatments.py", "analytics/forecasting/baseline.py", "scripts/run_baseline_forecast.py",
    "scripts/accuracy_as_served.py", "scripts/backtest_forecast_run.py", "scripts/run_lp.py", "analytics/marts.py",
    "scripts/compute_review_flags.py", "analytics/forecasting/review_flag.py",
)
STEPS = (
    ("forecast", ["-m", "scripts.run_baseline_forecast", "--calendar-factor", "--write"]),
    ("review flags", ["-m", "scripts.compute_review_flags", "--calendar-factor", "--write"]),
    ("backtests", ["-m", "scripts.accuracy_as_served", "--write-run", "--target-public"]),
    ("tier runs", ["-m", "scripts.accuracy_as_served", "--write-tier-runs", "--target-public"]),
    ("re-plan", ["-m", "scripts.run_lp", "--retire-stale-pending", "--replan"]),
)
# Compared before -> after on the SAME database, not copy against live: a restore writes function bodies and default
# privileges differently (the final bundle's false alarm of 2026-11-11), and this apply changes neither.
UNCHANGED_KEYS = ("definitions_md5", "privileges_md5", "rls", "ledger_latest", "ledger_rows")


def files_hash() -> str:
    h = hashlib.sha256()
    for f in FILES:
        h.update(f.encode() + b"\0" + (REPO / f).read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def measure(cur) -> dict:
    r = fb.measure(cur)
    cur.execute("""SELECT count(*) FILTER (WHERE status = 'ok'), round(sum(forecast_value) FILTER (WHERE status = 'ok'), 2),
                          count(*) FILTER (WHERE status = 'ok' AND mase < 1)
                   FROM forecast_result WHERE forecast_date = DATE '2026-03-01'""")
    ok, total, mase_pass = cur.fetchone()
    cur.execute("""SELECT min((model_params->>'calendar_factor')::numeric), max((model_params->>'calendar_factor')::numeric),
                          count(DISTINCT model_params->>'calendar_factor') FROM forecast_result
                   WHERE forecast_date = DATE '2026-03-01' AND status = 'ok'""")
    fmin, fmax, fdistinct = cur.fetchone()
    r["forecast_2026_03"] = {"ok": int(ok), "total": float(total or 0), "mase_below_1": int(mase_pass),
                             "calendar_factor": {"min": float(fmin or 0), "max": float(fmax or 0), "distinct": int(fdistinct or 0)},
                             "rows_md5": fb._md5(cur, """SELECT product_key, status, round(forecast_value, 4), round(mase, 4)
                                                         FROM forecast_result WHERE forecast_date = DATE '2026-03-01'""")}
    cur.execute("""SELECT r.label, count(v.*), round(sum(v.forecast_pieces), 2) FROM mart.forecast_run r
                   LEFT JOIN mart.forecast_run_value v ON v.run_id = r.run_id WHERE r.label LIKE %s GROUP BY 1 ORDER BY 1""",
                (GRAIN_LABEL,))
    r["grain_runs"] = [[a, int(b), float(c or 0)] for a, b, c in cur.fetchall()]
    cur.execute("""SELECT count(*), count(*) FILTER (WHERE needs_review) FROM review_flag
                   WHERE planning_cycle_date = DATE '2026-03-01'""")
    n, flagged = cur.fetchone()
    r["review_flags_2026_03"] = {"rows": int(n), "flagged": int(flagged),
                                 "rows_md5": fb._md5(cur, """SELECT product_key, needs_review, reasons::text, over_run_months, served_bin FROM review_flag
                                                             WHERE planning_cycle_date = DATE '2026-03-01'""")}
    cur.execute("SELECT planning_stale, stale FROM mart.refresh_status")
    r["refresh_status"] = dict(zip(("planning_stale", "stale"), cur.fetchone()))
    r["grain_runs_md5"] = fb._md5(cur, """SELECT r.label, v.product_key, v.month, round(v.forecast_pieces, 4), v.status, v.treatment
                                          FROM mart.forecast_run r JOIN mart.forecast_run_value v ON v.run_id = r.run_id
                                          WHERE r.label LIKE %s""", (GRAIN_LABEL,))
    return r


def preflight(cur) -> list[str]:
    bad = []
    cur.execute("SELECT filename FROM schema_migrations")
    applied = {f for (f,) in cur.fetchall()}
    on_disk = sorted(p.name for p in fb.MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    if max(applied) != LAST_APPLIED or [f for f in on_disk if f not in applied]:
        bad.append(f"ledger ends at {max(applied)} with {[f for f in on_disk if f not in applied]} pending; expected {LAST_APPLIED}, none")
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
        bad.append("rows of the current plan have been decided")
    cur.execute("SELECT count(*) FROM mart.forecast_run WHERE label LIKE %s", (GRAIN_LABEL,))
    if cur.fetchone()[0]:
        bad.append("a product-calendar backtest run is already stored")
    return bad


def run_step(name: str, args: list[str], env: dict, log: list) -> None:
    fb.say(f"\n=== {name}: python {' '.join(args)}")
    p = subprocess.run([sys.executable, *args], cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    tail = "\n".join(out.splitlines()[-25:])
    fb.say(tail)
    log.append({"step": name, "exit": p.returncode, "tail": tail})
    if p.returncode != 0:
        raise fb.StepFailed(f"{name} exited {p.returncode}")
    if name == "backup" and "RESULT: PASS" not in out:
        raise fb.StepFailed("the backup did not end RESULT: PASS")
    if "error decomposition refresh FAILED" in out:
        raise fb.StepFailed(f"{name}: the mart refresh kept the old error decomposition (refresh FAILED)")


def compare(expected: dict, result: dict) -> dict:
    return {k: {"got": result.get(k), "expected": expected.get(k)} for k in expected
            if k not in UNCHANGED_KEYS and result.get(k) != expected.get(k)}


def unchanged(before: dict, after: dict) -> dict:
    return {k: {"before": before.get(k), "after": after.get(k)} for k in UNCHANGED_KEYS if before.get(k) != after.get(k)}


def rehearse(backup: Path) -> int:
    from analytics.config import long_read_db_url
    from scripts import local_pg
    if not local_pg.is_up():
        local_pg.start()
    url = local_pg.local_url(db=COPY_DB)
    host = urlparse(url)
    if host.hostname not in ("127.0.0.1", "localhost") or host.port != local_pg.PORT:
        raise SystemExit(f"refusing: the rehearsal copy must be on 127.0.0.1:{local_pg.PORT}, got {host.hostname}:{host.port}")
    fb.say(f"restoring {backup} into {COPY_DB} ...")
    mism = local_pg.restore(backup, db=COPY_DB)
    if mism:
        fb.say(f"REFUSED: the restore does not match the backup manifest: {mism}")
        return 2
    live_tables = fb.read_only(long_read_db_url(), fb.table_fingerprints)
    copy_tables = fb.read_only(url, fb.table_fingerprints)
    differ = fb.changed(live_tables, copy_tables)
    inputs_differ = [t for t in differ if t.split(".")[0] in ("public", "mart")]
    fb.say(f"copy vs live, before: {len(differ)} table(s) differ {differ}; public/mart: {inputs_differ}")
    if inputs_differ:
        fb.say("REFUSED: the copy is not live (a public or mart table differs); take a fresh backup")
        return 2
    bad = fb.read_only(url, preflight)
    if bad:
        fb.say("REFUSED (preflight on the copy): " + "; ".join(bad))
        return 2
    start = fb.read_only(url, measure)
    env, log = fb.child_env(url), []
    try:
        for name, args in STEPS:
            run_step(name, args, env, log)
    except fb.StepFailed as exc:
        fb.say(f"\nREHEARSAL FAILED: {exc}")
        return 1
    after_tables = fb.read_only(url, fb.table_fingerprints)
    result = fb.read_only(url, measure)
    moved = fb.changed(copy_tables, after_tables)
    same = unchanged(start, result)
    fb.say(f"\nchanged tables ({len(moved)}): {moved}")
    fb.say(json.dumps(result, indent=1, default=str))
    if same:
        fb.say(f"REHEARSAL FAILED: something this apply must not change did: {same}")
        return 1
    rec = {
        "written": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backup": backup.name, "copy": f"127.0.0.1:{local_pg.PORT}/{COPY_DB}",
        "files_sha256": files_hash(), "files": list(FILES),
        "copy_equals_live_before": {"tables_compared": len(live_tables), "differ": differ, "public_mart_differ": inputs_differ},
        "start_tables": {t: v for t, v in copy_tables.items() if t.split(".")[0] in ("public", "mart")},
        "start": start, "expected": result, "changed_tables": moved,
        "steps": [{"step": s["step"], "exit": s["exit"]} for s in log],
    }
    ATTESTATION.write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    fb.say(f"\nwrote {ATTESTATION.relative_to(REPO)} (files sha256 {rec['files_sha256'][:16]}...)")
    return 0


def apply_live(target_public: bool, check_only: bool) -> int:
    from analytics.config import long_read_db_url
    if not ATTESTATION.is_file():
        fb.say(f"REFUSED: no rehearsal attestation at {ATTESTATION.relative_to(REPO)}")
        return 2
    att = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    url = long_read_db_url()
    bad = fb.git_state()
    if att.get("files_sha256") != files_hash():
        bad.append("the files that do the work changed since the rehearsal (files_sha256 differs): re-rehearse")
    bad += fb.read_only(url, preflight)
    fb.say("fingerprinting every public and mart table (READ ONLY) ...")
    now_tables = fb.read_only(url, fb.table_fingerprints)
    drift = sorted(t for t in set(att["start_tables"]) | {t for t in now_tables if t.split(".")[0] in ("public", "mart")}
                   if att["start_tables"].get(t) != now_tables.get(t))
    if drift:
        bad.append(f"{len(drift)} public/mart table(s) differ from the rehearsal's start, so the result could differ: {drift}")
    if bad:
        fb.say("REFUSED, nothing written:\n  - " + "\n  - ".join(bad))
        return 2
    fb.say("preflight passed: the database is the rehearsal's start, the files are the rehearsed files.")
    if check_only:
        return 0
    if not target_public:
        fb.say("REFUSED: writing to public needs --target-public")
        return 2
    before = fb.read_only(url, measure)
    env, log, done = fb.child_env(None), [], []
    try:
        run_step("backup", ["-m", "scripts.backup_everything"], env, log)
        done.append("backup")
        for name, args in STEPS:
            run_step(name, args, env, log)
            done.append(name)
    except fb.StepFailed as exc:
        fb.say(f"\nSTOPPED: {exc}. Steps completed: {done or 'none'}. Do not re-run; bring this output. "
               "The backup (step 1) is the full state before; nothing was deleted, so the older runs and lp_run 9 are still stored.")
        return 1
    result = fb.read_only(url, measure)
    moved = fb.changed(now_tables, fb.read_only(url, fb.table_fingerprints))
    diffs, same = compare(att["expected"], result), unchanged(before, result)
    unexpected = sorted(set(moved) - set(att["changed_tables"]))
    fb.say(json.dumps(result, indent=1, default=str))
    fb.say(f"changed tables: {moved}")
    if diffs or same or unexpected:
        fb.say(f"\nRESULT DIFFERS from the rehearsal: {json.dumps(diffs, default=str)}; changed that must not: {same}; "
               f"tables not changed in the rehearsal: {unexpected}. Stop and report; the backup holds the state before.")
        return 1
    fb.say("\nRESULT: identical to the rehearsal. Running scripts/check.sh --fast against live ...")
    rc = subprocess.run(["bash", "scripts/check.sh", "--fast"], cwd=REPO, env=env).returncode
    fb.say(f"check.sh --fast exit {rc}")
    return 0 if rc == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--rehearse", action="store_true", help=f"restore --backup into {COPY_DB} (127.0.0.1:55432) and run the steps there")
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
