"""(e) Safety stock and target stock agree between the plan and /policy-comparison.

Guards against: the policy card re-deriving safety stock or target stock from its own inputs and drifting from the
numbers the plan was built on (audit 2026-10-23 part 1b recorded them equal "by construction"; this makes that a
check, so a change on either side is caught). Also covers the stored mart copy and the Dashboard's policy block.
"""
import pytest


def test_safety_and_target_stock_agree_row_by_row(plan, get):
    pol = {i["sku_id"]: i for i in get("/policy-comparison?principal=unilever")["items"]}
    assert len(pol) == plan["count"], f"{len(pol)} policy rows against {plan['count']} plan rows"
    for item in plan["items"]:
        p = pol[item["sku_id"]]
        assert p["lp_safety_stock_units"] == pytest.approx(item["ss_i"], abs=0.01), item["sku_id"]
        assert p["lp_target_stock_units"] == pytest.approx(item["rop_i"], abs=0.01), item["sku_id"]


def test_portfolio_totals_agree_across_plan_policy_dashboard_and_mart(plan, get, sql):
    ss = sum(i["ss_i"] for i in plan["items"])
    target = sum(i["rop_i"] for i in plan["items"])
    pol = get("/policy-comparison?principal=unilever")["portfolio"]
    dash = get("/dashboard?principal=unilever")["policy_comparison"]
    mart = sql("""SELECT SUM(safety_stock) AS ss, SUM(target_stock) AS target FROM mart.planning_mart
                  WHERE planning_cycle_date = :c AND principal = 'unilever'
                    AND (decision_status = 'pending' OR lp_run_key IS NOT NULL)""", c=plan["planning_cycle_date"])[0]
    for name, (s, t) in {"policy-comparison": (pol["lp_safety_stock_units"], pol["lp_target_stock_units"]),
                         "dashboard": (dash["lp_safety_stock_units"], dash["lp_target_stock_units"]),
                         "mart.planning_mart": (float(mart["ss"]), float(mart["target"]))}.items():
        assert s == pytest.approx(ss, abs=0.5), f"{name} safety stock {s} vs plan {ss}"
        assert t == pytest.approx(target, abs=0.5), f"{name} target stock {t} vs plan {target}"
