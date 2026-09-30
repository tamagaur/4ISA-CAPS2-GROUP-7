"""
tests/optimization/test_lp.py — Tests for analytics.optimization.lp, the model
reworked 2026-09-29 (reports/LP_CLIENT_ALIGNMENT_PLAN_2026-09-29.md, Step B).

The plan's three behaviours:
  1. with enough allocation, every SKU is filled to its target;
  2. with a short allocation, the lowest-priority SKUs take the shortfall;
  3. an overstocked SKU orders 0.
Plus: the weights decide who comes up short (the old model ignored them,
reports/LP_READINESS.md B1), the aggregate cover rule, and the one way the LP
can still be infeasible.
"""

import pytest

from analytics.optimization.lp import (
    W1,
    W2,
    W3,
    Z_SCORE,
    SKUInput,
    build_lp_model,
    compute_safety_stock,
    net_need,
    solve_lp,
    target_stock,
    weekly_demand,
)
from analytics.optimization.lp_inputs import WEEKS_PER_MONTH

ROOMY = 1e12  # a warehouse or allocation that never binds


def _sku(sku_id, demand, target=0.0, stock=0.0, ss=0.0, cost=25.0, storage=0.5, weight=1.0, principal="unilever"):
    return SKUInput(sku_id, principal, demand=demand, target_stock=target, stock_on_hand=stock, safety_stock=ss,
                    procurement_cost_per_unit=cost, storage_cost_per_unit=storage, revenue_weight=weight)


def _solve(skus, allocation=ROOMY, warehouse=ROOMY, **kwargs):
    model = build_lp_model(skus, warehouse_capacity=warehouse, supplier_ceilings={"unilever": allocation}, **kwargs)
    return solve_lp(model), model


def test_safety_stock_formula():
    """SS = Z x sigma_d with Z=1.28 exactly."""
    assert compute_safety_stock(10.0) == pytest.approx(1.28 * 10.0)
    assert compute_safety_stock(0.0) == 0.0
    assert compute_safety_stock(10.0) == pytest.approx(Z_SCORE * 10.0)


def test_safety_stock_rejects_negative_sigma():
    with pytest.raises(ValueError):
        compute_safety_stock(-1.0)


def test_weights_sum_to_one():
    assert (W1 + W2 + W3) == pytest.approx(1.00)


def test_weekly_demand_uses_the_weeks_per_month_convention():
    assert weekly_demand(100 * WEEKS_PER_MONTH) == pytest.approx(100)


def test_target_is_demand_over_review_plus_lead_time_plus_safety_stock():
    monthly = 1000 * WEEKS_PER_MONTH  # 1,000 a week
    # 5 + 3 business days = 1.6 weeks of demand, plus SS
    assert target_stock(monthly, 500, review_days=5, lead_days=3) == pytest.approx(2100)
    # 'per-sku' cover rule: at least 3 weeks, and a lower floor changes nothing
    assert target_stock(monthly, 500, 5, 3, floor_weeks=3) == pytest.approx(3000)
    assert target_stock(monthly, 500, 5, 3, floor_weeks=1) == pytest.approx(2100)


@pytest.mark.parametrize("args", [(100, -1, 5, 3), (100, 10, -5, 3), (100, 10, 5, -3)])
def test_target_rejects_negative_inputs(args):
    with pytest.raises(ValueError):
        target_stock(*args)


def test_need_is_the_months_demand_plus_the_gap_to_target_net_of_stock():
    assert net_need(1000, 500, 300) == 1200
    assert net_need(1000, 500, 5000) == 0  # overstocked
    assert _sku("A", 1000, target=500, stock=300).need == 1200


def test_enough_allocation_fills_every_target():
    """Behaviour 1: every SKU ends the month at its target."""
    skus = [_sku("A", 1000, target=300, stock=200), _sku("B", 500, target=200), _sku("C", 800, target=100, stock=50)]
    result, _ = _solve(skus)
    assert result is not None
    for s in skus:
        assert result[s.sku_id] == pytest.approx(s.need)
        assert s.stock_on_hand + result[s.sku_id] - s.demand == pytest.approx(s.target_stock)


def test_short_allocation_is_all_used_and_the_lowest_priority_sku_takes_the_shortfall():
    """Behaviour 2: equal costs, so priority is the revenue weight."""
    skus = [_sku("TOP", 1000, weight=0.9), _sku("LOW", 1000, weight=0.1)]
    result, _ = _solve(skus, allocation=1500)
    assert sum(result.values()) == pytest.approx(1500)
    assert result["TOP"] == pytest.approx(1000)
    assert result["LOW"] == pytest.approx(500)


def test_a_short_allocation_trims_the_rest_of_the_target_before_anyones_demand():
    """LOW (low priority) has nothing on hand; TOP's stock covers its month.
    Filled as one block the weights would cut LOW first, below its month of
    demand. Layered, LOW's 500 of demand comes first, and TOP's higher
    priority only wins the target stock above that."""
    skus = [_sku("TOP", 500, target=1000, stock=500, weight=0.9), _sku("LOW", 500, target=500, weight=0.1)]
    result, _ = _solve(skus, allocation=1200)
    assert result["LOW"] == pytest.approx(500)
    assert result["TOP"] == pytest.approx(700)


def test_safety_stock_is_kept_before_the_rest_of_the_target():
    skus = [_sku("TOP", 500, target=1000, stock=500, ss=600, weight=0.9),
            _sku("LOW", 500, target=1000, stock=500, ss=600, weight=0.1)]
    result, _ = _solve(skus, allocation=1400)
    assert result["LOW"] == pytest.approx(600)  # keeps its safety stock
    assert result["TOP"] == pytest.approx(800)  # the other 200 of the rest goes to priority


def test_an_overstocked_sku_orders_zero_even_with_allocation_to_spare():
    """Behaviour 3."""
    skus = [_sku("FULL", 1000, target=300, stock=5000), _sku("B", 500, target=200)]
    result, _ = _solve(skus, allocation=10_000)
    assert result["FULL"] == 0
    assert result["B"] == pytest.approx(700)


def test_the_weights_decide_who_comes_up_short():
    """Regression for the old model's flaw (reports/LP_READINESS.md B1): its
    output never moved with w1/w2/w3. Here a short allocation must go where
    the weights say: to the cheap SKU when cost dominates, to the
    high-revenue one when service does."""
    skus = [_sku("CHEAP", 100, cost=10, weight=0.1), _sku("PRICEY", 100, cost=50, weight=0.9)]
    cost_first, _ = _solve(skus, allocation=100, weights=(0.90, 0.05, 0.05))
    service_first, _ = _solve(skus, allocation=100, weights=(0.05, 0.90, 0.05))
    assert cost_first["CHEAP"] == pytest.approx(100) and cost_first["PRICEY"] == pytest.approx(0)
    assert service_first["PRICEY"] == pytest.approx(100) and service_first["CHEAP"] == pytest.approx(0)


def test_the_order_moves_with_the_allocation():
    skus = [_sku("A", 1000, weight=0.6), _sku("B", 1000, weight=0.4)]
    tight, _ = _solve(skus, allocation=1200)
    looser, _ = _solve(skus, allocation=1600)
    assert sum(tight.values()) == pytest.approx(1200)
    assert sum(looser.values()) == pytest.approx(1600)
    assert tight != looser


def test_warehouse_capacity_counts_stock_on_hand():
    result, _ = _solve([_sku("A", 1000, target=400, stock=900)], warehouse=1000)
    assert result["A"] == pytest.approx(100)  # need is 500, but 900 is already on the shelves


def test_stock_already_above_capacity_is_infeasible_and_returns_none():
    """The one hard constraint left that stock alone can break. Returns None,
    never raises."""
    result, _ = _solve([_sku("A", 1000, stock=2000)], warehouse=1000)
    assert result is None


def _cover_case():
    # Each SKU's stock covers exactly its month, so its month-end stock is its
    # order. A 1-week rule needs 1,010 pesos at month end: 100 x 10 + 1 x 10.
    week = WEEKS_PER_MONTH
    return [
        _sku("HIGH_VALUE", 10 * week, target=20, stock=10 * week, cost=100, weight=0.1),
        _sku("LOW_VALUE", 10 * week, target=20, stock=10 * week, cost=1, weight=0.9),
    ]


def test_aggregate_cover_rule_picks_a_mix_that_meets_it():
    """Without the rule the weights send the short allocation to LOW_VALUE;
    the rule needs enough HIGH_VALUE stock to cover a week at cost."""
    without, _ = _solve(_cover_case(), allocation=20)
    assert without["LOW_VALUE"] == pytest.approx(20) and without["HIGH_VALUE"] == pytest.approx(0)

    with_rule, model = _solve(_cover_case(), allocation=20, min_cover_weeks=1)
    assert with_rule["HIGH_VALUE"] == pytest.approx(10, abs=1e-3)  # 100 x 10 + 1 x 10 = 1,010
    assert with_rule["LOW_VALUE"] == pytest.approx(10, abs=1e-3)
    assert model.stage_values["cover_short"] == pytest.approx(0, abs=1e-3)


def test_aggregate_cover_rule_is_soft_when_it_cannot_be_met():
    """No allocation at all: still a plan (all zero), and the shortfall is
    reported rather than the cycle failing."""
    result, model = _solve(_cover_case(), allocation=0, min_cover_weeks=1)
    assert result == {"HIGH_VALUE": 0, "LOW_VALUE": 0}
    assert model.stage_values["cover_short"] == pytest.approx(1010)


def test_build_lp_model_requires_ceiling_for_every_principal():
    with pytest.raises(ValueError):
        build_lp_model([_sku("SKU-1", 10)], warehouse_capacity=100, supplier_ceilings={})


def test_build_lp_model_rejects_empty_sku_list():
    with pytest.raises(ValueError):
        build_lp_model([], warehouse_capacity=100, supplier_ceilings={})


def test_build_lp_model_rejects_weights_that_dont_sum_to_one():
    with pytest.raises(ValueError):
        build_lp_model([_sku("A", 10)], warehouse_capacity=100, supplier_ceilings={"unilever": 10},
                       weights=(0.5, 0.5, 0.5))
