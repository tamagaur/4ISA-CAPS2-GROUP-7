"""
scripts/run_guards.py - refusals shared by run_baseline_forecast.py and run_lp.py (audit 2026-10-30, P1 and P2).

    stale_abc_refusal(cur, abc_period)          a message when the ABC period is older than the latest real sales month
    cycles_with_a_plan(cur, cycles, principals) the cycles that already hold LP rows from a run (lp_run_key set)

The scripts print the message and exit 2 unless the matching explicit flag is given (--allow-stale-abc, --replan). Before
this, a stale ABC period was an INFO line and only close_cycle caught it, after the plan existed; and a second LP run
quietly moved a plan that had been reviewed.
"""
from __future__ import annotations

LATEST_DEMAND_SQL = "SELECT MAX(calendar_month) FROM Unilever_SKU_Demand_Fact_Real"
PLAN_ROWS_SQL = """
    SELECT lr.planning_cycle_date, COUNT(*)
    FROM LP_Recommendation lr JOIN Product_Dimension pd ON pd.product_key = lr.product_key
    WHERE lr.planning_cycle_date = ANY(%s) AND lr.lp_run_key IS NOT NULL AND pd.principal = ANY(%s)
    GROUP BY lr.planning_cycle_date ORDER BY lr.planning_cycle_date
"""


def stale_abc_refusal(cur, abc_period: str | None) -> str | None:
    cur.execute(LATEST_DEMAND_SQL)
    latest = cur.fetchone()[0]
    if abc_period is None or latest is None or abc_period >= latest:
        return None
    return (f"the ABC period is {abc_period} but the latest real sales month is {latest}: this run would plan from a "
            "stale classification. Run the ABC step for that month first, or pass --allow-stale-abc to go on anyway.")


def cycles_with_a_plan(cur, cycles, principals) -> list[tuple]:
    cur.execute(PLAN_ROWS_SQL, (list(cycles), list(principals)))
    return [(c, int(n)) for c, n in cur.fetchall()]
