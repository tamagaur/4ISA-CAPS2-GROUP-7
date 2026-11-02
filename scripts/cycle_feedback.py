"""
scripts/cycle_feedback.py - what a closed month teaches, for a person to read (2026-11-02). Read-only.

    python -m scripts.cycle_feedback --cycle 2026-03

Three things about one planning month: how far the forecast was from the sales, what the planners did with the plan, and
what became of the accepted orders. Printed, and saved under local/cycle_feedback/ (git-ignored: per-product figures,
hard rule 9).

WHAT THE LOOP IS. Sales, stock counts and accepted orders already reach the next plan through the pipeline itself. This
report is the other half: overrides and dismissal reasons are shown to a person and go nowhere else, because "Truck is
full" says nothing about demand. tests/backend/test_recommendation_decisions.py fails if forecasting or the LP reads them.

MISSING DATA. A month with no sales loaded is "not scored", never zero. In a loaded month a product with no row sold nothing
(the Unilever rule, CLAUDE.md "Why data is missing"), and a blank quantity is left out. A month holding the rehearsal's
generated sales says so on the first line.

GENERATED SALES (hard rule 2). The forecast error is withheld, not computed, when any is_demo row is among the sales it would
be scored on or the history behind the forecast. It reads the same _Real view as the score: the retired backfill rows in the
base table (644 for 2026-03, never read by that view) say nothing about a real month's score.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.close_cycle import PRINCIPAL, cycle_params, parse_cycle, transaction  # noqa: E402
from scripts.report_target import is_live_target  # noqa: E402

SYNTHETIC_TAG = "qa_synthetic%%"   # scripts/local_pipeline_qa.py's _src_file on generated sales; practice database only

MONTH_LOADED_SQL = "SELECT EXISTS (SELECT 1 FROM Unilever_SKU_Demand_Fact_Real WHERE calendar_month = %(period)s)"
# The base table: these rows are is_demo = true, so a count through a _Real view would read 0 and lose the label.
SYNTHETIC_SQL = f"SELECT COUNT(*) FROM unilever_sku_demand_fact WHERE calendar_month = %(period)s AND _src_file LIKE '{SYNTHETIC_TAG}'"
GENERATED_IN_SCORE_SQL = "SELECT COUNT(*) FROM Unilever_SKU_Demand_Fact_Real WHERE calendar_month <= %(period)s AND is_demo"
FORECAST_SQL = """
    SELECT pd.sku_code, fr.forecast_value, s.actual, COALESCE(s.blanks, 0), s.product_key IS NOT NULL
    FROM forecast_result fr
    JOIN product_dimension pd ON pd.product_key = fr.product_key
    LEFT JOIN (SELECT product_key, GREATEST(SUM(quantity_sold), 0) AS actual,
                      COUNT(*) FILTER (WHERE quantity_sold IS NULL) AS blanks
               FROM Unilever_SKU_Demand_Fact_Real WHERE calendar_month = %(period)s GROUP BY product_key) s
           ON s.product_key = fr.product_key
    WHERE pd.principal = %(principal)s AND fr.forecast_date = %(cycle)s AND fr.status = 'ok'
    ORDER BY pd.sku_code
"""
DECISIONS_SQL = """
    SELECT lr.status, lr.q_i, lr.decided_q_i, lr.decision_reason, lr.lp_run_key IS NOT NULL
    FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE pd.principal = %(principal)s AND lr.planning_cycle_date = %(cycle)s
"""
RECEIPTS_SQL = """
    SELECT er.state, er.not_visible_in_count, COUNT(*), COALESCE(SUM(er.pieces), 0),
           COUNT(*) FILTER (WHERE er.state = 'expected' AND er.expected_on < CURRENT_DATE)
    FROM expected_receipt er JOIN lp_recommendation lr ON lr.recommendation_key = er.recommendation_key
    WHERE lr.planning_cycle_date = %(cycle)s
    GROUP BY er.state, er.not_visible_in_count ORDER BY er.state, er.not_visible_in_count
"""


def score(rows: list[dict], month_loaded: bool, generated_rows: int = 0) -> dict:
    """Forecast against sales, in pieces. Blocked (no ratio at all) when the month is not loaded, or when generated sales
    are in what it would be scored on: the figures that could rebuild an error are withheld with it."""
    if generated_rows:
        return {"status": "blocked", "reason": f"forecast error withheld: {generated_rows:,} generated sales rows are in this cycle, "
                                               "and an error computed on generated sales is not presented"}
    if not month_loaded:
        return {"status": "blocked", "reason": "the month's sales are not loaded: not scored, and not read as zero"}
    scored = [r for r in rows if not r["blanks"]]
    pairs = [(float(r["forecast"]), float(r["actual"]) if r["has_row"] else 0.0) for r in scored]
    forecast = sum(f for f, _ in pairs)
    actual = sum(a for _, a in pairs)
    return {"status": "ok", "scored": len(scored), "excluded_blank": len(rows) - len(scored),
            "no_sale": sum(1 for r in scored if not r["has_row"]), "forecast": forecast, "actual": actual,
            "wape": sum(abs(f - a) for f, a in pairs) / actual if actual else None,
            "bias": (forecast - actual) / actual if actual else None,
            "over": sum(1 for f, a in pairs if f > a), "under": sum(1 for f, a in pairs if f < a)}


def summarize_decisions(rows: list[dict]) -> dict:
    plan = [r for r in rows if r["in_plan"]]
    overrides = [r for r in plan if r["status"] == "accepted" and r["decided_q_i"] is not None
                 and float(r["decided_q_i"]) != float(r["q_i"])]
    reasons = Counter(r["decision_reason"] for r in plan if r["decision_reason"])
    return {"pending": sum(1 for r in plan if r["status"] == "pending"),
            "accepted": sum(1 for r in plan if r["status"] == "accepted"),
            "dismissed": sum(1 for r in plan if r["status"] == "dismissed"),
            "outside_plan": len(rows) - len(plan), "overrides": len(overrides),
            "override_change_pieces": sum(float(r["decided_q_i"]) - float(r["q_i"]) for r in overrides),
            "reasons": sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))}


def render(report: dict) -> list[str]:
    lines = []
    if report["synthetic_rows"]:
        lines.append(f"SYNTHETIC REHEARSAL: {report['synthetic_rows']} generated sales rows in this month. Not a result.")
    lines.append(f"Feedback for cycle {report['cycle']} (Unilever). Read-only; none of this changes the next plan.")
    fc = report["forecast"]
    if fc["status"] == "blocked":
        lines.append(f"  Forecast vs sales: {fc['reason']}")
    else:
        ratio = (lambda v: "n/a" if v is None else f"{v:.1%}")
        lines += [f"  Forecast vs sales: {fc['scored']} products, forecast {fc['forecast']:,.0f} vs sold {fc['actual']:,.0f} pieces",
                  f"    error across products (WAPE) {ratio(fc['wape'])}, overall bias {ratio(fc['bias'])}; "
                  f"{fc['over']} over-forecast, {fc['under']} under-forecast",
                  f"    {fc['no_sale']} sold nothing (no row), {fc['excluded_blank']} left out (blank quantity)"]
    d = report["decisions"]
    lines.append(f"  Decisions: {d['accepted']} accepted, {d['dismissed']} dismissed, {d['pending']} never decided, "
                 f"{d['outside_plan']} outside the plan")
    lines.append(f"    {d['overrides']} quantity overrides, net {d['override_change_pieces']:+,.0f} pieces against the plan")
    lines += [f"    reason x{n}: {reason}" for reason, n in d["reasons"]]
    if not report["receipts"]:
        lines.append("  Accepted orders: no receipts recorded for this cycle")
    for r in report["receipts"]:
        note = " NOT VISIBLE in the count (possible short delivery)" if r["not_visible"] else ""
        late = f", {r['overdue']} overdue" if r["overdue"] else ""
        lines.append(f"  Accepted orders: {r['state']}{note}: {r['n']} orders, {r['pieces']:,.0f} pieces{late}")
    return lines


def read_report(cur, params: dict) -> tuple[dict, list[dict]]:
    cur.execute(MONTH_LOADED_SQL, params)
    loaded = bool(cur.fetchone()[0])
    cur.execute(SYNTHETIC_SQL, params)
    synthetic = int(cur.fetchone()[0])
    cur.execute(GENERATED_IN_SCORE_SQL, params)
    generated = max(int(cur.fetchone()[0]), synthetic)
    cur.execute(FORECAST_SQL, params)
    rows = [dict(zip(("sku_code", "forecast", "actual", "blanks", "has_row"), r)) for r in cur.fetchall()]
    cur.execute(DECISIONS_SQL, params)
    decisions = [dict(zip(("status", "q_i", "decided_q_i", "decision_reason", "in_plan"), r)) for r in cur.fetchall()]
    cur.execute(RECEIPTS_SQL, params)
    receipts = [dict(zip(("state", "not_visible", "n", "pieces", "overdue"), r)) for r in cur.fetchall()]
    return ({"cycle": params["period"], "synthetic_rows": synthetic, "forecast": score(rows, loaded, generated),
             "decisions": summarize_decisions(decisions), "receipts": receipts}, rows if loaded and not generated else [])


def save(report: dict, rows: list[dict], lines: list[str], live: bool) -> Path:
    folder = REPO / "local" / "cycle_feedback"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"feedback_{report['cycle']}" + ("" if live else "_nonlive")
    (folder / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(folder / f"{stem}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sku_code", "forecast", "actual", "reason"])
        for r in rows:
            reason = "blank_capture" if r["blanks"] else ("sold" if r["has_row"] else "no_sale")
            actual = "" if r["blanks"] else (r["actual"] if r["has_row"] else 0)
            w.writerow([r["sku_code"], r["forecast"], actual, reason])
    return folder / f"{stem}.txt"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cycle", required=True, type=parse_cycle, help="the planning month, YYYY-MM")
    ap.add_argument("--json", action="store_true", help="print the report as one line of JSON and save nothing")
    args = ap.parse_args()
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        with transaction(conn, "public", read_only=True) as cur:
            report, rows = read_report(cur, cycle_params(args.cycle, PRINCIPAL))
    finally:
        conn.close()
    if args.json:
        print(json.dumps(report, default=float))
        return 0
    lines = render(report)
    print("\n".join(lines))
    print(f"saved {save(report, rows, lines, is_live_target())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
