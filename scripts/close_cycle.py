"""
scripts/close_cycle.py - close a planning cycle, and reopen it (migration 0069, docs/ROLLOVER_DESIGN.md section d).

    python -m scripts.close_cycle --cycle 2026-03                   # DRY RUN (the default): reads, prints, writes nothing
    python -m scripts.close_cycle --cycle 2026-03 --approved-by NAME --expect-cycle 2026-03 --target-public
    python -m scripts.close_cycle --cycle 2026-03 --reopen --approved-by NAME --expect-cycle 2026-03 --target-public

WHAT A CLOSE IS. Cycle 2026-03 is the plan made from the February count. Closing it, after the April plan exists,
(1) settles its accepted orders' receipts against the March count (analytics/receipt_settlement.py), (2) marks every
row of the cycle closed (lp_recommendation.closed_at: the row and its decision are kept exactly as they were, nothing
is deleted), and (3) records the cycle in planning_cycle (state closed, who, when, how its opening stock was obtained).

WHAT IT DOES NOT DO. It does not run the ABC, the forecast or the LP. Those have their own gates and flags
(orchestrate_abc, run_baseline_forecast --write, run_lp), so a close VERIFIES that they have run for the next cycle
and refuses to write if any has not. The dry run prints that table. This is the existing pipeline's status,
not a new scheduler.

Writing happens only with --approved-by NAME and --expect-cycle YYYY-MM, and the expected cycle must equal --cycle
(the gate pattern of scripts/clean_dead_skus.py). On public it also needs --target-public.

IF A STEP FAILS MIDWAY. The close is a short state machine on planning_cycle, each step in its own committed transaction:
    open --(close starts)--> closing --(settle_receipts, close_plan)--> closing --(record)--> closed
steps_done lists the steps that completed. A failure leaves the cycle in 'closing' with exactly the finished steps
done, and nothing half-written inside a step (each is one transaction). Running the same command again RESUMES: it
skips the finished steps and does the rest. Nothing is ever deleted, so every step is undoable:
    --reopen puts a closing OR closed cycle back to open without a database restore: receipts this close settled
    return to expected (settled_by_*, not_visible_in_count, stock_change_pieces cleared), lp_recommendation.closed_at
    goes back to NULL, planning_cycle returns to open with reopen_count + 1, reopened_by and reopened_at.
Running a close twice changes nothing the second time: a closed cycle is reported and left untouched.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analytics import receipt_settlement  # noqa: E402

PRINCIPAL = "unilever"          # Del Monte has no per-product plan to close

# --- what a close verifies (the existing pipeline's steps) --------------------------------------------------------
CHECKS = {
    "count_loaded": ("the stock count of the cycle's month is loaded",
                     "SELECT EXISTS (SELECT 1 FROM inventory_fact_real WHERE principal = %(principal)s AND _period = %(period)s)"),
    "sales_loaded": ("the cycle's month of per-SKU sales is loaded",
                     "SELECT EXISTS (SELECT 1 FROM Unilever_SKU_Demand_Fact_Real WHERE calendar_month = %(period)s)"),
    "abc_run": ("the ABC run for that month is stored",
                "SELECT EXISTS (SELECT 1 FROM abc_classification WHERE principal = %(principal)s "
                "AND classification_period = %(period)s)"),
    "forecast_next": ("the forecast for the next cycle is written",
                      "SELECT EXISTS (SELECT 1 FROM forecast_result WHERE forecast_date = %(next_cycle)s)"),
    "lp_next": ("the LP run for the next cycle is written",
                "SELECT EXISTS (SELECT 1 FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key "
                "WHERE pd.principal = %(principal)s AND lr.planning_cycle_date = %(next_cycle)s AND lr.lp_run_key IS NOT NULL)"),
}

CYCLE_SQL = """
    SELECT state, steps_done, closing_started_by, closing_started_at, closed_by, closed_at, reopened_by, reopened_at, reopen_count
    FROM planning_cycle WHERE principal = %(principal)s AND cycle = %(cycle)s
"""
ENSURE_SQL = """
    INSERT INTO planning_cycle (principal, cycle) VALUES (%(principal)s, %(cycle)s) ON CONFLICT (principal, cycle) DO NOTHING
"""
START_SQL = """
    UPDATE planning_cycle SET state = 'closing', closing_started_by = %(by)s, closing_started_at = now()
    WHERE principal = %(principal)s AND cycle = %(cycle)s AND state = 'open'
"""
STEP_DONE_SQL = """
    UPDATE planning_cycle SET steps_done = array_append(steps_done, %(step)s)
    WHERE principal = %(principal)s AND cycle = %(cycle)s AND NOT (%(step)s = ANY(steps_done))
"""
CLOSE_PLAN_SQL = """
    UPDATE lp_recommendation lr SET closed_at = now()
    FROM product_dimension pd
    WHERE pd.product_key = lr.product_key AND pd.principal = %(principal)s
      AND lr.planning_cycle_date = %(cycle)s AND lr.closed_at IS NULL
"""
RECORD_SQL = """
    UPDATE planning_cycle pc
    SET state = 'closed', closed_by = %(by)s, closed_at = now(),
        opening_basis = r.basis, opening_count_period = r.count_period, opening_count_date = r.count_date,
        lp_run_key = r.run_key
    FROM (SELECT (SELECT run_key FROM lp_run WHERE planning_cycle_date = %(cycle)s ORDER BY run_key DESC LIMIT 1) AS run_key,
                 (SELECT inputs -> 'stock_counts' -> %(principal)s ->> 'opening_basis' FROM lp_run
                  WHERE planning_cycle_date = %(cycle)s ORDER BY run_key DESC LIMIT 1) AS basis,
                 (SELECT inputs -> 'stock_counts' -> %(principal)s ->> 'period' FROM lp_run
                  WHERE planning_cycle_date = %(cycle)s ORDER BY run_key DESC LIMIT 1) AS count_period,
                 (SELECT (inputs -> 'stock_counts' -> %(principal)s ->> 'counted_on')::date FROM lp_run
                  WHERE planning_cycle_date = %(cycle)s ORDER BY run_key DESC LIMIT 1) AS count_date) r
    WHERE pc.principal = %(principal)s AND pc.cycle = %(cycle)s AND pc.state = 'closing'
"""
# --- reopening ----------------------------------------------------------------------------------------------------
UNSETTLE_SQL = """
    UPDATE expected_receipt er
    SET state = 'expected', settled_by_period = NULL, settled_by_count_date = NULL, settled_at = NULL,
        not_visible_in_count = false, stock_change_pieces = NULL
    FROM planning_cycle pc
    WHERE pc.principal = %(principal)s AND pc.cycle = %(cycle)s
      AND er.state = 'arrived_in_count' AND er.settled_by_period = %(period)s
      AND pc.closing_started_at IS NOT NULL AND er.settled_at >= pc.closing_started_at
"""
REOPEN_PLAN_SQL = """
    UPDATE lp_recommendation lr SET closed_at = NULL
    FROM product_dimension pd
    WHERE pd.product_key = lr.product_key AND pd.principal = %(principal)s
      AND lr.planning_cycle_date = %(cycle)s AND lr.closed_at IS NOT NULL
"""
REOPEN_CYCLE_SQL = """
    UPDATE planning_cycle
    SET state = 'open', steps_done = '{}', closing_started_by = NULL, closing_started_at = NULL, closed_by = NULL,
        closed_at = NULL, opening_basis = NULL, opening_count_period = NULL, opening_count_date = NULL, lp_run_key = NULL,
        reopened_by = %(by)s, reopened_at = now(), reopen_count = reopen_count + 1
    WHERE principal = %(principal)s AND cycle = %(cycle)s AND state IN ('closing', 'closed')
"""
STEPS = ("settle_receipts", "close_plan")


def cycle_params(cycle: datetime.date, principal: str = PRINCIPAL) -> dict:
    nxt = datetime.date(cycle.year + (cycle.month == 12), cycle.month % 12 + 1, 1)
    return {"principal": principal, "cycle": cycle, "next_cycle": nxt, "period": f"{cycle.year}-{cycle.month:02d}"}


def parse_cycle(text_: str) -> datetime.date:
    try:
        d = datetime.date.fromisoformat(text_ + "-01" if len(text_) == 7 else text_)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text_!r} is not a month (YYYY-MM)")
    if d.day != 1:
        raise argparse.ArgumentTypeError("a cycle is the first of a month")
    return d


def read_status(cur, params: dict) -> dict:
    """{check: bool}, the cycle's planning_cycle row (or None) and how many rows it has, all read-only."""
    checks = {}
    for name, (_, sql) in CHECKS.items():
        cur.execute(sql, params)
        checks[name] = bool(cur.fetchone()[0])
    cur.execute("SELECT to_regclass('planning_cycle') IS NOT NULL")
    present = bool(cur.fetchone()[0])
    row = None
    if present:
        cur.execute(CYCLE_SQL, params)
        r = cur.fetchone()
        if r:
            row = dict(zip(("state", "steps_done", "closing_started_by", "closing_started_at", "closed_by", "closed_at",
                            "reopened_by", "reopened_at", "reopen_count"), r))
    cur.execute("""SELECT COUNT(*), COUNT(*) FILTER (WHERE lr.closed_at IS NOT NULL),
                          COUNT(*) FILTER (WHERE lr.status <> 'pending')
                   FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
                   WHERE pd.principal = %(principal)s AND lr.planning_cycle_date = %(cycle)s""", params)
    rows, closed_rows, decided = cur.fetchone()
    return {"checks": checks, "cycle_row": row, "ledger_present": present, "rows": rows, "closed_rows": closed_rows,
            "decided_rows": decided}


def missing_checks(status: dict) -> list[str]:
    return [CHECKS[k][0] for k, ok in status["checks"].items() if not ok]


@contextlib.contextmanager
def transaction(conn, schema: str, read_only: bool = False):
    """One committed transaction (or a read-only one that rolls back). search_path is transaction-local (hard rule 7)."""
    cur = conn.cursor()
    cur.execute("BEGIN")
    if schema != "public":
        cur.execute("SELECT set_config('search_path', %s, true)", (schema,))   # the scratch schema ALONE: a missing table fails, never falls back to public
    if read_only:
        cur.execute("SET TRANSACTION READ ONLY")
    try:
        yield cur
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.rollback() if read_only else conn.commit()


def describe(status: dict, params: dict) -> list[str]:
    lines = [f"cycle {params['cycle']} ({params['principal']}); next cycle {params['next_cycle']}; count and sales month {params['period']}"]
    for name, (label, _) in CHECKS.items():
        lines.append(f"  [{'done' if status['checks'][name] else 'MISSING'}] {label}")
    row = status["cycle_row"]
    lines.append(f"  cycle row: {row['state'] + ', steps done ' + str(row['steps_done']) if row else 'none yet (open)'}")
    lines.append(f"  plan rows: {status['rows']} ({status['decided_rows']} decided, {status['closed_rows']} already closed)")
    return lines


def close(conn, schema: str, params: dict, by: str, write: bool, out=print) -> dict:
    """Close the cycle (or only describe what a close would do when write is False). Returns what happened."""
    result = {"cycle": params["cycle"], "action": "dry_run" if not write else "closed", "steps": [], "changed": False}
    with transaction(conn, schema, read_only=True) as cur:
        status = read_status(cur, params)
    for line in describe(status, params):
        out(line)
    if not status["ledger_present"]:
        raise SystemExit("planning_cycle does not exist: migration 0069 is not applied")
    row = status["cycle_row"]
    if row and row["state"] == "closed":
        result.update(action="already_closed", changed=False)
        out(f"already closed by {row['closed_by']} at {row['closed_at']}: nothing changed")
        return result
    missing = missing_checks(status)
    if missing:
        result.update(action="refused", reason=missing)
        out("REFUSED: " + "; ".join(missing) + ". A close verifies the pipeline has run, it does not run it.")
        if write:
            raise SystemExit(2)
        return result
    if status["rows"] == 0:
        result.update(action="refused", reason=["the cycle has no plan rows"])
        out("REFUSED: the cycle has no plan rows")
        if write:
            raise SystemExit(2)
        return result
    if not write:
        out("dry run: would settle receipts against the count, close "
            f"{status['rows'] - status['closed_rows']} plan rows (decisions kept) and record the cycle closed. Nothing written.")
        return result
    done = list(row["steps_done"]) if row else []
    with transaction(conn, schema) as cur:                       # state: open -> closing (committed before any work)
        cur.execute(ENSURE_SQL, params)
        cur.execute(START_SQL, {**params, "by": by})
    if "settle_receipts" not in done:
        with transaction(conn, schema) as cur:
            settled = receipt_settlement.settle(cur, params["period"], write=True)
            cur.execute(STEP_DONE_SQL, {**params, "step": "settle_receipts"})
        result["steps"].append(("settle_receipts", settled["settles"]))
        out(f"step settle_receipts: {settled['settles']} receipt(s) settled, {settled['not_visible']} not visible in the count")
    if "close_plan" not in done:
        with transaction(conn, schema) as cur:
            cur.execute(CLOSE_PLAN_SQL, params)
            closed = cur.rowcount
            cur.execute(STEP_DONE_SQL, {**params, "step": "close_plan"})
        result["steps"].append(("close_plan", closed))
        out(f"step close_plan: {closed} plan row(s) closed, decisions untouched")
    with transaction(conn, schema) as cur:
        cur.execute(RECORD_SQL, {**params, "by": by})
    result["changed"] = True
    out(f"closed by {by}")
    return result


def reopen(conn, schema: str, params: dict, by: str, write: bool, out=print) -> dict:
    """Put a closing or closed cycle back to open. No restore needed: nothing was deleted, so each step is undone."""
    result = {"cycle": params["cycle"], "action": "dry_run" if not write else "reopened", "changed": False}
    with transaction(conn, schema, read_only=True) as cur:
        status = read_status(cur, params)
    for line in describe(status, params):
        out(line)
    row = status["cycle_row"]
    if not row or row["state"] == "open":
        result["action"] = "nothing_to_reopen"
        out("the cycle is open: nothing to reopen")
        return result
    if not write:
        out("dry run: would return settled receipts to expected, clear closed_at on the plan rows, and set the cycle open. Nothing written.")
        return result
    with transaction(conn, schema) as cur:                        # one transaction: all three undone together or none
        cur.execute(UNSETTLE_SQL, params)
        receipts = cur.rowcount
        cur.execute(REOPEN_PLAN_SQL, params)
        rows = cur.rowcount
        cur.execute(REOPEN_CYCLE_SQL, {**params, "by": by})
    result.update(changed=True, receipts_unsettled=receipts, rows_reopened=rows)
    out(f"reopened by {by}: {receipts} receipt(s) back to expected, {rows} plan row(s) reopened")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cycle", required=True, type=parse_cycle, help="the planning month to close, YYYY-MM")
    ap.add_argument("--reopen", action="store_true", help="reopen a closing or closed cycle instead")
    ap.add_argument("--approved-by", metavar="NAME")
    ap.add_argument("--expect-cycle", metavar="YYYY-MM", type=parse_cycle,
                    help="must equal --cycle: the gate that stops a close of a cycle nobody named")
    ap.add_argument("--schema", default="public")
    ap.add_argument("--target-public", action="store_true")
    args = ap.parse_args()
    write = bool(args.approved_by or args.expect_cycle)
    if write:
        if not (args.approved_by and args.expect_cycle):
            ap.error("writing needs BOTH --approved-by NAME and --expect-cycle YYYY-MM")
        if args.expect_cycle != args.cycle:
            ap.error(f"--expect-cycle {args.expect_cycle:%Y-%m} is not --cycle {args.cycle:%Y-%m}: nothing written")
        if args.schema == "public" and not args.target_public:
            ap.error("writing to public needs --target-public")
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        params = cycle_params(args.cycle)
        (reopen if args.reopen else close)(conn, args.schema, params, args.approved_by or "", write)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
