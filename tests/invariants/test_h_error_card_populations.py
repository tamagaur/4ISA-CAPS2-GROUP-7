"""(h) The error card names the population behind each figure, and the planned-products line is the plan's.

Guards against: a figure read as being about the products the system orders when it is about every scored product.
The card's MAPE covers the Tier A products a percentage can score (179 on 2026-11-16), its two WAPEs every scored
product (233), and the plan orders for 115. Since 2026-11-16 the card carries the plan's own line
(backend/marts.planned_products_block): the headline's measure, near-zero treatment and window on the products with a
row in the current cycle's plan. Here that line is recomputed from live by SQL written independently of the route, and
its population is held equal to the plan GET /recommendations serves.
"""
import pytest

# The card's default run and window are read from the card itself; this is the headline's arithmetic and nothing else:
# per product, the mean of |forecast - actual| / actual over its months with actual > 0; products with a near-zero month
# (0 < actual < 5% of the 12-month average) set apart; the median over the plan's products that remain.
_SQL = """
WITH scored AS (
    SELECT a.product_key, a.forecast_pieces AS f, a.actual_pieces AS a, a.avg_monthly_pieces AS avg
    FROM mart.accuracy_mart a JOIN mart.forecast_run r ON r.run_id = a.run_id
    WHERE r.label = :label AND a.month BETWEEN :start AND :end AND a.actual_pieces IS NOT NULL AND a.forecast_pieces IS NOT NULL
), p AS (
    SELECT product_key, COUNT(*) FILTER (WHERE a > 0 AND avg > 0 AND a < :share * avg) AS near_zero,
           AVG(ABS(f - a) / a) FILTER (WHERE a > 0) AS mape, COUNT(*) FILTER (WHERE a > 0) AS sold
    FROM scored GROUP BY product_key
)
SELECT COUNT(*) AS scored, COUNT(*) FILTER (WHERE sold > 0) AS with_percentage,
       COUNT(*) FILTER (WHERE planned) AS plan_scored,
       COUNT(*) FILTER (WHERE planned AND near_zero > 0) AS plan_near_zero,
       COUNT(*) FILTER (WHERE planned AND near_zero = 0 AND sold = 0) AS plan_no_percentage,
       COUNT(*) FILTER (WHERE planned AND near_zero = 0 AND sold > 0) AS plan_products,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY mape) FILTER (WHERE planned AND near_zero = 0 AND sold > 0) AS plan_median,
       AVG(mape) FILTER (WHERE planned AND near_zero = 0 AND sold > 0) AS plan_mean,
       COUNT(*) FILTER (WHERE planned AND near_zero = 0 AND mape >= 1) AS plan_at_100,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY mape) FILTER (WHERE near_zero = 0 AND sold > 0) AS all_median,
       COUNT(*) FILTER (WHERE near_zero = 0 AND sold > 0) AS all_products
FROM (SELECT p.*, p.product_key = ANY(:plan_keys) AS planned FROM p) p
"""


@pytest.fixture(scope="module")
def card(get):
    return get("/dashboard/accuracy?principal=unilever")


def test_the_planned_line_is_the_headline_measure_on_the_live_plans_products(card, plan, sql):
    from backend import marts
    block = card["mape"]["planned_products"]
    assert block is not None and len(card["run_labels"]) == 1
    keys = [r["product_key"] for r in sql(
        "SELECT lr.product_key FROM lp_recommendation lr WHERE lr.recommendation_key = ANY(:k)",
        k=[i["recommendation_key"] for i in plan["items"]])]
    assert len(set(keys)) == plan["count"]
    want = sql(_SQL, label=card["run_labels"][0], start=card["start_period"], end=card["end_period"],
               share=marts.NEAR_ZERO_SHARE, plan_keys=keys)[0]
    # the population: the plan GET /recommendations serves, its cycle and its run
    assert (block["plan_rows"], block["plan_products"]) == (plan["count"], plan["count"])
    assert block["planning_cycle_date"] == plan["planning_cycle_date"]
    assert block["lp_run_key"] == plan["lp_model"]["run"]["run_key"]
    # the figure, and where every plan product went
    assert block["products"] == want["plan_products"]
    assert block["value"] == pytest.approx(float(want["plan_median"]), abs=1e-6)
    assert block["mean"] == pytest.approx(float(want["plan_mean"]), abs=1e-6)
    assert block["at_or_above_100_pct"] == want["plan_at_100"]
    assert block["near_zero_products"] == want["plan_near_zero"]
    assert block["no_percentage_products"] == want["plan_no_percentage"]
    assert block["not_scored_products"] == plan["count"] - want["plan_scored"]
    assert (block["products"] + block["near_zero_products"] + block["no_percentage_products"]
            + block["not_scored_products"]) == plan["count"], "the line does not account for every plan product"
    # the same SQL gives the headline it is compared with: one basis, two populations
    assert card["mape"]["value"] == pytest.approx(float(want["all_median"]), abs=1e-6)
    assert card["mape"]["products"] == want["all_products"]


def test_the_card_states_the_population_of_each_figure(card, get):
    m = card["mape"]
    # the two WAPEs are over every scored product; the MAPE figures over the ones a percentage can score
    assert m["scored_products"] == card["products"]
    assert m["all_products"]["products"] + 0 <= card["products"]
    assert m["products"] + m["near_zero_flag"]["products"] == m["all_products"]["products"]
    assert m["planned_products"]["products"] <= m["products"], "a planned product scored outside the headline's population"
    # the Dashboard's copy of the card is the same card
    dash = get("/dashboard?principal=unilever")["forecast_accuracy"]
    assert dash["mape"] == m and (dash["products"], dash["company_total"], dash["typical_product_weighted"]) == (
        card["products"], card["company_total"], card["typical_product_weighted"])


def test_the_pooled_wape_is_on_the_manuscripts_rule(card, sql):
    """A net-negative month counts as 0 sold (scripts/accuracy_as_served.py, docs/ACCURACY_AS_SERVED.md), on the card as in
    the manuscript's headline. Recomputed from live by SQL written apart from the route (2026-11-17: the card divided the raw
    sums until then, 32.04% against 31.95% on its default window)."""
    assert len(card["run_labels"]) == 1
    want = sql("""SELECT SUM(ABS(a.forecast_pieces - GREATEST(a.actual_pieces, 0))) / SUM(GREATEST(a.actual_pieces, 0)) AS ruled,
                         SUM(ABS(a.forecast_pieces - a.actual_pieces)) / SUM(a.actual_pieces) AS raw
                  FROM mart.accuracy_mart a JOIN mart.forecast_run r ON r.run_id = a.run_id
                  WHERE r.label = :label AND a.month BETWEEN :start AND :end
                    AND a.actual_pieces IS NOT NULL AND a.forecast_pieces IS NOT NULL""",
               label=card["run_labels"][0], start=card["months"][0], end=card["months"][-1])[0]
    assert card["typical_product_weighted"]["value"] == card["wape_pieces"] == pytest.approx(float(want["ruled"]), abs=1e-6)
    assert card["abs_miss_pieces"] / card["actual_pieces"] == pytest.approx(float(want["raw"]), abs=1e-6), "the raw sums moved"
