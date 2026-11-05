"""scripts/month_load_rehearsal.py - the gate: load, load, roll back, roll back on a restored copy, exact at every step (2026-11-06).

    python -m scripts.local_pg start
    python -m scripts.month_load_rehearsal --backup backups/full_backup_<stamp> [--no-write-attestation]

Restores the backup into `ssm_rehearsal` on 127.0.0.1:55432 (never any other database: it refuses), makes the two generated files from the restored data,
then drives scripts/demo_session.py as a child process, the way the page does:

    start          fingerprint of every table, view, function, sequence      -> F0
    load_first     load March                                                -> F1
    load_second    load April on top                                         -> F2
    rollback_second   roll April back          the system must equal F1 exactly
    rollback_first    roll March back          the system must equal F0 exactly; plan 109 rows / 435,988 pieces; the pinned figures reproduce
    load_first_again, load_second_again                                      -> F1', F2' (the same cycle works a second time)
    rollback_first_with_second_loaded   roll March back while April is also loaded: the system must equal F0 exactly
    load_first_third, load_second_third, third_month_refused_before_anything_changes
        March, April, then May: May cannot be planned (no opening stock count), so it is refused before anything is written and nothing moves
    crash_mid_run_then_rollback   (from the original state) a March load killed during the ABC reads "started, not finished", blocks the next month, and rolls
        back to the original state exactly

Only when every step is exact does it write docs/MONTH_LOAD_REHEARSAL.json (scripts/demo_rehearsal.py). A loaded step must also have changed the tables a
real month changes, so a load that did nothing cannot pass. The fingerprint is exact: row counts and an md5 of every row of every table of app, public,
mart and demo (audit_log, user_session and auth_token excluded, as the rollback excludes them), the definition of every view and function, and every
sequence. Output is the evidence; it prints the failing step and stops at the first.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import psycopg2  # noqa: E402

from analytics import demo_session as ds  # noqa: E402
from scripts import demo_rehearsal, demo_revert, local_pg  # noqa: E402

DB = "ssm_rehearsal"
MARCH, APRIL, MAY = "2026-03", "2026-04", "2026-05"
MUST_HAVE_CHANGED = ("public.unilever_sku_demand_fact", "public.forecast_result", "public.lp_recommendation", "public.lp_run", "mart.planning_mart", "mart.sales_mart")
START_PLAN = (109, 435988)


def say(text: str) -> None:
    print(f"[rehearsal {time.strftime('%H:%M:%S')}] {text}", flush=True)


def fingerprint_all(url: str) -> dict:
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL statement_timeout = 0")
        tables = {f"{s}.{t}": demo_revert.fingerprint(cur, s, t) for s, t in demo_revert.base_tables(cur)}
        defs = ds.definitions_fingerprint(cur)
        seqs = {f"{s}.{q}": (v, called) for s, q, v, called in demo_revert.sequences(cur)}
        conn.rollback()
        return {"tables": tables, "defs": defs, "sequences": seqs}
    finally:
        conn.close()


def differences(a: dict, b: dict) -> list[str]:
    out = [f"{k}: {a['tables'].get(k)} != {b['tables'].get(k)}" for k in sorted(set(a["tables"]) | set(b["tables"])) if a["tables"].get(k) != b["tables"].get(k)]
    if a["defs"] != b["defs"]:
        out.append("views and functions differ")
    out += [f"sequence {k}: {a['sequences'].get(k)} != {b['sequences'].get(k)}" for k in sorted(set(a["sequences"]) | set(b["sequences"]))
            if a["sequences"].get(k) != b["sequences"].get(k)]
    return out


def changed_tables(a: dict, b: dict) -> list[str]:
    return [k for k in sorted(a["tables"]) if a["tables"].get(k) != b["tables"].get(k)]


def plan_of(url: str) -> dict:
    out = subprocess.run([sys.executable, "-m", "scripts.demo_session", "status", "--json"], cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=child_env(url))
    if out.returncode:
        raise SystemExit("status failed: " + out.stderr[-400:])
    return json.loads(out.stdout.strip().splitlines()[-1])


def child_env(url: str) -> dict:
    return {**os.environ, "SUPABASE_DB_URL": url, "SUPABASE_DIRECT_URL": url, "DATABASE_URL": url, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}


def run(url: str, *args: str) -> tuple[int, float]:
    start = time.monotonic()
    rc = subprocess.run([sys.executable, "-m", "scripts.demo_session", *args], cwd=REPO, env=child_env(url)).returncode
    return rc, time.monotonic() - start


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backup", required=True)
    ap.add_argument("--no-write-attestation", action="store_true")
    ap.add_argument("--keep-going", action="store_true", help="do not stop at the first inexact step")
    args = ap.parse_args()
    url = local_pg.local_url(db=DB)
    if "127.0.0.1" not in url or f"/{DB}" not in url:
        raise SystemExit("REFUSED: the rehearsal runs only on ssm_rehearsal on 127.0.0.1")
    say(f"restoring {args.backup} into {DB}")
    bad = local_pg.restore(Path(args.backup), db=DB)
    if bad:
        raise SystemExit(f"REFUSED: the restore does not match its manifest: {bad}")
    files = {}
    for month in (MARCH, APRIL, MAY):
        out = REPO / "local" / "demo" / f"rehearsal_sales_{month}.csv"
        rc = subprocess.run([sys.executable, "-m", "scripts.make_demo_sales_file", "--month", month, "--out", str(out)], cwd=REPO, env=child_env(url)).returncode
        if rc:
            raise SystemExit(f"could not make the {month} file")
        files[month] = str(out)
    steps: dict[str, dict] = {}
    f0 = fingerprint_all(url)
    start_status = plan_of(url)
    start_plan = (start_status["plan"]["rows"], start_status["plan"]["pieces"])
    say(f"start: plan {start_status['newest_cycle']} = {start_plan[0]} rows / {start_plan[1]:,} pieces; expected {START_PLAN}")
    if start_plan != START_PLAN:
        raise SystemExit(f"the restored copy does not start at {START_PLAN}")
    state = {"f": f0}

    def record(name: str, exact: bool, detail: dict) -> bool:
        steps[name] = {"exact": exact, **detail}
        say(f"{name}: {'EXACT' if exact else 'NOT EXACT'} {json.dumps(detail, default=str)[:600]}")
        return exact or args.keep_going

    def load(name: str, month: str) -> bool:
        before = state["f"]
        rc, secs = run(url, "load", "--file", files[month], "--by", "rehearsal@local", "--accept-waiting", "--target-public")
        after = fingerprint_all(url)
        changed = changed_tables(before, after)
        status = plan_of(url)
        entry = next((m for m in status["loaded"] if m["month"] == month), None)
        ok = rc == 0 and entry is not None and entry["state"] == "loaded" and not [t for t in MUST_HAVE_CHANGED if t not in changed]
        state["f"] = after
        state[name] = after
        return record(name, ok, {"exit": rc, "seconds": round(secs), "tables_changed": len(changed), "loaded": [m["month"] for m in status["loaded"]],
                                 "plan": status["plan"], "newest_cycle": status["newest_cycle"]})

    def rollback(name: str, month: str, expect: dict, expect_plan: tuple | None = None) -> bool:
        rc, secs = run(url, "rollback", "--month", month, "--by", "rehearsal@local", "--yes", "--target-public")
        after = fingerprint_all(url)
        diff = differences(expect, after)
        status = plan_of(url)
        plan_ok = expect_plan is None or (status["plan"]["rows"], status["plan"]["pieces"]) == expect_plan
        ok = rc == 0 and not diff and plan_ok and not status["loaded"] if month == MARCH else rc == 0 and not diff and plan_ok
        state["f"] = after
        return record(name, ok, {"exit": rc, "seconds": round(secs), "differences": diff[:8], "plan": status["plan"], "newest_cycle": status["newest_cycle"],
                                 "loaded_after": [m["month"] for m in status["loaded"]]})

    def third() -> bool:
        """A third month cannot be planned: its opening stock count does not exist. It is refused BEFORE anything is written: the file check says why, the
        command exits non-zero, and every table, view, function and sequence equals what it was a moment ago."""
        rc, secs = run(url, "load", "--file", files[MAY], "--by", "rehearsal@local", "--accept-waiting", "--target-public")
        after = fingerprint_all(url)
        diff = differences(state["f"], after)
        status = plan_of(url)
        months = [m["month"] for m in status["loaded"]]
        checked = subprocess.run([sys.executable, "-m", "scripts.demo_session", "check-file", "--file", files[MAY]], cwd=REPO, capture_output=True, text=True,
                                 encoding="utf-8", env=child_env(url))
        said = json.loads(checked.stdout.strip().splitlines()[-1])["message"] if checked.returncode == 0 else checked.stderr[-200:]
        exact = rc != 0 and not diff and months == [MARCH, APRIL] and "stock count" in said
        return record("third_month_refused_before_anything_changes", exact, {"load_exit": rc, "differences": diff[:8], "loaded_after": months, "said": said[:200], "seconds": round(secs)})

    def crash() -> bool:
        """A load interrupted while it runs (the process is killed during the ABC): the rollback point exists, the month reads 'started, not finished', another month
        is refused until it is settled, and rolling it back puts the system exactly where it was."""
        before = state["f"]
        proc = subprocess.Popen([sys.executable, "-m", "scripts.demo_session", "load", "--file", files[MARCH], "--by", "rehearsal@local", "--accept-waiting", "--target-public"],
                                cwd=REPO, env=child_env(url), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        reached = False
        for line in proc.stdout:
            print("   | " + line.rstrip(), flush=True)
            if line.startswith("[abc] running"):
                reached = True
                break
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        proc.wait()
        status = plan_of(url)
        unfinished = [(m["month"], m["state"]) for m in status["loaded"]]
        refused = subprocess.run([sys.executable, "-m", "scripts.demo_session", "check-file", "--file", files[APRIL]], cwd=REPO, capture_output=True, text=True,
                                 encoding="utf-8", env=child_env(url))
        said = json.loads(refused.stdout.strip().splitlines()[-1])["message"]
        rc, secs = run(url, "rollback", "--month", MARCH, "--by", "rehearsal@local", "--yes", "--target-public")
        after = fingerprint_all(url)
        diff = differences(f0, after)
        final = plan_of(url)
        exact = reached and unfinished == [(MARCH, "taken")] and "has not finished" in said and rc == 0 and not diff and not final["loaded"]             and (final["plan"]["rows"], final["plan"]["pieces"]) == START_PLAN
        state["f"] = after
        del before
        return record("crash_mid_run_then_rollback", exact, {"reached_abc": reached, "state_after_crash": unfinished, "next_month_said": said[:160], "rollback_exit": rc,
                                                              "differences": diff[:8], "plan": final["plan"], "seconds": round(secs)})

    sequence = [
        lambda: load("load_first", MARCH),
        lambda: load("load_second", APRIL),
        lambda: rollback("rollback_second", APRIL, state["load_first"]),
        lambda: rollback("rollback_first", MARCH, f0, START_PLAN),
        lambda: load("load_first_again", MARCH),
        lambda: load("load_second_again", APRIL),
        lambda: rollback("rollback_first_with_second_loaded", MARCH, f0, START_PLAN),
        crash,
        lambda: load("load_first_third", MARCH),
        lambda: load("load_second_third", APRIL),
        third,
    ]
    for step in sequence:
        if not step():
            say("STOPPED at the first inexact step. Nothing is attested.")
            return 1
    # step names in the attestation
    final = {k: steps[k] for k in demo_rehearsal.STEPS if k in steps}
    if [k for k in demo_rehearsal.STEPS if k not in final or not final[k]["exact"]]:
        say("not every step ran exact: nothing is attested")
        return 1
    say("EVERY STEP EXACT: load, load, roll back April, roll back March, load, load, roll back March with April loaded.")
    if not args.no_write_attestation:
        demo_rehearsal.write(f"127.0.0.1/{DB}", final, START_PLAN, Path(args.backup).name)
        say(f"attestation written: {demo_rehearsal.PROOF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
