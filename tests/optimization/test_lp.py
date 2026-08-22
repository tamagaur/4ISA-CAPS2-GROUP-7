"""
tests/optimization/test_lp.py — Tests for analytics.optimization.lp.

Phase 5 (CLAUDE.md Steps 17–21):
  test_safety_stock_formula       — SS = Z × σ_d with Z=1.28 exactly
  test_rop_formula                — ROP = forecast + SS
  test_lp_feasible_result         — Q_i values within allocation ceiling
  test_lp_infeasible_returns_none — infeasible LP returns None, does not raise
  test_weights_sum_to_one         — w1+w2+w3 == 1.00

"""

import pytest

from analytics.optimization.lp import (
    W1,
    W2,
    W3,
    Z_SCORE,
    SKUInput,
    build_lp_model,
    compute_rop,
    compute_safety_stock,
    solve_lp,
)


def test_safety_stock_formula():
    """SS = Z x sigma_d with Z=1.28 exactly."""
    assert compute_safety_stock(10.0) == pytest.approx(1.28 * 10.0)
    assert compute_safety_stock(0.0) == 0.0
    assert compute_safety_stock(10.0) == pytest.approx(Z_SCORE * 10.0)


def test_safety_stock_rejects_negative_sigma():
    with pytest.raises(ValueError):
        compute_safety_stock(-1.0)


def test_rop_formula():
    """ROP = forecast + SS."""
    ss = compute_safety_stock(5.0)
    assert compute_rop(forecast=100.0, safety_stock=ss) == pytest.approx(100.0 + ss)
    assert compute_rop(50.0, 0.0) == 50.0


def test_weights_sum_to_one():
    assert (W1 + W2 + W3) == pytest.approx(1.00)


def test_lp_feasible_result():
    """Q_i values stay within the per-principal allocation ceiling and
    honor the demand-coverage floor (Q_i >= ROP_i)."""
    skus = [
        SKUInput("SKU-1", "unilever", rop=100, procurement_cost_per_unit=2.0, storage_cost_per_unit=0.5),
        SKUInput("SKU-2", "unilever", rop=150, procurement_cost_per_unit=1.5, storage_cost_per_unit=0.3),
        SKUInput("SKU-3", "delmonte", rop=80, procurement_cost_per_unit=3.0, storage_cost_per_unit=0.4),
    ]
    model = build_lp_model(
        skus,
        warehouse_capacity=1000,
        supplier_ceilings={"unilever": 400, "delmonte": 200},
    )
    result = solve_lp(model)

    assert result is not None
    unilever_total = result["SKU-1"] + result["SKU-2"]
    delmonte_total = result["SKU-3"]
    assert unilever_total <= 400 + 1e-6
    assert delmonte_total <= 200 + 1e-6
    for sku in skus:
        assert result[sku.sku_id] >= sku.rop - 1e-6


def test_lp_infeasible_returns_none():
    """An infeasible LP (ROP demand exceeds the supplier ceiling) returns
    None and does not raise."""
    skus = [
        SKUInput("SKU-1", "unilever", rop=500, procurement_cost_per_unit=2.0, storage_cost_per_unit=0.5),
    ]
    model = build_lp_model(
        skus,
        warehouse_capacity=1000,
        supplier_ceilings={"unilever": 100},  # ceiling below rop=500 -> infeasible
    )
    result = solve_lp(model)
    assert result is None


def test_build_lp_model_requires_ceiling_for_every_principal():
    skus = [
        SKUInput("SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1),
    ]
    with pytest.raises(ValueError):
        build_lp_model(skus, warehouse_capacity=100, supplier_ceilings={})


def test_build_lp_model_rejects_empty_sku_list():
    with pytest.raises(ValueError):
        build_lp_model([], warehouse_capacity=100, supplier_ceilings={})
