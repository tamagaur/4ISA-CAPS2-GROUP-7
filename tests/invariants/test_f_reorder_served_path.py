"""(f) The Reorder page is checked on the path live serves.

Guards against: the gap found 2026-11-16. Live answers GET /recommendations from mart.planning_mart
(backend/planning_mart.py), and the per-request joins run only when the mart is stale. The unit tests' fake sessions
are never asked for the mart, so every route test of tests/backend/test_recommendations.py ran the fallback, and A13's
own test (a decided row no LP run produced is outside the plan) only searched the router's source text. Here the real
SQL of both paths runs against live, read-only:

  - live IS serving the mart (if it stops, the tests below would be comparing the fallback with itself, so that fails);
  - the mart's answer equals the joins' answer, field by field, for the plan and for cycle=all over the plan's cycle
    (the view that lists the row A13 is about);
  - in cycle=all the rows flagged outside the plan are exactly the rows the plan clauses leave out, read straight from
    lp_recommendation, and the unflagged ones are exactly the plan.
"""
from fastapi.encoders import jsonable_encoder

from backend import planning_mart
from backend.data_mode import REAL
from backend.routers import recommendations as rec
from scripts.rehearse_planning_mart import _diff


def _answer(db, cycle: str, from_date=None, to_date=None, mart: bool = True) -> dict:
    """The endpoint's own function for Unilever, from the mart or (mart=False) from the per-request joins."""
    planning_mart.use_schema("mart" if mart else None)
    try:
        out = rec.get_recommendations(status=None, cycle=cycle, from_date=from_date, to_date=to_date,
                                      principal="unilever", mode=REAL, db=db, current_user=None)
    finally:
        planning_mart.use_schema("mart")
    return jsonable_encoder(out)


def test_live_serves_the_reorder_page_from_the_planning_mart(db, plan):
    got = planning_mart.read(db, "unilever", None, "current", None, None)
    assert got is not None, (
        "live is not serving mart.planning_mart (stale, out of step with lp_recommendation, or built on another Tier A "
        "basis), so GET /recommendations is running the per-request joins: refresh the planning mart "
        "(analytics/marts.py) before trusting any check of the mart path")
    assert len(got["rows"]) == plan["count"]
    assert {r["recommendation_key"] for r in got["rows"]} == {i["recommendation_key"] for i in plan["items"]}


def test_the_mart_and_the_joins_answer_alike_for_the_plan_and_for_its_cycle_in_full(db, plan):
    import datetime
    cycle = datetime.date.fromisoformat(plan["planning_cycle_date"])
    cases = [("current", None, None), ("all", cycle, cycle)]
    for name, start, end in cases:
        mart = _answer(db, name, start, end, mart=True)
        joins = _answer(db, name, start, end, mart=False)
        assert mart["items"], f"cycle={name}: the mart path listed nothing"
        assert _diff(joins, mart) == [], f"cycle={name}: the mart and the joins disagree"
    assert _diff(_answer(db, "current"), plan) == [], "GET /recommendations is not the mart's answer"


def test_every_page_that_shows_a_target_shows_it_for_the_plans_products_and_no_others(get, plan):
    """The SKU list, the ABC page and the stock page each read the plan through their own SQL
    (PLAN_STATUS_SQL_BARE). tests/backend/test_recommendation_decisions.py::test_every_plan_read_uses_the_plan_statuses
    only finds that text in their source; this runs them. A product has a target on those pages when, and only when, it
    has a row in the plan: a decided row no LP run produced gives none."""
    planned = {i["sku_id"] for i in plan["items"]}
    sku = {i["sku_id"] for i in get("/sku?principal=unilever")["items"] if i["reorder_point"] is not None}
    assert sku == planned, f"GET /sku: {len(sku - planned)} targets outside the plan, {len(planned - sku)} plan products without"
    abc_items = get("/abc?principal=unilever")["items"]
    abc = {i["sku_id"] for i in abc_items if i["no_target_code"] is None}
    assert abc == planned, f"GET /abc: {len(abc - planned)} targets outside the plan, {len(planned - abc)} plan products without"
    stock = get("/inventory/current?principal=unilever")
    rows = stock if isinstance(stock, list) else stock["inventory"]
    with_target = {r["sku"] for r in rows if r["status"] != "NO ROP"}
    assert with_target == planned & {r["sku"] for r in rows}, "GET /inventory/current: a target on a product outside the plan"


def test_cycle_all_flags_exactly_the_rows_the_plan_clauses_leave_out(get, plan, sql):
    """A13 on live's own rows, through the route as live serves it."""
    body = get("/recommendations?principal=unilever&cycle=all")
    truth = sql("""SELECT lr.recommendation_key AS k, lr.status, lr.lp_run_key, lr.planning_cycle_date AS d
                   FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
                   WHERE pd.principal = 'unilever'""")
    cycle = plan["planning_cycle_date"]
    no_run = {r["k"] for r in truth if str(r["d"]) == cycle and r["status"] != "pending" and r["lp_run_key"] is None}
    earlier = {r["k"] for r in truth if str(r["d"]) != cycle}
    items = {i["recommendation_key"]: i for i in body["items"]}
    assert set(items) == {r["k"] for r in truth}, "cycle=all does not list every lp_recommendation row"
    flagged = {k for k, i in items.items() if i["outside_plan"]}
    assert flagged == no_run | earlier, "the rows flagged outside the plan are not the rows the plan clauses leave out"
    assert set(items) - flagged == {i["recommendation_key"] for i in plan["items"]}, "an unflagged row is not in the plan"
    assert len(items) - len(flagged) == plan["count"]
    assert no_run, ("live no longer holds a decided row that no LP run produced (row 4 of cycle 2026-03): A13's case is "
                    "not covered on live any more; update this test and STATE.md's plan note")
    for k in no_run:
        assert "no LP run produced it" in items[k]["plan_note"] and items[k]["status"] != "pending"
    for k in earlier:
        assert "earlier planning cycle" in items[k]["plan_note"]
    assert all(i["plan_note"] is None for k, i in items.items() if k not in flagged)
