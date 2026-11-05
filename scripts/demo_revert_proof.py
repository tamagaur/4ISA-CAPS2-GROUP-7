"""scripts/demo_revert_proof.py - prove the revert on a restored copy of live, before any demonstration row goes near live (2026-11-05).

    python -m scripts.local_pg start
    python -m scripts.local_pg restore backups/full_backup_<stamp>      # the copy, into ssm_local
    python -m scripts.demo_revert_proof --backup backups/full_backup_<stamp>

What it does, on the throwaway server only (127.0.0.1:55432, ssm_practice made from ssm_local):
  1. reads the plan and the pinned figures of the untouched copy;
  2. takes a snapshot (scripts/demo_revert.py);
  3. runs a whole demonstration month: generated March sales, the decisions run_month asks for, ABC, forecast, safety stock, LP, marts,
     review, close (the same commands as scripts/practice_artefacts.py);
  4. checks the month really changed the database (a revert that has nothing to revert proves nothing);
  5. reverts, and requires every table's fingerprint to equal the snapshot's;
  6. requires the plan to read the figures of step 1 again (109 rows, 435,988 pieces for the 2026-11-04 backup) and the 51 pinned
     figures to reproduce (scripts.snapshot_published_figures --verify), and the five cross-endpoint invariants to pass;
  7. writes local/demo_revert_proof.json, which scripts/demo_revert.py reads before it will write to any other database.

The proof is of the revert, run with the practice copy's own demand view (the copy admits generated rows through it, live does not).
It says nothing about how the pages read generated rows on live; that is a separate path and has its own checks.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

import psycopg2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import local_pg  # noqa: E402
from scripts.demo_revert import PROOF_FILE, compare, read_manifest  # noqa: E402

TAG = "proof"
CYCLE = "2026-03-01"
MONTH = "2026-03"
PLAN_SQL = """SELECT count(*), round(sum(q_i)::numeric) FROM lp_recommendation lr
              JOIN product_dimension pd ON pd.product_key = lr.product_key
              WHERE pd.principal = 'unilever' AND lr.planning_cycle_date = %s AND lr.lp_run_key IS NOT NULL
                AND lr.status IN ('pending', 'accepted', 'dismissed')"""


def plan_figures(conn, cycle: str) -> tuple[int, int]:
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute(PLAN_SQL, (cycle,))
    n, pieces = cur.fetchone()
    conn.rollback()
    return int(n), int(pieces or 0)


def step(label: str, cmd: list[str], practice: bool = True) -> int:
    print(f"\n=== {label}", flush=True)
    return local_pg.run(cmd, practice=practice)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", required=True, help="the backup folder that was restored into ssm_local")
    args = ap.parse_args()
    py = sys.executable
    local_pg.make_practice()
    url = local_pg.local_url(practice=True)
    conn = psycopg2.connect(url)
    before_plan = plan_figures(conn, CYCLE)
    print(f"untouched copy: plan {CYCLE[:7]} = {before_plan[0]} rows, {before_plan[1]:,} pieces")

    failures: list[str] = []
    if step("pinned figures, untouched copy", [py, "-m", "scripts.snapshot_published_figures", "--verify"]):
        failures.append("pins did not reproduce BEFORE the month: the copy is not a faithful copy")
    if step("snapshot", [py, "-m", "scripts.demo_revert", "snapshot", "--tag", TAG]):
        sys.exit("the snapshot failed; nothing was run")

    month = ["--month", MONTH, "--calendar-factor", "on", "--approved-by", "demo_revert_proof", "--expect-month", MONTH]
    for label, cmd in (("generate March sales", [py, "scripts/local_pipeline_qa.py", "synth"]),
                       ("decisions", [py, "-m", "scripts.practice_artefacts", "--settle-decisions"]),
                       ("run the month", [py, "-m", "scripts.run_month", *month])):
        if step(label, cmd):
            failures.append(f"the demonstration month stopped at: {label}")
            break
    else:
        conn2 = psycopg2.connect(url)
        cur = conn2.cursor()
        cur.execute("SELECT round(SUM(q_i)) FROM lp_recommendation WHERE planning_cycle_date = '2026-04-01' AND lp_run_key IS NOT NULL")
        pieces = int(cur.fetchone()[0])
        conn2.close()
        if step("close the month", [py, "-m", "scripts.run_month", *month, "--close", "--expect-plan-pieces", str(pieces)]):
            failures.append("the demonstration close stopped")

    conn3 = psycopg2.connect(url)
    cur = conn3.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    changed = compare(cur, read_manifest(cur, TAG))
    conn3.rollback()
    after_plan = plan_figures(conn3, "2026-04-01")
    conn3.close()
    print(f"\nafter the month: {len(changed)} table(s) differ from the snapshot; plan 2026-04 = {after_plan[0]} rows, {after_plan[1]:,} pieces")
    if not changed:
        failures.append("the month changed nothing, so the revert proved nothing")

    if step("revert", [py, "-m", "scripts.demo_revert", "revert", "--tag", TAG, "--yes"]):
        failures.append("the revert refused or rolled back")
    if step("verify identical", [py, "-m", "scripts.demo_revert", "verify", "--tag", TAG]):
        failures.append("tables differ after the revert")

    conn4 = psycopg2.connect(url)
    now_plan = plan_figures(conn4, CYCLE)
    cur = conn4.cursor()
    cur.execute("SELECT count(*) FROM lp_recommendation WHERE planning_cycle_date = '2026-04-01'")
    april_rows = cur.fetchone()[0]
    conn4.rollback()
    conn4.close()
    print(f"\nafter the revert: plan {CYCLE[:7]} = {now_plan[0]} rows, {now_plan[1]:,} pieces; 2026-04 rows left: {april_rows}")
    if now_plan != before_plan:
        failures.append(f"plan after the revert {now_plan} is not the plan before {before_plan}")
    if april_rows:
        failures.append(f"{april_rows} 2026-04 plan rows survived the revert")
    if step("pinned figures after the revert", [py, "-m", "scripts.snapshot_published_figures", "--verify"]):
        failures.append("pinned figures do not reproduce after the revert")
    if step("cross-endpoint invariants after the revert", [py, "-m", "pytest", "tests/invariants", "-q", "-p", "no:cacheprovider"]):
        failures.append("invariants fail after the revert")

    proof = {"passed": not failures, "failures": failures, "when": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "backup": args.backup, "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
             "plan_before": before_plan, "plan_after_revert": now_plan, "plan_during_month": after_plan, "tables_changed_by_month": changed}
    PROOF_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROOF_FILE.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print("\n" + ("PROOF PASSED" if not failures else "PROOF FAILED: " + "; ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
