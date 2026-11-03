"""
scripts/optin_run.py - run the 18 opt-in database tests on a disposable database, report each, tear down (2026-11-03).

    scripts/check.sh --optin                 the one command
    python -m scripts.optin_run [--seed BACKUP_DIR] [--keep]

Never reads or writes live. Every connection goes to 127.0.0.1:55432, enforced by scripts/optin_guard.py in this process and in
every child; a run in which anything tried to connect elsewhere fails, even if every test passed.

What each test needs, and what provides it:
  17 tests/etl/test_fills_db.py          FILLS_SCRATCH_SCHEMA: a filled rehearsal schema. scripts/rehearse_fills --build clones the
                                         database's public into ssm_fills, then scripts/fill_missing fills it.
   1 tests/etl/test_rollover_scratch.py  ROLLOVER_SCRATCH=1. It clones the connected database's public, so on a throwaway server it
                                         needs a public worth cloning: real rows, the plan of 109 rows and 435,988 pieces, no pending
                                         migration. The SEED provides them.

The seed is a database backup already on this machine (backups/, git-ignored, it holds client rows): scripts/local_pg.restore loads
it into a database of its own, OPTIN_DB, so ssm_local and ssm_practice are left alone. Migrations newer than the backup are applied
to that copy through the normal runner. The seed is read from disk: nothing is fetched from live, so these tests run on the data of
the backup's date. A machine with no backup fails here, loudly; it does not skip.

This proves the tests pass on a disposable copy. It does not prove they would pass against live, where they must never run.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from dotenv import dotenv_values

from scripts import optin_guard
from scripts.check_helpers import covered_by_optin

REPO = Path(__file__).resolve().parents[1]
OPTIN_DB = "ssm_optin"
FILLS_SCHEMA = "ssm_fills"
SEED = REPO / "backups" / "full_backup_20261102T170343Z"   # the newest database backup, taken just before 0073 was applied to live
SEED_PLAN = (109, 435988.0)                                 # lp_run 6, cycle 2026-03: the plan the rollover test pins
KEPT_FROM_DOTENV = {"JWT_SECRET_KEY", "JWT_ALGORITHM", "JWT_EXPIRY_HOURS", "CORS_ALLOWED_ORIGINS"}   # no destination in them
TEST_FILES = ("tests/etl/test_fills_db.py", "tests/etl/test_rollover_scratch.py")


def child_env(url: str, dotenv: Path = REPO / ".env") -> dict[str, str]:
    """The child's environment: the throwaway URL under every name the code reads, and every other .env value blanked unless it is
    known to hold no destination. load_dotenv(override=False) leaves a key that is already set, even empty, so .env cannot refill it."""
    optin_guard.require_throwaway(url)
    env = dict(os.environ)
    env.update({k: "" for k in dotenv_values(dotenv) if k not in KEPT_FROM_DOTENV})
    env.update(LOCAL_PG_URL=url, SUPABASE_DB_URL=url, SUPABASE_DIRECT_URL=url, DATABASE_URL=url, SUPABASE_KEY="local-dummy",
               PYTHONIOENCODING="utf-8", PYTHONPATH=str(REPO))
    return env


def read_outcomes(junit: Path, want: list[str]) -> tuple[dict[str, str], bool]:
    """({test id: PASS | FAIL | SKIPPED | NOT RUN}, every listed test passed and nothing else ran)."""
    got = {}
    for c in ET.parse(junit).getroot().iter("testcase"):
        tid = f"{c.get('classname')}::{c.get('name')}"
        got[tid] = ("SKIPPED" if c.find("skipped") is not None else
                    "FAIL" if c.find("failure") is not None or c.find("error") is not None else "PASS")
    outcomes = {t: got.get(t, "NOT RUN") for t in want}
    extra = {t: f"{v} (not on the list)" for t, v in got.items() if t not in outcomes}
    return {**outcomes, **extra}, not extra and all(v == "PASS" for v in outcomes.values())


def _guarded(env: dict, module: str, *args: str) -> int:
    print(f"\n--- {module} {' '.join(args)}", flush=True)
    return subprocess.call([sys.executable, "-m", "scripts.optin_guard", module, *args], cwd=REPO, env=env)


def _server_says(env: dict) -> tuple:
    import psycopg2
    conn = psycopg2.connect(env["SUPABASE_DB_URL"])
    try:
        cur = conn.cursor()
        cur.execute("SELECT inet_server_port(), current_database()")
        where = cur.fetchone()
        cur.execute("SELECT COUNT(*), SUM(q_i) FROM public.lp_recommendation WHERE planning_cycle_date = DATE '2026-03-01' AND lp_run_key = 6")
        rows, pieces = cur.fetchone()
        return where, (rows, float(pieces or 0))
    finally:
        conn.close()


def run(seed: Path, keep: bool) -> int:
    optin_guard.install()
    from scripts import local_pg

    want = covered_by_optin()
    if not (seed / "structure").is_dir():
        print(f"FAIL: the seed {seed} is not on this machine, so nothing was run. Pass another backup with --seed.")
        return 1
    url = local_pg.local_url(db=OPTIN_DB)
    with tempfile.TemporaryDirectory() as tmp:
        refused = Path(tmp) / "refused.log"
        env = {**child_env(url), optin_guard.LOG_VAR: str(refused)}
        os.environ[optin_guard.LOG_VAR] = str(refused)
        was_up = local_pg.is_up()
        local_pg.start()
        try:
            print(f"seed: {seed.name}; database: {OPTIN_DB} on 127.0.0.1:{local_pg.PORT} (server {'already up' if was_up else 'started here'})", flush=True)
            problems = local_pg.restore(seed, db=OPTIN_DB)
            if problems:
                print(f"FAIL: the seed did not load cleanly: {problems[:5]}")
                return 1
            if _guarded(env, "scripts.run_canonical_load", "--schema", "public", "--target-public", "--schema-only") != 0:
                print("FAIL: could not apply the pending migrations to the copy")
                return 1
            where, plan = _server_says(env)
            print(f"\nthe server says {where}; the copy's plan is {plan[0]} rows, {plan[1]:,.0f} pieces", flush=True)
            if where != (local_pg.PORT, OPTIN_DB):
                print(f"FAIL: expected the server to be {local_pg.PORT}/{OPTIN_DB}")
                return 1
            if plan != SEED_PLAN:
                print(f"FAIL: the seed's plan is not {SEED_PLAN}, so the rollover test's pin does not describe it")
                return 1
            if _guarded(env, "scripts.rehearse_fills", "--schema", FILLS_SCHEMA, "--build") != 0:
                print("FAIL: could not build the rehearsal schema")
                return 1
            if _guarded(env, "scripts.fill_missing", "--schema", FILLS_SCHEMA) != 0:
                print("FAIL: could not fill the rehearsal schema")
                return 1
            junit = Path(tmp) / "optin.xml"
            test_env = {**env, "FILLS_SCRATCH_SCHEMA": FILLS_SCHEMA, "ROLLOVER_SCRATCH": "1"}
            _guarded(test_env, "pytest", "-q", "-p", "no:cacheprovider", "-rs", f"--junitxml={junit}", *TEST_FILES)
            if not junit.exists():
                print("FAIL: pytest wrote no result file")
                return 1
            outcomes, ok = read_outcomes(junit, want)
            print(f"\n================ check.sh --optin: {OPTIN_DB} on 127.0.0.1:{local_pg.PORT}, seeded from {seed.name}")
            for tid, outcome in outcomes.items():
                print(f"  {outcome:<8} {tid}")
            passed = sum(v == "PASS" for v in outcomes.values())
            print(f"  {passed} of {len(want)} passed")
            attempts = refused.read_text(encoding="utf-8").splitlines() if refused.exists() else []
            if attempts:
                print(f"FAIL: {len(attempts)} connection(s) to somewhere else were attempted and refused: {sorted(set(attempts))}")
                return 1
            print("  connections refused by the guard: 0")
            if not ok:
                print("RED: not every listed test passed. Skipped is not passed.")
                return 1
            print("GREEN on a disposable database. This does not show they would pass against live, where they must never run.")
            return 0
        finally:
            if keep:
                print(f"--keep: {OPTIN_DB} left on 127.0.0.1:{local_pg.PORT}")
            else:
                # In the finally, so a failed test, a failed step or an exception all drop it. A database still there fails the run.
                dropped = local_pg.drop_database(OPTIN_DB)
                print(f"teardown: {OPTIN_DB} {'dropped' if dropped else 'NOT dropped'}", end="")
                if was_up:
                    print("; the server was already up, so it stays up")
                else:
                    local_pg.stop()
                    print("; server stopped")
                if not dropped:
                    sys.exit(f"FAIL: could not drop {OPTIN_DB} on 127.0.0.1:{local_pg.PORT}. Drop it by hand.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=Path, default=SEED)
    ap.add_argument("--keep", action="store_true", help="leave the database for inspection")
    a = ap.parse_args()
    return run(a.seed, a.keep)


if __name__ == "__main__":
    sys.exit(main())
