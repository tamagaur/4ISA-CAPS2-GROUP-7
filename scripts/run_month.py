"""
scripts/run_month.py - the monthly batch: one command over the existing steps (2026-11-02).

    python -m scripts.run_month --month 2026-03 --calendar-factor on                      # DRY RUN: reads, prints, writes nothing
    python -m scripts.run_month --month 2026-03 --calendar-factor on \\
        --slice unilever:unilever_sku_demand_fact:2026-03 --slice unilever:inventory_fact:2026-03 \\
        --approved-by NAME --expect-month 2026-03 --target-public                         # load, ABC, forecast, plan; stops for review
    python -m scripts.run_month --month 2026-03 --calendar-factor on --close --expect-plan-pieces N \\
        --approved-by NAME --expect-month 2026-03 --target-public                         # closes the month after a person read the plan

--month is the month whose sales and count just arrived. It produces the plan for the month after, then closes this one.

WHAT IT IS. Only the order. Every step is the repo's own script with its own refusals, run as a child process; a step
that exits non-zero stops the batch with that exit code, and running the same command again skips the steps already done
(close_cycle.CHECKS is the record of what is done). There is no scheduler, on purpose: a close needs a named person.

THE STOP BEFORE THE CLOSE. The first write run ends by printing the old and new plan side by side, the stock count against
its earlier ones, and the feedback report. There is no threshold for "too large": nothing on record sets one. The close
needs --expect-plan-pieces with the total that person saw (the gate pattern of scripts/clean_dead_skus.py).

THE CALENDAR FACTOR has no default here. The forecast runner's default is off, the live forecast used it, and a monthly
run that silently turned it off would move the plan (Sir Catubag's sign-off is still pending, see CLAUDE.md).

SYNTHETIC SALES (scripts/local_pipeline_qa.py synth, is_demo = true) exist only in the local ssm_practice database. No real step
reads them, so a month holding only those is refused here (KNOWN_ISSUES M5). On live this refuses to start if any are in the
month, and it never generates any.
"""
from __future__ import annotations

import argparse
import datetime
import os
import statistics
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analytics.params import abc_method  # noqa: E402
from scripts import close_cycle  # noqa: E402
from scripts.close_cycle import PRINCIPAL, cycle_params, parse_cycle, transaction  # noqa: E402
from scripts.cycle_feedback import SYNTHETIC_SQL  # noqa: E402
from scripts.report_target import is_live_target  # noqa: E402

LATEST_SALES_SQL = "SELECT MAX(calendar_month) FROM Unilever_SKU_Demand_Fact_Real"
PLAN_SQL = """
    SELECT COUNT(*), COUNT(*) FILTER (WHERE lr.q_i > 0), COALESCE(SUM(lr.q_i), 0)
    FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE pd.principal = %(principal)s AND lr.planning_cycle_date = %(plan_cycle)s AND lr.lp_run_key IS NOT NULL
"""
NEWEST_PLAN_SQL = """
    SELECT MAX(lr.planning_cycle_date) FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE pd.principal = %(principal)s AND lr.lp_run_key IS NOT NULL
"""
PRIOR_CLOSED_SQL = """
    SELECT 1 FROM planning_cycle WHERE principal = %(principal)s AND cycle = %(plan_cycle)s AND state = 'closed'
"""
OPENING_BASIS_SQL = """
    SELECT inputs ->> 'opening_basis' FROM lp_run WHERE planning_cycle_date = %(plan_cycle)s ORDER BY run_key DESC LIMIT 1
"""
COUNTS_SQL = """
    SELECT inv._period, MAX(inv.snapshot_date),
           SUM(CASE WHEN pd.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd.pack_size::numeric > 0
                    THEN COALESCE(inv.quantity_on_hand, 0) * pd.pack_size::numeric + COALESCE(inv.quantity_pieces, 0) END)
    FROM inventory_fact_real inv JOIN product_dimension pd ON pd.product_key = inv.product_key
    WHERE inv.principal = %(principal)s AND inv._period ~ '^[0-9]{4}-[0-9]{2}$'
    GROUP BY inv._period ORDER BY inv._period DESC LIMIT 7
"""


@dataclass
class Step:
    name: str
    cmd: list[str]
    check: str | None = None     # the close_cycle check that says this step's work is in the database
    always: bool = False         # run even when the check already holds (a load the person asked for)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--month", required=True, type=parse_cycle, help="the month whose sales and count just arrived, YYYY-MM")
    ap.add_argument("--calendar-factor", required=True, choices=["on", "off"], help="say it every run; no default on purpose")
    ap.add_argument("--slice", action="append", default=[], metavar="SPEC", help="load this slice first (run_canonical_load --slice). Repeatable.")
    ap.add_argument("--file", action="append", default=[], metavar="PATH", help="use this raw file for those slices (run_canonical_load --file). Repeatable.")
    ap.add_argument("--close", action="store_true", help="close the month, after a person has read the new plan")
    ap.add_argument("--expect-plan-pieces", type=int, metavar="N", help="with --close: the new plan's total as printed")
    ap.add_argument("--approved-by", metavar="NAME")
    ap.add_argument("--expect-month", type=parse_cycle, metavar="YYYY-MM", help="must equal --month")
    ap.add_argument("--target-public", action="store_true", help="explicit-only: allow a write to the live database")
    return ap


def cycle_prior(cycle: datetime.date) -> datetime.date:
    return datetime.date(cycle.year - (cycle.month == 1), (cycle.month - 2) % 12 + 1, 1)


def pick_month(newest_plan: datetime.date, prior_has_plan: bool, prior_closed: bool) -> datetime.date:
    """The month in play: a new plan exists once its month's data arrived, and that month stays in play until it is closed."""
    if prior_has_plan and not prior_closed:
        return cycle_prior(newest_plan)
    return newest_plan


def is_write(args) -> bool:
    return bool(args.approved_by or args.expect_month)


def gate_errors(args, live: bool) -> list[str]:
    if args.file and not args.slice:
        return ["--file needs --slice: a file says what to load, the slice says where it goes"]
    if not is_write(args):
        return []
    if not (args.approved_by and args.expect_month):
        return ["writing needs BOTH --approved-by NAME and --expect-month YYYY-MM"]
    errors = []
    if args.expect_month != args.month:
        errors.append(f"--expect-month {args.expect_month:%Y-%m} is not --month {args.month:%Y-%m}: nothing written")
    if live and not args.target_public:
        errors.append("this is the live database: writing needs --target-public")
    if args.close and args.expect_plan_pieces is None:
        errors.append("--close needs --expect-plan-pieces N, the new plan's total as printed by the run before it")
    return errors


def preflight_refusals(month: datetime.date, facts: dict, checks: dict, slices: list[str], live: bool) -> list[str]:
    period = f"{month:%Y-%m}"
    refusals = []
    if facts["latest_sales_month"] and facts["latest_sales_month"] > period:
        refusals.append(f"sales for {facts['latest_sales_month']} are already loaded: {period} is not the latest month")
    if live and facts["synthetic_rows"]:
        refusals.append(f"{facts['synthetic_rows']} synthetic sales rows are in {period} on the live database")
    if not checks["sales_loaded"] and not slices:
        if facts["synthetic_rows"]:
            refusals.append(f"{period} holds only {facts['synthetic_rows']} generated sales rows, labelled is_demo = true: the real "
                            "steps do not read them and the forecast refuses them, so this month cannot run on them")
        else:
            refusals.append(f"{period} sales are not loaded and no --slice was given to load them")
    if slices and checks["abc_run"]:
        refusals.append(f"the ABC for {period} has already run: loading again would leave the forecast and plan built on the "
                        "old sales. Nothing here reruns them; redo those steps by hand and on purpose")
    return refusals


def plan_steps(args, py: str = sys.executable) -> list[Step]:
    period = f"{args.month:%Y-%m}"
    steps = []
    if args.slice:
        load = [py, "-m", "scripts.run_canonical_load", "--schema", "public", "--target-public"]
        for spec in args.slice:
            load += ["--slice", spec]
        for path in args.file:
            load += ["--file", path]
        steps.append(Step("load", load, "sales_loaded", always=True))
    forecast = [py, "scripts/run_baseline_forecast.py", "--write"] + (["--calendar-factor"] if args.calendar_factor == "on" else [])
    steps += [Step("abc", [py, "-m", "analytics.classification.orchestrate_abc", "--period", period, "--schema", "public",
                           "--method", abc_method(PRINCIPAL), "--principal", PRINCIPAL], "abc_run"),
              Step("forecast", forecast, "forecast_next"),
              Step("lp", [py, "scripts/run_lp.py", "--retire-stale-pending"], "lp_next")]
    return steps


def run_steps(steps: list[Step], runner, read_checks, out=print) -> int:
    for step in steps:
        if step.check and not step.always and read_checks()[step.check]:
            out(f"[{step.name}] already done, skipped")
            continue
        out(f"[{step.name}] running")
        rc = runner(step.cmd)
        if rc:
            out(f"[{step.name}] exited {rc}: batch stopped. Fix it and run the same command again; finished steps are skipped.")
            return rc
        if step.check and not read_checks()[step.check]:
            out(f"[{step.name}] exited 0 but did not do its work ({step.check} is still false): batch stopped")
            return 2
    return 0


def plan_comparison(month: datetime.date, old: dict, new: dict) -> list[str]:
    nxt = cycle_params(month)["next_cycle"]
    ratio = f"{new['pieces'] / old['pieces']:.2f}x" if old["pieces"] else "n/a"
    return [f"  plan {month:%Y-%m}: {old['rows']} rows, {old['ordering']} ordering, {old['pieces']:,.0f} pieces",
            f"  plan {nxt:%Y-%m}: {new['rows']} rows, {new['ordering']} ordering, {new['pieces']:,.0f} pieces "
            f"({ratio} the old plan; opening stock from {new.get('opening_basis') or 'unknown'})"]


def count_lines(rows: list[tuple]) -> list[str]:
    if not rows:
        return ["  no stock count on record"]
    period, counted_on, pieces = rows[0]
    earlier = [float(r[2]) for r in rows[1:] if r[2] is not None]
    if not earlier or pieces is None:
        return [f"  stock count {period} (taken {counted_on}): {'n/a' if pieces is None else format(float(pieces), ',.0f')} pieces"]
    median = statistics.median(earlier)
    ratio = f"{float(pieces) / median:.2f}x" if median else "n/a"
    return [f"  stock count {period} (taken {counted_on}): {float(pieces):,.0f} pieces, {ratio} the median of the {len(earlier)} before it",
            "  SSM cannot be asked about a count that looks wrong: it is shown here for the person approving, and is not corrected."]


def close_refusal(expected: int, actual: float) -> str | None:
    if round(actual) == expected:
        return None
    return f"--expect-plan-pieces {expected:,} is not the plan's {actual:,.0f} pieces: the plan changed, or the number is wrong. Nothing closed."


# --- the database ---------------------------------------------------------------------------------------------------

def _read(fn):
    import psycopg2
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])   # a new connection each time: a step can run longer than the pooler keeps an idle one
    try:
        with transaction(conn, "public", read_only=True) as cur:
            return fn(cur)
    finally:
        conn.close()


def _status(params: dict) -> dict:
    return _read(lambda cur: close_cycle.read_status(cur, params))


def _facts(params: dict) -> dict:
    def read(cur):
        cur.execute(LATEST_SALES_SQL)
        latest = cur.fetchone()[0]
        cur.execute(SYNTHETIC_SQL, params)
        return {"latest_sales_month": latest, "synthetic_rows": int(cur.fetchone()[0])}
    return _read(read)


def _plan(params: dict, cycle: datetime.date) -> dict:
    def read(cur):
        args = {**params, "plan_cycle": cycle}
        cur.execute(PLAN_SQL, args)
        rows, ordering, pieces = cur.fetchone()
        cur.execute(OPENING_BASIS_SQL, args)
        basis = cur.fetchone()
        return {"rows": int(rows), "ordering": int(ordering), "pieces": float(pieces), "opening_basis": basis[0] if basis else None}
    return _read(read)


def _counts(params: dict) -> list[tuple]:
    def read(cur):
        cur.execute(COUNTS_SQL, params)
        return cur.fetchall()
    return _read(read)


def current_month() -> datetime.date:
    def read(cur):
        cur.execute(NEWEST_PLAN_SQL, {"principal": PRINCIPAL})
        newest = cur.fetchone()[0]
        if newest is None:
            raise SystemExit("no plan on record")
        args = {"principal": PRINCIPAL, "plan_cycle": cycle_prior(newest)}
        cur.execute(PLAN_SQL, args)
        has_plan = cur.fetchone()[0] > 0
        cur.execute(PRIOR_CLOSED_SQL, args)
        return pick_month(newest, has_plan, cur.fetchone() is not None)
    return _read(read)


def _runner(cmd: list[str]) -> int:
    sys.stdout.flush()   # piped output is buffered: without this a child's lines land before ours
    return subprocess.run(cmd, cwd=REPO).returncode


def _feedback(args) -> int:
    return _runner([sys.executable, "-m", "scripts.cycle_feedback", "--cycle", f"{args.month:%Y-%m}"])


def _review(args, params: dict) -> int:
    new = _plan(params, params["next_cycle"])
    print("\nREVIEW BEFORE CLOSING")
    for line in plan_comparison(args.month, _plan(params, params["cycle"]), new) + count_lines(_counts(params)):
        print(line)
    rc = _feedback(args)
    print(f"\nTo close {args.month:%Y-%m}, once this has been read: the same command with --close --expect-plan-pieces {round(new['pieces'])}")
    return rc


def run_plan_stage(args, params: dict) -> int:
    rc = run_steps(plan_steps(args), _runner, lambda: _status(params)["checks"])
    if rc:
        return rc
    from analytics import marts
    if marts.refresh_marts(os.environ["SUPABASE_DB_URL"], "run_month") is None:
        print("[marts] did not refresh: batch stopped. Run the same command again.")
        return 1
    return _review(args, params)


def run_close_stage(args, params: dict) -> int:
    refusal = close_refusal(args.expect_plan_pieces, _plan(params, params["next_cycle"])["pieces"])
    if refusal:
        print("REFUSED: " + refusal)
        return 2
    period = f"{args.month:%Y-%m}"
    rc = _runner([sys.executable, "-m", "scripts.close_cycle", "--cycle", period, "--approved-by", args.approved_by,
                  "--expect-cycle", period, "--target-public"])
    return rc or _feedback(args)


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    live = is_live_target()
    errors = gate_errors(args, live)
    if errors:
        ap.error("; ".join(errors))
    params = cycle_params(args.month, PRINCIPAL)
    status = _status(params)
    for line in close_cycle.describe(status, params):
        print(line)
    print(f"  database: {'LIVE' if live else 'local (not live)'}; calendar factor {args.calendar_factor}")
    refusals = preflight_refusals(args.month, _facts(params), status["checks"], args.slice, live)
    if refusals:
        print("REFUSED: " + "; ".join(refusals))
        return 2
    if not is_write(args):
        print("dry run. Nothing ran and nothing was written. A write run would do, in order:")
        for step in plan_steps(args):
            done = step.check and not step.always and status["checks"][step.check]
            print(f"  [{'skip, done' if done else 'run'}] {' '.join(step.cmd[1:])}")
        print("  then refresh the marts, print the review, and stop. The close is a separate command.")
        return 0
    if live:
        print("LIVE WRITE: a new plan moves the 109 rows / 435,988 pieces in STATE.md (the numeric gate). Update STATE.md in the same commit.")
    return run_close_stage(args, params) if args.close else run_plan_stage(args, params)


if __name__ == "__main__":
    sys.exit(main())
