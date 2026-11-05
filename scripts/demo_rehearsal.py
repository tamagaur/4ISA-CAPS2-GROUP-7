"""scripts/demo_rehearsal.py - the record that THIS code ran a whole demonstration month and undid it on a restored copy (2026-11-05).

The gate of the brief: "if load, run and undo do not restore a restored copy exactly, nothing goes to live". scripts/demo_session.py undo writes this record
when, and only when, it undid a month that really ran (the load, the ABC, the forecast, the plan and the marts all changed tables), on a database on this
machine, and every table, view and function then equalled the snapshot. The record carries a hash of the files that make the window, the load, the run and
the undo. A later edit to any of them changes the hash, so the record stops counting: a change has to be rehearsed again, on a restored copy, before live.

Read by scripts/demo_session.py (open, load, run and undo refuse a database that is not on this machine without it) and backend/routers/live_demo.py (the
routes do not mount without it). It is git-ignored (local/), per machine, like local/demo_revert_proof.json.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROOF = REPO / "local" / "demo_session_rehearsal.json"
# What the demonstration is made of. An edit to any of these needs a new rehearsal.
FILES = (
    "analytics/demo_session.py",
    "analytics/forecasting/practice_switch.py",
    "scripts/demo_session.py",
    "scripts/demo_revert.py",
    "scripts/run_month.py",
    "scripts/report_target.py",
    "scripts/cycle_feedback.py",
    "backend/routers/live_demo.py",
)
# Tables a real month changes. All of them must have changed in the rehearsal, else it rehearsed a load and nothing more.
MUST_HAVE_CHANGED = ("public.unilever_sku_demand_fact", "public.forecast_result", "public.lp_recommendation",
                     "public.lp_run", "mart.planning_mart", "mart.sales_mart")


def code_hash() -> str:
    digest = hashlib.sha256()
    for name in FILES:
        digest.update(name.encode())
        digest.update((REPO / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def month_really_ran(touched: list[str]) -> list[str]:
    """The tables a real month changes that this undo did NOT put back (so did not change): empty when the rehearsal was a whole month."""
    changed = {line.split(":", 1)[0] for line in touched}
    return [t for t in MUST_HAVE_CHANGED if t not in changed]


def write(target: str, base: tuple, after: tuple, touched: list[str]) -> None:
    PROOF.parent.mkdir(parents=True, exist_ok=True)
    PROOF.write_text(json.dumps({"passed": True, "code_hash": code_hash(), "target": target, "when": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                 "plan_before": list(base), "plan_after_undo": list(after), "tables_changed_then_put_back": touched}, indent=2), encoding="utf-8")


def ok() -> tuple[bool, str]:
    """(passed, why not). The record exists, passed, was made on this machine, and its hash is the current code's."""
    try:
        found = json.loads(PROOF.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "no rehearsal on record: run the whole cycle on a restored copy first (python -m scripts.live_demo_app --rehearsal)"
    if found.get("passed") is not True:
        return False, "the rehearsal on record did not pass"
    if not str(found.get("target", "")).startswith(("127.0.0.1/", "localhost/")):
        return False, "the rehearsal on record was not made on a database on this machine"
    if found.get("code_hash") != code_hash():
        return False, "the demonstration code changed after its rehearsal: rehearse it again on a restored copy"
    return True, ""
