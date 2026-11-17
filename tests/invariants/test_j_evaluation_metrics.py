"""(j) The six pinned evaluation metrics equal live, and the error card serves the pinned figures.

Guards against: two places in the project stating different values for the same measure. The authoritative set is
docs/EVALUATION_METRICS.json (scripts/evaluation_metrics.py: MAE, RMSE, MAPE, WAPE, MASE, R² x forecastable / order plan /
all scored x card window / full span). Here it is recomputed from live (any divergence fails), and the figures the error card
serves for the pinned window are held equal to the pinned cell of the SAME population: the pooled WAPE to "all scored"
(233 products), the MAPE to "forecastable" (179), the planned-products line to "order plan" (100), the every-product MAPE to
"all scored" (218 with a percentage). The card rounds to 6 decimals, hence the tolerance.
"""
import json

import pytest

from scripts import evaluation_metrics as em


@pytest.fixture(scope="module")
def pin():
    return json.loads(em.PIN_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def card(get, pin):
    w = pin["windows"]["card"]
    return get(f"/dashboard/accuracy?principal=unilever&start_period={w['start']}&period={w['end']}")


def test_the_pinned_set_equals_live(live_env, capsys):
    rc = em.cmd_verify()
    out = capsys.readouterr().out
    assert rc == 0, out


_NEAR_ZERO_SQL = """
WITH s AS (SELECT a.product_key, a.forecast_pieces AS f, a.actual_pieces AS a, a.avg_monthly_pieces AS avg
           FROM mart.accuracy_mart a JOIN mart.forecast_run r ON r.run_id = a.run_id
           JOIN product_dimension pd ON pd.product_key = a.product_key
           WHERE r.label = :label AND pd.principal = 'unilever' AND a.month BETWEEN :start AND :end
             AND a.actual_pieces IS NOT NULL AND a.forecast_pieces IS NOT NULL),
     nz AS (SELECT product_key FROM s GROUP BY product_key
            HAVING COUNT(*) FILTER (WHERE a > 0 AND avg > 0 AND a < :share * avg) > 0)
SELECT COUNT(DISTINCT product_key) AS products, COUNT(*) AS months,
       AVG(ABS(f - GREATEST(a, 0))) AS mae, SQRT(AVG(POWER(f - GREATEST(a, 0), 2))) AS rmse
FROM s JOIN nz USING (product_key)
"""


def test_the_error_card_serves_the_pinned_figures_of_each_population(card, pin, sql):
    from backend import marts
    w = pin["windows"]["card"]
    # the near-zero line: its own population, on the pinned set's basis (a net-negative month = 0 sold), from SQL written here
    nz = sql(_NEAR_ZERO_SQL, label=pin["source"]["run"]["label"], start=w["start"], end=w["end"], share=marts.NEAR_ZERO_SHARE)[0]
    z = card["mape"]["near_zero_flag"]
    assert (z["products"], z["product_months"]) == (nz["products"], nz["months"])
    assert z["mae_pieces"] == pytest.approx(float(nz["mae"]), abs=0.005)
    assert z["rmse_pieces"] == pytest.approx(float(nz["rmse"]), abs=0.005)
    cells = pin["figures"]["card"]
    w = pin["windows"]["card"]
    assert (card["start_period"], card["end_period"]) == (w["start"], w["end"])
    assert card["run_labels"] == [pin["source"]["run"]["label"]], "the card did not read the pinned backtest run"
    # the pooled WAPE in pieces: every scored product
    assert card["products"] == cells["all_scored"]["WAPE_products"]
    assert card["typical_product_weighted"]["value"] == pytest.approx(cells["all_scored"]["WAPE"], abs=1e-6)
    m = card["mape"]
    # the MAPE headline: the forecastable products
    assert m["products"] == cells["forecastable"]["MAPE_products"]
    assert m["value"] == pytest.approx(cells["forecastable"]["MAPE"], abs=1e-6)
    assert m["mean"] == pytest.approx(cells["forecastable"]["MAPE_mean"], abs=1e-6)
    # every product a percentage can score, the near-zero ones included
    assert m["all_products"]["products"] == cells["all_scored"]["MAPE_products"]
    assert m["all_products"]["value"] == pytest.approx(cells["all_scored"]["MAPE"], abs=1e-6)
    # the planned-products line: the order plan
    pl = m["planned_products"]
    assert (pl["planning_cycle_date"], pl["lp_run_key"]) == (pin["source"]["plan"]["planning_cycle_date"],
                                                            pin["source"]["plan"]["lp_run_key"])
    assert pl["products"] == cells["order_plan"]["MAPE_products"]
    assert pl["value"] == pytest.approx(cells["order_plan"]["MAPE"], abs=1e-6)
    assert pl["mean"] == pytest.approx(cells["order_plan"]["MAPE_mean"], abs=1e-6)
