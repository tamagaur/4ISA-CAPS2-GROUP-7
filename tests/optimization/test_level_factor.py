"""scripts.run_lp.level_factor: safety stock follows the level (analytics.params.SAFETY_STOCK_FOLLOWS_LEVEL)."""
from __future__ import annotations

import math

import pandas as pd

from analytics.params import SAFETY_STOCK_FOLLOWS_LEVEL
from scripts.run_lp import TREATMENT_QUERY, level_factor


def _hist(qty: dict[str, float | None]) -> pd.DataFrame:
    return pd.DataFrame({"period": list(qty), "total_quantity": list(qty.values()), "sku_code": "X",
                         "product_key": 1, "principal": "unilever", "total_amount": 0.0})


def test_forecast_zero_gives_zero_factor():
    assert level_factor(_hist({"2025-01": 100, "2025-02": 120, "2025-03": 80}), 0.0) == 0.0


def test_never_above_one_for_a_rising_product():
    assert level_factor(_hist({"2025-01": 100, "2025-02": 100}), 500.0) == 1.0


def test_ratio_to_the_mean_of_the_months_sigma_reads():
    assert math.isclose(level_factor(_hist({"2025-01": 100, "2025-02": 300}), 100.0), 0.5)


def test_absent_month_is_a_zero_sale_month_and_blank_is_left_out():
    # 2025-02 has no row (a zero), 2025-04 is blank (excluded): mean = (300 + 0 + 300) / 3 = 200
    h = _hist({"2025-01": 300, "2025-03": 300, "2025-04": None})
    assert math.isclose(level_factor(h, 100.0), 0.5)


def test_end_period_extends_with_zero_months():
    # rows to 2025-02, end 2025-04: mean = (200 + 200 + 0 + 0) / 4 = 100
    assert math.isclose(level_factor(_hist({"2025-01": 200, "2025-02": 200}), 50.0, "2025-04"), 0.5)


def test_no_quantity_or_zero_history_leaves_sigma_alone():
    assert level_factor(_hist({"2025-01": None}), 10.0) == 1.0
    assert level_factor(_hist({"2025-01": 0.0, "2025-02": 0.0}), 10.0) == 1.0


def test_switch_is_off_until_decided_and_query_reads_the_treatment():
    assert SAFETY_STOCK_FOLLOWS_LEVEL in (False, "treated", "all")
    assert SAFETY_STOCK_FOLLOWS_LEVEL is False      # the plan is unchanged until Kelvin decides
    assert "model_params->>'treatment'" in TREATMENT_QUERY
