"""analytics.demo.prescriptive: Del Monte demonstration safety stock / target stock / order quantity — the real
formulas (analytics.optimization.lp), no allocation or warehouse ceiling."""
import math

from analytics.demo.prescriptive import plan_category, sigma_d_for_category
from analytics.optimization.lp import compute_safety_stock
from analytics.optimization.lp import target_stock as real_target_stock
from analytics.params import PLACEHOLDERS, SERVICE_Z


def test_sigma_d_needs_at_least_two_months():
    assert sigma_d_for_category({"2024-01": 100.0}) is None
    assert sigma_d_for_category({}) is None


def test_sigma_d_is_a_real_number_for_a_varying_series():
    sigma = sigma_d_for_category({"2024-01": 100.0, "2024-02": 110.0, "2024-03": 90.0})
    assert sigma is not None and sigma > 0.0


def test_plan_matches_run_lp_safety_stock_for_and_target_stock_exactly():
    review_days, lead_days, target_weeks = PLACEHOLDERS["review_days"], PLACEHOLDERS["lead_days"], PLACEHOLDERS["target_weeks"]
    plan = plan_category("/A", forecast_quantity=1000.0, stock_on_hand=200.0, sigma_d=5.0)
    expected_ss = compute_safety_stock(5.0 * math.sqrt(review_days + lead_days), z=SERVICE_Z)
    expected_target = real_target_stock(1000.0, expected_ss, review_days, lead_days, floor_weeks=target_weeks)
    assert math.isclose(plan.safety_stock, expected_ss)
    assert math.isclose(plan.target_stock, expected_target)
    assert math.isclose(plan.order_qty, max(0.0, 1000.0 + expected_target - 200.0))


def test_order_qty_never_negative_when_stock_exceeds_target():
    plan = plan_category("/A", forecast_quantity=10.0, stock_on_hand=1_000_000.0, sigma_d=1.0)
    assert plan.order_qty == 0.0


def test_order_covers_the_forecast_months_own_demand():
    """DATA-6 (2026-10-20): stock above the target still has to be drawn down by the month's sales, so the order is
    F + T - S, not T - S. Stock exactly at the target used to order 0 against a full month of forecast demand."""
    probe = plan_category("/A", forecast_quantity=1000.0, stock_on_hand=0.0, sigma_d=5.0)
    at_target = plan_category("/A", forecast_quantity=1000.0, stock_on_hand=probe.target_stock, sigma_d=5.0)
    assert math.isclose(at_target.order_qty, 1000.0)
