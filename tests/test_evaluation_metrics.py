"""scripts/evaluation_metrics.py: the six pinned evaluation metrics (2026-11-17). No database: synthetic rows, and the
committed pin read as a file. The live comparison is tests/invariants/test_j_evaluation_metrics.py."""
import json

import numpy as np
import pandas as pd
import pytest

from scripts import evaluation_metrics as em


def _demand(rows):
    return pd.DataFrame(rows, columns=["product_key", "month", "qty"])


def _rows(rows):
    return pd.DataFrame(rows, columns=["product_key", "month", "forecast_pieces", "actual_pieces", "avg_monthly_pieces"])


def test_the_r2_benchmark_reads_only_months_before_t():
    """The benchmark of month t is knowable at t: changing month t or any later month must not move it."""
    s = em.demand_series(_demand([(1, "2024-01", 10), (1, "2024-02", 20), (1, "2024-03", 30), (1, "2024-04", 1000)]),
                         "2024-04")[1]
    assert em.earlier_mean(s, "2024-03") == 15.0
    s2 = s.copy()
    s2["2024-03"], s2["2024-04"] = 1e9, -5
    assert em.earlier_mean(s2, "2024-03") == 15.0
    assert np.isnan(em.earlier_mean(s, "2024-01")), "the first month has no earlier month, so no benchmark"


def test_r2_is_out_of_sample_not_the_hindsight_in_window_mean():
    # history 100, 100; scored months 200, 0, 200 forecast at 150, 50, 150
    dem = _demand([(1, "2025-01", 100), (1, "2025-02", 100), (1, "2025-03", 200), (1, "2025-04", 0), (1, "2025-05", 200)])
    rows = _rows([(1, "2025-03", 150, 200, 100), (1, "2025-04", 50, 0, 100), (1, "2025-05", 150, 200, 100)])
    series = em.demand_series(dem, "2025-05")
    R =rows.assign(product_key=1, f=rows.forecast_pieces.astype(float), a_raw=rows.actual_pieces.astype(float))
    R["a"], R["avg"] = R.a_raw.clip(lower=0), R.avg_monthly_pieces.astype(float)
    c = em.cell(R, {1}, "2025-03", series)
    b = [100.0, (100 + 100 + 200) / 3, (100 + 100 + 200 + 0) / 4]        # expanding means of the months before t
    a, f = np.array([200, 0, 200.0]), np.array([150, 50, 150.0])
    want = 1 - np.sum((a - f) ** 2) / np.sum((a - np.array(b)) ** 2)
    hindsight = 1 - np.sum((a - f) ** 2) / np.sum((a - a.mean()) ** 2)
    assert c["R2"] == pytest.approx(want)
    assert c["R2"] != pytest.approx(hindsight), "the R² must not use the scored months' own mean as its benchmark"
    assert (c["R2_products"], c["R2_product_months"]) == (1, 3)


def test_one_basis_a_net_negative_month_counts_as_zero_sold():
    rows = _rows([(1, "2025-03", 10, -4, 50), (1, "2025-04", 10, 20, 50)])
    out = em.compute(rows, _demand([(1, "2025-01", 50), (1, "2025-02", 40)]), set(), 0.05)["card"]["all_scored"]
    assert out["MAE"] == pytest.approx((10 + 10) / 2)                       # |10 - 0| and |10 - 20|, not |10 - (-4)|
    assert out["WAPE"] == pytest.approx(20 / 20)
    assert out["RMSE"] == pytest.approx(10.0)


def test_populations_near_zero_and_the_plan():
    rows = _rows([
        (1, "2025-03", 100, 100, 100), (1, "2025-04", 100, 90, 100),       # forecastable, planned
        (2, "2025-03", 100, 2, 100), (2, "2025-04", 100, 100, 100),        # a near-zero month (2 < 5% of 100)
        (3, "2025-03", 10, 0, 100),                                        # sold nothing in the window
        (4, "2025-03", 80, 100, 100),                                      # forecastable, not planned
    ])
    out = em.compute(rows, _demand([]), {1, 2, 3}, 0.05)["card"]
    assert out["all_scored"]["products"] == 4
    assert out["forecastable"]["products"] == 2
    assert out["order_plan"]["products"] == 1, "the order plan is the forecastable products with a plan row"
    assert out["all_scored"]["MAPE_products"] == 3, "a product that sold nothing has no percentage"


def test_mase_scale_is_the_naive_error_before_the_window_only():
    dem = _demand([(1, "2025-01", 100), (1, "2025-02", 120), (1, "2025-03", 1000), (1, "2025-04", 0)])
    s = em.demand_series(dem, "2025-04")[1]
    assert em.naive_scale(s, "2025-03") == 20.0                           # |120 - 100|; the window's jump is not in the scale
    rows = _rows([(1, "2025-03", 960, 1000, 110), (1, "2025-04", 40, 0, 110)])
    out = em.compute(rows, dem, set(), 0.05)["card"]["all_scored"]
    assert out["MASE"] == pytest.approx(((40 + 40) / 2) / 20.0)


def test_a_blank_capture_is_unknown_not_zero():
    s = em.demand_series(_demand([(1, "2025-01", 10), (1, "2025-02", np.nan), (1, "2025-03", 30)]), "2025-03")[1]
    assert np.isnan(s["2025-02"]) and em.earlier_mean(s, "2025-03") == 10.0
    assert np.isnan(em.naive_scale(s, "2025-03")), "no pair of known neighbouring months"


def test_a_month_with_no_row_is_zero_sold():
    s = em.demand_series(_demand([(1, "2025-01", 10), (1, "2025-03", 30)]), "2025-03")[1]
    assert s["2025-02"] == 0.0


def _pin():
    return json.loads(em.PIN_JSON.read_text(encoding="utf-8"))


def test_compare_flags_every_kind_of_divergence():
    pin = _pin()
    assert em.compare(pin, json.loads(json.dumps(pin))) == []
    moved = json.loads(json.dumps(pin))
    moved["figures"]["card"]["forecastable"]["MAE"] += 1
    assert any("card.forecastable.MAE" in b for b in em.compare(pin, moved))
    gone = json.loads(json.dumps(pin))
    del gone["figures"]["full"]["order_plan"]["R2"]
    assert any("no such figure" in b for b in em.compare(pin, gone))
    redefined = json.loads(json.dumps(pin))
    redefined["definitions"]["R2"] = "1 - SSE/SST against the mean of the scored months"
    assert any(b.startswith("definitions") for b in em.compare(pin, redefined))
    recount = json.loads(json.dumps(pin))
    recount["figures"]["card"]["order_plan"]["products"] += 1
    assert any("order_plan.products" in b for b in em.compare(pin, recount))
    replanned = json.loads(json.dumps(pin))
    replanned["source"]["plan"]["lp_run_key"] = 11
    assert any("lp_run_key" in b for b in em.compare(pin, replanned))


def test_the_committed_pin_is_this_codes_and_its_markdown_is_its_rendering():
    pin = _pin()
    for key in ("basis", "windows", "populations", "definitions", "context"):
        assert pin[key] == json.loads(json.dumps(getattr(em, key.upper()))), f"{key} changed without a re-pin"
    assert em.PIN_MD.read_text(encoding="utf-8") == em.render_md(pin)
    assert em.cross_pin(pin) == [], "the full-span WAPE over every scored product is not the published headline"
    cells = [(w, p) for w in em.WINDOWS for p in em.POPULATION_ORDER]
    for w, p in cells:
        c = pin["figures"][w][p]
        for m in ("MAE", "RMSE", "WAPE", "MAPE", "MASE", "R2"):
            assert c[m] is not None and c[f"{m}_products"] > 0 and c[f"{m}_product_months"] > 0, (w, p, m)


def test_the_means_are_pinned_with_and_without_the_named_product():
    """Mean MASE / mean R² beside the medians (2026-11-18): a mean follows the worst product, so it is given over every product
    and without the one named SKU. A median ignores that product, so it must not move."""
    dem = _demand([(k, m, q) for k in (1, 2, 3) for m, q in (("2025-01", 100), ("2025-02", 110), ("2025-03", 100), ("2025-04", 105),
                                                              ("2025-05", 95), ("2025-06", 100))])
    rows = _rows([(1, "2025-04", 105, 105, 100), (1, "2025-05", 95, 95, 100), (1, "2025-06", 100, 100, 100),
                  (2, "2025-04", 100, 105, 100), (2, "2025-05", 100, 95, 100), (2, "2025-06", 100, 100, 100),
                  (3, "2025-04", 5000, 105, 100), (3, "2025-05", 5000, 95, 100), (3, "2025-06", 5000, 100, 100)])
    series = em.demand_series(dem, "2025-06")
    R = rows.assign(product_key=rows.product_key.astype(int), f=rows.forecast_pieces.astype(float), a_raw=rows.actual_pieces.astype(float))
    R["a"], R["avg"] = R.a_raw.clip(lower=0), R.avg_monthly_pieces.astype(float)
    every = em.cell(R, {1, 2, 3}, "2025-04", series)
    without = em.cell(R, {1, 2, 3}, "2025-04", series, frozenset({3}))
    assert every["R2_mean"] < without["R2_mean_without_sku"] - 100          # product 3's R² is hugely negative
    assert every["R2_mean_without_sku"] == every["R2_mean"]                 # nothing excluded: the two means agree
    assert (without["R2_products"], without["R2_mean_without_sku_products"]) == (3, 2)
    assert without["MASE_mean_without_sku_products"] == without["MASE_products"] - 1
    assert without["R2"] == every["R2"]                                     # the median does not move when the mean does
