"""(a) The plan total and row count agree across /recommendations, the Dashboard, mart.planning_mart and the join path.

Guards against: audit 2026-10-23 finding 2 - the Dashboard's order total and product count fell with each decision
(it summed pending rows only) while /recommendations and /policy-comparison kept the whole plan, so one screen said
427,060 and another 435,988 for the same plan. Also guards the planning mart drifting from lp_recommendation
(it is a stored copy, refreshed by a hook) and the "agreement by coincidence" the audit noted (the sum agreed only
because case-pack rounding made every q_i an integer).
"""
import math
import re
from pathlib import Path

from backend.lp_cycle import PLAN_STATUS_SQL
from backend.routers.recommendations import plan_quantity

STATE = Path(__file__).resolve().parents[2] / "STATE.md"


def _numbers(plan, get, sql):
    cycle = plan["planning_cycle_date"]
    dash = get("/dashboard?principal=unilever")
    policy = get("/policy-comparison?principal=unilever")
    joined = sql(f"""SELECT lr.status, lr.q_i, lr.decided_q_i, lr.lp_run_key
                     FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
                     WHERE {PLAN_STATUS_SQL} AND pd.principal = 'unilever' AND lr.planning_cycle_date = :c""", c=cycle)
    mart = sql("""SELECT COUNT(*) AS n, SUM(order_pieces) AS pieces FROM mart.planning_mart
                  WHERE planning_cycle_date = :c AND principal = 'unilever'
                    AND (decision_status = 'pending' OR lp_run_key IS NOT NULL)""", c=cycle)[0]
    return {
        "recommendations": (plan["count"], sum(i["plan_q_i"] for i in plan["items"])),
        "dashboard.reorder_preview": (dash["reorder_preview"]["plan_count"], dash["reorder_preview"]["total_order_qty"]),
        "dashboard.recommendations": (dash["recommendations"]["product_count"], None),
        "policy-comparison": (policy["portfolio"]["sku_count"], None),
        "dashboard.policy_comparison": (dash["policy_comparison"]["sku_count"], None),
        "mart.planning_mart": (int(mart["n"]), float(mart["pieces"])),
        "join (lp_recommendation x product_dimension)":
            (len(joined), sum(plan_quantity(r["q_i"], r["status"], r["decided_q_i"]) for r in joined)),
    }


def test_plan_row_count_and_total_agree_across_every_path(plan, get, sql):
    got = _numbers(plan, get, sql)
    counts = {k: v[0] for k, v in got.items()}
    totals = {k: v[1] for k, v in got.items() if v[1] is not None}
    assert len(set(counts.values())) == 1, f"row count differs by path: {counts}"
    ref = totals["recommendations"]
    assert all(abs(t - ref) < 0.01 for t in totals.values()), f"plan total differs by path: {totals}"


def test_dashboard_action_counts_are_the_reorder_pages(plan, get):
    """The Dashboard and the Reorder page must say the same "Act Now". The Reorder page works these out from
    GET /recommendations' rows (frontend/src/utils/reorderView.js), the Dashboard reads reorder_preview.action_counts."""
    orders = lambda i: math.ceil((i["plan_q_i"] if i["plan_q_i"] is not None else i["q_i"]) - 1e-9) > 0
    waiting = [i for i in plan["items"] if i["status"] == "pending" and orders(i)]
    act_now = sum(1 for i in waiting if i["urgency"] in ("CRITICAL", "URGENT"))
    expected = {"act_now": act_now, "review_later": len(waiting) - act_now,
                "no_order": sum(1 for i in plan["items"] if not orders(i))}
    assert get("/dashboard?principal=unilever")["reorder_preview"]["action_counts"] == expected


def test_state_md_plan_line_matches_the_live_plan(plan):
    """STATE.md is read first by every session, so a plan that moved without it being updated is a failure here.
    Guards against a session trusting a stale 'rows / pieces / cycle / lp_run' line."""
    line = next((ln for ln in STATE.read_text(encoding="utf-8").splitlines() if ln.startswith("plan:")), None)
    assert line, "STATE.md has no 'plan:' line"
    pinned = dict(re.findall(r"(\w+)=(\S+)", line))
    live = {"rows": str(plan["count"]), "pieces": str(round(sum(i["plan_q_i"] for i in plan["items"]))),
            "cycle": plan["planning_cycle_date"], "lp_run": str(plan["lp_model"]["run"]["run_key"])}
    assert pinned == live, f"STATE.md says {pinned}, live plan is {live}: update STATE.md"
