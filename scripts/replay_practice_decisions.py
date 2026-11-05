"""
scripts/replay_practice_decisions.py - carry the Reorder page's decisions onto the practice copy (2026-11-04).

    python -m scripts.replay_practice_decisions --cycle 2026-03 --json            # compares, writes nothing
    python -m scripts.replay_practice_decisions --cycle 2026-03 --write --json    # replays through decide_row

WHY IT EXISTS. On the local setup the pages use ssm_local and the monthly batch uses ssm_practice (backend/routers/monthly_batch.py
step_env), so a decision made on the Reorder page never reached the plan the batch makes. No page can read ssm_practice (CLAUDE.md
rule 2, arrangement 3), so the page cannot write there directly. On a single database, as on live, this script has nothing to do.

HOW. The source is the pages' database, and only its decisions are read. A decision is written to the practice copy by the one
place that writes decisions, recommendations.decide_row: same guards, same planning-mart copy, same receipt ledger, with the
original person, time, reason and quantity, so the receipt falls due on the same date. A decision undone on the page is undone here
by the real reversal, reorder_approval.reverse_decision. There is no SQL UPDATE of a recommendation in this file.

IT IS SAFE TO RUN AGAIN. A row already holding the same decision is left alone, so nothing is applied twice. A row that does not
match (another product, cycle or quantity), or is on one side only, is reported and left pending, so the safeguard keeps refusing
rather than guessing. Each row is its own transaction. Once the next plan exists on the practice copy the cycle is over and nothing
is replayed. It touches the recommendation rows of this one cycle, their receipts, their planning-mart rows and the audit log, never
sales or stock, so generated sales survive.

It refuses to run unless the source and the target are two different databases on the throwaway server (scripts/local_pg.py), so it
cannot reach live. Provisional, for Yuan's review: docs/MONTHLY_BATCH_REVIEW.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.close_cycle import PRINCIPAL, cycle_params, parse_cycle, transaction  # noqa: E402

PAGES_URL_ENV = "BATCH_PAGES_DB_URL"
THROWAWAY = ("127.0.0.1", 55432)        # scripts/local_pg.py
PRACTICE_PATH = "/ssm_practice"         # scripts/local_pg.py PRACTICE_DB
REVERSAL_REASON = "Reversed on the Reorder page; carried onto the practice copy."
ROWS_SQL = """
    SELECT lr.recommendation_key, lr.product_key, lr.planning_cycle_date, lr.q_i, lr.status, lr.decided_q_i, lr.decision_reason,
           lr.decided_by, lr.decided_at
    FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE pd.principal = %(principal)s AND lr.planning_cycle_date = %(cycle)s
"""
NEWEST_CYCLE_SQL = """
    SELECT MAX(lr.planning_cycle_date) FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE pd.principal = %(principal)s
"""


def separate_databases(pages_url: str | None, practice_url: str | None) -> bool:
    """True only for two different databases, both on the throwaway server, the target being the practice copy."""
    pages, practice = urlparse(pages_url or ""), urlparse(practice_url or "")
    return ((pages.hostname, pages.port) == THROWAWAY and (practice.hostname, practice.port) == THROWAWAY
            and practice.path == PRACTICE_PATH and pages.path not in ("", "/", practice.path))


def _quantity(value) -> float | None:
    return None if value is None else round(float(value), 2)


def same_row(a: dict, b: dict) -> bool:
    """The same recommendation on both sides. q_i belongs here: another LP run behind the same key is another decision."""
    return (a["product_key"] == b["product_key"] and a["planning_cycle_date"] == b["planning_cycle_date"]
            and _quantity(a["q_i"]) == _quantity(b["q_i"]))


def same_decision(a: dict, b: dict) -> bool:
    return a["status"] == b["status"] and _quantity(a["decided_q_i"]) == _quantity(b["decided_q_i"])


@dataclass
class Plan:
    apply: list[int] = field(default_factory=list)      # decided on the page, not on the copy
    reverse: list[int] = field(default_factory=list)    # decided on the copy; the page says otherwise now
    already: list[int] = field(default_factory=list)    # the same decision on both sides
    pending: list[int] = field(default_factory=list)    # pending on both sides
    mismatched: list[int] = field(default_factory=list)  # a different row behind the same key
    missing: list[int] = field(default_factory=list)    # on the page, not on the copy
    only_in_practice: list[int] = field(default_factory=list)


def plan_replay(pages: dict[int, dict], practice: dict[int, dict]) -> Plan:
    """What to do for each row. Pure: every decision about safety is made here, before anything is written."""
    plan = Plan()
    for key, page in sorted(pages.items()):
        copy = practice.get(key)
        if copy is None:
            plan.missing.append(key)
        elif not same_row(page, copy):
            plan.mismatched.append(key)
        elif same_decision(page, copy):
            (plan.pending if page["status"] == "pending" else plan.already).append(key)
        else:
            if copy["status"] != "pending":
                plan.reverse.append(key)
            if page["status"] != "pending":
                plan.apply.append(key)
    plan.only_in_practice = sorted(set(practice) - set(pages))
    return plan


def apply_plan(plan: Plan, pages: dict[int, dict], reverse, decide) -> dict:
    """Carries the plan out, reversals first, so a changed decision ends as the page has it. `reverse(key)` and `decide(key, row)` do
    one row in its own transaction. A row that fails stays as it was and is named, and the safeguard keeps counting it."""
    done = {"applied": 0, "reversed": 0, "refused": []}
    blocked = set()
    for key in plan.reverse:
        try:
            reverse(key)
            done["reversed"] += 1
        except Exception as exc:  # noqa: BLE001 - one row's refusal must not stop the others
            blocked.add(key)
            done["refused"].append({"recommendation_key": key, "why": _why(exc)})
    for key in plan.apply:
        if key in blocked:
            continue
        try:
            decide(key, pages[key])
            done["applied"] += 1
        except Exception as exc:  # noqa: BLE001 - one row's refusal must not stop the others
            done["refused"].append({"recommendation_key": key, "why": _why(exc)})
    return done


def _why(exc: Exception) -> str:
    return str(getattr(exc, "detail", None) or type(exc).__name__)[:200]


def _read_side(url: str, params: dict) -> tuple[dict[int, dict], dict, object]:
    """The cycle's rows, the decision counts and the principal's newest cycle, in one read-only transaction."""
    import psycopg2

    from scripts.run_month import read_decisions
    conn = psycopg2.connect(url)
    try:
        with transaction(conn, "public", read_only=True) as cur:
            cur.execute(ROWS_SQL, params)
            names = [c[0] for c in cur.description]
            rows = {row[0]: dict(zip(names, row)) for row in cur.fetchall()}
            decisions = read_decisions(cur, params)
            cur.execute(NEWEST_CYCLE_SQL, params)
            newest = cur.fetchone()[0]
    finally:
        conn.close()
    return rows, decisions, newest


def _summary(month, plan: Plan, pages_decisions: dict, state: str) -> dict:
    return {"cycle": f"{month:%Y-%m}", "state": state, "to_apply": len(plan.apply), "to_reverse": len(plan.reverse),
            "already": len(plan.already), "pending": len(plan.pending), "mismatched": len(plan.mismatched),
            "missing": len(plan.missing), "only_in_practice": len(plan.only_in_practice), "applied": 0, "reversed": 0, "refused": [],
            "pages": pages_decisions}


def compare(month, pages_url: str, practice_url: str) -> tuple[Plan, dict, dict]:
    """Reads both sides and writes nothing. Returns the plan, its summary and the page's rows."""
    params = cycle_params(month, PRINCIPAL)
    pages, pages_decisions, _ = _read_side(pages_url, params)
    practice, _, newest = _read_side(practice_url, params)
    if newest is not None and newest > month:
        # The next plan exists on the copy: this cycle's rows can no longer be decided there, so there is nothing to carry over.
        return Plan(), _summary(month, Plan(), pages_decisions, "plan_already_written"), pages
    plan = plan_replay(pages, practice)
    return plan, _summary(month, plan, pages_decisions, "compared"), pages


def preview_if_separate(month) -> dict | None:
    """For scripts/batch_status.py: the comparison where the pages have their own database, else None. Read-only."""
    pages_url, practice_url = os.environ.get(PAGES_URL_ENV), os.environ.get("SUPABASE_DB_URL")
    if not separate_databases(pages_url, practice_url):
        return None
    return compare(month, pages_url, practice_url)[1]


def accept_as_recommended(db, present: dict, key: int, by: str):
    """One row accepted at the recommended quantity, through decide_row. For scripts/practice_artefacts.py, a check with no person to
    decide. The caller commits."""
    from backend.routers import recommendations as rec
    return rec.decide_row(db, present, key=key, status="accepted", reason=None, decided_quantity=None, decided_by=by)


def _writers(practice_url: str):
    """(reverse, decide): the real functions, on a session bound to the practice copy. Imported here: only a write needs them."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend import audit
    from backend.auth_utils import TokenPayload
    from backend.routers import recommendations as rec
    from backend.routers import reorder_approval as approval
    from backend.schemas.recommendations import ReverseRequest

    engine = create_engine(practice_url)
    actor = TokenPayload(user_id=0, email="practice-replay@local", role="admin", full_name="Practice replay", session_id=None)

    def reverse(key: int) -> None:
        with Session(engine) as db:
            approval.reverse_decision(key, ReverseRequest(reason=REVERSAL_REASON), db=db, admin=actor)

    def decide(key: int, row: dict) -> None:
        with Session(engine) as db:
            decided = rec.decide_row(db, rec._present(db), key=key, status=row["status"], reason=row["decision_reason"],
                                     decided_quantity=_quantity(row["decided_q_i"]), decided_by=row["decided_by"],
                                     decided_at=row["decided_at"])
            quantity = f", quantity {_quantity(row['decided_q_i']):g}" if row["decided_q_i"] is not None else ""
            audit.record(db, "Reorder Decision Replayed To Practice",
                         f"SKU {decided['sku']}: {row['status']}{quantity}, decided by {row['decided_by']} on the Reorder page",
                         email=row["decided_by"], name=None, role="practice_replay")
            db.commit()

    return reverse, decide


def replay(month, pages_url: str, practice_url: str) -> dict:
    plan, summary, pages = compare(month, pages_url, practice_url)
    if plan.apply or plan.reverse:
        reverse, decide = _writers(practice_url)
        summary.update(apply_plan(plan, pages, reverse, decide))
    summary["state"] = "replayed" if summary["state"] == "compared" else summary["state"]
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cycle", required=True, type=parse_cycle, help="the planning month, YYYY-MM")
    ap.add_argument("--write", action="store_true", help="replay; without it this only compares")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    pages_url, practice_url = os.environ.get(PAGES_URL_ENV), os.environ.get("SUPABASE_DB_URL")
    if not separate_databases(pages_url, practice_url):
        print(f"REFUSED: {PAGES_URL_ENV} and SUPABASE_DB_URL must be two databases on the throwaway server, the target being ssm_practice")
        return 2
    summary = replay(args.cycle, pages_url, practice_url) if args.write else compare(args.cycle, pages_url, practice_url)[1]
    print(json.dumps(summary) if args.json else summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
