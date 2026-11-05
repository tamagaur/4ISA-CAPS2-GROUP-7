"""scripts/demo_rehearsal.py - the attestation that THIS code loaded months and rolled them back exactly, on a restored copy (2026-11-06).

The gate of the brief: "if load, load, roll back and roll back do not restore a restored copy exactly at every step, nothing goes to live". The driver
scripts/month_load_rehearsal.py runs that cycle on a database restored from a backup, compares a fingerprint of every table, view and function at each
step, and calls write() only if every step was exact. The record carries a hash of the files that make the load and the rollback, so an edit to any
of them stops it counting until the cycle is rehearsed again.

It is COMMITTED (docs/MONTH_LOAD_REHEARSAL.json): a server that runs this commit has the attestation without a terminal, and nothing depends on an
environment variable, a flag or a file on one machine. It holds counts and fingerprints, no per-product figure (hard rule 9).
Read by scripts/demo_session.py (load and rollback refuse a database that is not the throwaway local server without it).
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROOF = REPO / "docs" / "MONTH_LOAD_REHEARSAL.json"
# What loading and rolling back a month is made of. An edit to any of these needs a new rehearsal.
FILES = (
    "analytics/demo_session.py",
    "analytics/month_file.py",
    "analytics/forecasting/practice_switch.py",
    "scripts/demo_session.py",
    "scripts/demo_revert.py",
    "scripts/demo_rehearsal.py",
    "scripts/run_month.py",
    "scripts/report_target.py",
    "scripts/cycle_feedback.py",
)
# The steps a rehearsal must have shown exact, in order (scripts/month_load_rehearsal.py).
STEPS = ("load_first", "load_second", "rollback_second", "rollback_first", "load_first_again", "load_second_again", "rollback_first_with_second_loaded",
         "load_first_third", "load_second_third", "third_month_refused_before_anything_changes", "crash_mid_run_then_rollback")


def code_hash() -> str:
    digest = hashlib.sha256()
    for name in FILES:
        digest.update(name.encode())
        digest.update((REPO / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def write(target: str, steps: dict, plan_start: tuple, backup: str) -> None:
    PROOF.parent.mkdir(parents=True, exist_ok=True)
    PROOF.write_text(json.dumps({
        "passed": True, "code_hash": code_hash(), "target": target, "backup": backup, "when": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_start": list(plan_start), "steps": steps}, indent=2), encoding="utf-8")


def ok() -> tuple[bool, str]:
    """(passed, why not). The record exists, passed, covered every step, was made on a database on a local machine, and its hash is the current code's."""
    try:
        found = json.loads(PROOF.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "no rehearsal on record (docs/MONTH_LOAD_REHEARSAL.json): run python -m scripts.month_load_rehearsal on a restored copy first"
    if found.get("passed") is not True:
        return False, "the rehearsal on record did not pass"
    if not str(found.get("target", "")).startswith(("127.0.0.1/", "localhost/")):
        return False, "the rehearsal on record was not made on a restored copy"
    if [s for s in STEPS if not (found.get("steps") or {}).get(s, {}).get("exact")]:
        return False, "the rehearsal on record did not show every step exact"
    if found.get("code_hash") != code_hash():
        return False, "the load and rollback code changed after its rehearsal: rehearse it again on a restored copy"
    return True, ""
