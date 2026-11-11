"""
scripts/run_month.py - the monthly batch: one command over the existing steps (2026-11-02).

    python -m scripts.run_month --month 2026-03 --calendar-factor on                      # DRY RUN: reads, prints, writes nothing
    python -m scripts.run_month --month 2026-03 --calendar-factor on \\
        --slice unilever:unilever_sku_demand_fact:2026-03 --slice unilever:inventory_fact:2026-03 \\
        --approved-by NAME --expect-month 2026-03 --target-public                         # load, ABC, forecast, plan; stops for review
    python -m scripts.run_month --month 2026-03 --calendar-factor on --close --expect-plan-pieces N \\
        --approved-by NAME --expect-month 2026-03 --target-public                         # closes the month after a person read the plan
    python -m scripts.run_month --month 2026-03 --calendar-factor on --check-files \\
        --slice unilever:unilever_sku_demand_fact:2026-03 --file local/x.xls              # the loader's dry run, nothing loaded

--month is the month whose sales and count just arrived. It produces the plan for the month after, then closes this one.

WHAT IT IS. Only the order. Every step is the repo's own script with its own refusals, run as a child process; a step
that exits non-zero stops the batch with that exit code, and running the same command again skips the steps already done
(close_cycle.CHECKS is the record of what is done). There is no scheduler, on purpose: a close needs a named person.

THE STOP BEFORE THE CLOSE. The first write run ends by printing the old and new plan side by side, the stock count against
its earlier ones, and the feedback report. There is no threshold for "too large": nothing on record sets one. The close
needs --expect-plan-pieces with the total that person saw (the gate pattern of scripts/clean_dead_skus.py).

UNSETTLED REORDER DECISIONS STOP THE RUN (2026-11-04, provisional, for Yuan's review: docs/MONTHLY_BATCH_REVIEW.md). Once the
next plan is written this month's rows can no longer be decided (backend/routers/recommendations.py, the current-cycle rule), and
an accepted order counts as stock on the way in that next plan (stock_opening_v). So preflight_refusals refuses while this month's
plan holds a row someone can still decide, or a staff request an admin has not settled. It does not stop a rerun once the next
plan exists, or a close: by then those rows cannot be decided, and a refusal could never clear. There is no override.

THE CALENDAR FACTOR has no default here. The forecast runner's default is off, the live forecast used it, and a monthly
run that silently turned it off would move the plan (team decision DEC-41; adviser sign-off outstanding, still pending, see CLAUDE.md).

SYNTHETIC SALES (scripts/local_pipeline_qa.py synth, is_demo = true) exist only in the local ssm_practice database, whose demand
view admits them (local_pg.PRACTICE_VIEW_SQL) and whose connection alone makes the forecast accept them
(analytics/forecasting/practice_switch). Anywhere else a month holding only those is refused here. On live this refuses to start
if any are in the month, and it never generates any.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analytics import demo_session  # noqa: E402
from analytics.params import abc_method  # noqa: E402
from scripts import close_cycle  # noqa: E402
from scripts.close_cycle import PRINCIPAL, cycle_params, parse_cycle, transaction  # noqa: E402
from scripts.cycle_feedback import GENERATED_IN_SCORE_SQL, SYNTHETIC_SQL  # noqa: E402
from scripts.report_target import PRACTICE_MARKER, is_live_target, is_practice_target  # noqa: E402

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
    SELECT inputs ->> 'opening_basis', run_key FROM lp_run WHERE planning_cycle_date = %(plan_cycle)s ORDER BY run_key DESC LIMIT 1
"""
# Every recommendation row of the principal, sorted by whether a person can still act on it. Only the first count stops a run.
#   actionable_pending     this month's plan, pending, ordering more than 0: the Reorder page offers Accept and Dismiss
#   zero_quantity_pending  this month's plan, pending, ordering nothing: the page offers neither (36 of the 109 on 2026-11-04)
#   decided                this month's rows already accepted or dismissed, kept as they are
#   historical_pending     pending rows of earlier cycles: the backend refuses a decision on them, so they can never clear
#   later_pending          pending rows of a later plan, which is the next month's to settle
DECISION_COUNTS_SQL = """
    SELECT COUNT(*) FILTER (WHERE lr.planning_cycle_date = %(cycle)s AND lr.status = 'pending' AND lr.closed_at IS NULL AND lr.q_i > 0),
           COUNT(*) FILTER (WHERE lr.planning_cycle_date = %(cycle)s AND lr.status = 'pending' AND lr.closed_at IS NULL
                            AND COALESCE(lr.q_i, 0) <= 0),
           COUNT(*) FILTER (WHERE lr.planning_cycle_date = %(cycle)s AND lr.status <> 'pending'),
           COUNT(*) FILTER (WHERE lr.planning_cycle_date < %(cycle)s AND lr.status = 'pending'),
           COUNT(*) FILTER (WHERE lr.planning_cycle_date > %(cycle)s AND lr.status = 'pending')
    FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE pd.principal = %(principal)s
"""
# A staff request is open until an admin settles it (migrations 0068 and 0070). While it is open nobody can decide the row directly.
OPEN_REQUESTS_SQL = """
    SELECT COUNT(*) FROM {table} r
    JOIN lp_recommendation lr ON lr.recommendation_key = r.recommendation_key
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE r.state = 'pending_approval' AND lr.planning_cycle_date = %(cycle)s AND pd.principal = %(principal)s
"""
REQUEST_TABLES = {"open_quantity_changes": "lp_quantity_change", "open_dismissal_requests": "lp_dismissal_request"}
LOAD_EVENTS_SQL = """
    SELECT slice, status, reason, detail, files, real_rows_before, real_rows_after, real_rows_added, quarantine_rows_added
    FROM etl_load_event WHERE run_id = %(run_id)s AND dry_run ORDER BY load_event_key
"""
COUNTS_SQL = r"""
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
    ap.add_argument("--practice-auto-sign", action="store_true", help="passed to the load step, which refuses it off the practice copy (scripts/practice_signed_load.py)")
    ap.add_argument("--check-files", action="store_true", help="the loader's dry run on these --slice and --file inputs: nothing is loaded")
    ap.add_argument("--check-files-report", metavar="PATH", help="with --check-files: write what it found to this JSON file")
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
    if args.check_files:
        if not args.slice:
            return ["--check-files needs --slice: nothing to check"]
        if is_write(args) or args.close:
            return ["--check-files only checks: it takes no --approved-by, --expect-month or --close"]
        if live and not args.target_public:
            return ["this is the live database: the loader's dry run records its events there, so --check-files needs --target-public"]
        return []
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


def open_decisions(decisions: dict) -> int:
    """What still needs a person: rows someone can decide, and staff requests an admin must settle. A request's row is pending
    too, so the two can overlap; this is only ever tested for zero, and the two are shown separately."""
    return decisions["actionable_pending"] + decisions["open_requests"]


def decisions_refusal(period: str, decisions: dict, checks: dict) -> str | None:
    """Why a run must wait for people, or None. See UNSETTLED REORDER DECISIONS above. Once the next plan exists these rows cannot
    be decided, so a refusal there could never clear: a rerun and a close go on."""
    if checks.get("lp_next") or not open_decisions(decisions):
        return None
    return (f"{decisions['actionable_pending']} reorder recommendation(s) of the {period} plan still await a decision and "
            f"{decisions['open_requests']} staff request(s) await an admin: settle them on the Reorder Recommendations page first. "
            "Once the next plan exists they can no longer be decided, and accepted orders count as stock on the way in that plan")


def preflight_items(month: datetime.date, facts: dict, checks: dict, slices: list[str], live: bool) -> list[tuple[str, str]]:
    """(code, sentence) for each reason not to start. The code lets scripts/batch_status.py report which check it was."""
    period = f"{month:%Y-%m}"
    items = []
    if facts["latest_sales_month"] and facts["latest_sales_month"] > period:
        items.append(("not_latest_month", f"sales for {facts['latest_sales_month']} are already loaded: {period} is not the latest month"))
    if live and facts["synthetic_rows"] and not facts.get("demo_session"):
        items.append(("synthetic_on_live", f"{facts['synthetic_rows']} synthetic sales rows are in {period} on the live database"))
    if not checks["sales_loaded"] and not slices:
        if facts["synthetic_rows"]:
            items.append(("only_generated_sales",
                          f"{period} holds only {facts['synthetic_rows']} generated sales rows, labelled is_demo = true: this database's "
                          "demand view excludes them. Only the practice copy (python -m scripts.local_pg practice) runs on them"))
        else:
            items.append(("sales_missing", f"{period} sales are not loaded and no --slice was given to load them"))
    if slices and checks["abc_run"]:
        items.append(("already_ran", f"the ABC for {period} has already run: loading again would leave the forecast and plan built on the "
                                     "old sales. Nothing here reruns them; redo those steps by hand and on purpose"))
    refusal = decisions_refusal(period, facts["decisions"], checks)
    if refusal:
        items.append(("decisions_open", refusal))
    return items


def preflight_refusals(month: datetime.date, facts: dict, checks: dict, slices: list[str], live: bool) -> list[str]:
    return [sentence for _, sentence in preflight_items(month, facts, checks, slices, live)]


def plan_steps(args, py: str = sys.executable) -> list[Step]:
    period = f"{args.month:%Y-%m}"
    steps = []
    if args.slice:
        load = [py, "-m", "scripts.run_canonical_load", "--schema", "public", "--target-public"]
        for spec in args.slice:
            load += ["--slice", spec]
        for path in args.file:
            load += ["--file", path]
        if getattr(args, "practice_auto_sign", False):
            load.append("--practice-auto-sign")
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


def check_files_cmd(args, py: str = sys.executable) -> list[str]:
    """The loader's own dry run on the same inputs the load step would get. It is scripts/load_slices.py that checks: layout, missing
    file, shrink guard, validation bands, sign-off. Only its events are written, and those rows say dry_run."""
    cmd = [py, "-m", "scripts.run_canonical_load", "--schema", "public", "--target-public", "--dry-run"]
    for spec in args.slice:
        cmd += ["--slice", spec]
    for path in args.file:
        cmd += ["--file", path]
    return cmd


def parse_loader_output(lines: list[str]) -> dict:
    """What the loader printed about this run: the id its events carry, and the manifest a sign-off must match."""
    found = {"run_id": None, "run_key": None, "fingerprint": None}
    for line in lines:
        manifest = re.search(r"\[manifest\] run key (\S+?):.*fingerprint (\S+)", line)
        if manifest:
            found["run_key"], found["fingerprint"] = manifest.group(1), manifest.group(2)
        run = re.search(r"\brun_id=(\S+)", line)
        if run:
            found["run_id"] = run.group(1)
    return found


def file_digest(path: str) -> dict:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"name": Path(path).name, "sha256": digest.hexdigest()}


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


def read_decisions(cur, params: dict) -> dict:
    """The counts behind the decisions refusal, from the records themselves, in the caller's read-only transaction."""
    cur.execute(DECISION_COUNTS_SQL, params)
    actionable, zero_quantity, decided, historical, later = (int(n) for n in cur.fetchone())
    out = {"cycle": f"{params['cycle']:%Y-%m}", "actionable_pending": actionable, "zero_quantity_pending": zero_quantity,
           "decided": decided, "historical_pending": historical, "later_pending": later}
    for name, table in REQUEST_TABLES.items():
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
        present = bool(cur.fetchone()[0])       # no table, no request: the migrations behind them may not be applied on an old copy
        if present:
            cur.execute(OPEN_REQUESTS_SQL.format(table=table), params)
        out[name] = int(cur.fetchone()[0]) if present else 0
    out["open_requests"] = sum(out[name] for name in REQUEST_TABLES)
    return out


def _facts(params: dict) -> dict:
    def read(cur):
        cur.execute(LATEST_SALES_SQL)
        latest = cur.fetchone()[0]
        cur.execute(SYNTHETIC_SQL, params)
        synthetic = int(cur.fetchone()[0])
        cur.execute(GENERATED_IN_SCORE_SQL, params)
        generated = max(int(cur.fetchone()[0]), synthetic)
        return {"latest_sales_month": latest, "synthetic_rows": synthetic, "generated_rows": generated,
                "decisions": read_decisions(cur, params),
                "demo_session": demo_session.permits_labelled_rows(cur)}   # asked of the database: an open session with its window in force
    return _read(read)


def _plan(params: dict, cycle: datetime.date) -> dict:
    def read(cur):
        args = {**params, "plan_cycle": cycle}
        cur.execute(PLAN_SQL, args)
        rows, ordering, pieces = cur.fetchone()
        cur.execute(OPENING_BASIS_SQL, args)
        basis = cur.fetchone()
        return {"rows": int(rows), "ordering": int(ordering), "pieces": float(pieces), "opening_basis": basis[0] if basis else None,
                "run_key": basis[1] if basis else None}
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


def run_check_files(args, params: dict) -> int:
    """Runs the loader's dry run and reports what it found. Refused slices are a finding, not a failure of this command: it exits 0
    once the report is written, and non-zero only when the loader never got as far as recording anything."""
    digests = [file_digest(path) for path in args.file]
    sys.stdout.flush()
    proc = subprocess.Popen(check_files_cmd(args), cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    lines = []
    for line in proc.stdout:
        print(line, end="")
        lines.append(line.rstrip())
    code = proc.wait()
    found = parse_loader_output(lines)
    events = []
    if found["run_id"]:
        def read(cur):
            cur.execute(LOAD_EVENTS_SQL, {"run_id": found["run_id"]})
            names = [c[0] for c in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]
        events = _read(read)
    report = {"marker": PRACTICE_MARKER if is_practice_target() else None, "month": f"{args.month:%Y-%m}",
              "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "exit_code": code, **found,
              "completed": bool(found["run_id"]), "events": events, "files": digests}
    if args.check_files_report:
        target = Path(args.check_files_report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"[check-files] {len(events)} event(s), {sum(1 for e in events if e['status'] == 'refused')} refused")
    if not found["run_id"]:
        print("[check-files] the loader recorded nothing: batch stopped")
        return 1
    return 0


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
    facts = _facts(params)
    if facts["generated_rows"]:
        print(f"  {PRACTICE_MARKER}: {facts['generated_rows']} generated sales rows in the history up to this month")
    refusals = preflight_refusals(args.month, facts, status["checks"], args.slice, live)
    if args.check_files:
        # Checking a file writes nothing that a refusal is there to protect, and the person wants every problem at once.
        for refusal in refusals:
            print("NOTE: a run would be refused: " + refusal)
        return run_check_files(args, params)
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
        print(f"LIVE WRITE: a new plan moves the {state_plan_text()} in STATE.md (the numeric gate). Update STATE.md in the same commit.")
    return run_close_stage(args, params) if args.close else run_plan_stage(args, params)


def state_plan_text() -> str:
    """'<rows> rows / <pieces> pieces' from STATE.md's plan line, which tests/invariants/test_a_plan_agreement.py holds equal
    to the live plan (this message carried a literal 109 / 435,988 until 2026-11-11, two re-plans after it stopped being true)."""
    try:
        line = next(ln for ln in (REPO / "STATE.md").read_text(encoding="utf-8").splitlines() if ln.startswith("plan:"))
        got = dict(re.findall(r"(\w+)=(\S+)", line))
        return f"{int(got['rows'])} rows / {int(got['pieces']):,} pieces"
    except (OSError, StopIteration, KeyError, ValueError):
        return "plan (STATE.md's plan line could not be read)"


if __name__ == "__main__":
    sys.exit(main())
