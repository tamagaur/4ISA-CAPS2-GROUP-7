"""
tests/optimization/test_lp.py — Tests for analytics.optimization.lp.

Phase 5 (CLAUDE.md Steps 17–21):
  test_safety_stock_formula       — SS = Z × σ_d with Z=1.28 exactly
  test_rop_formula                — ROP = forecast + SS
  test_lp_feasible_result         — Q_i values within allocation ceiling
  test_lp_infeasible_returns_none — infeasible LP returns None, does not raise
  test_weights_sum_to_one         — w1+w2+w3 == 1.00

Story 59 (warehouse volume + shelf-life bounds) and Story 61 (infeasibility
diagnostics) tests are grouped near the bottom of this file, below the
Story 55/58 config tests.
"""

import pytest

from analytics.optimization.lp import (
    W1,
    W2,
    W3,
    Z_SCORE,
    LPResult,
    SKUInput,
    build_lp_model,
    compute_rop,
    compute_safety_stock,
    diagnose_infeasibility,
    solve_lp,
    solve_lp_detailed,
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


def test_build_lp_model_defaults_to_config_weights():
    """Story 58: omitting `weights` should build the same objective as
    passing (W1, W2, W3) explicitly — proving the default is config-sourced,
    not a separate hardcoded value that happens to match."""
    skus = [SKUInput("SKU-1", "unilever", rop=100, procurement_cost_per_unit=2.0, storage_cost_per_unit=0.5)]
    ceilings = {"unilever": 1000}

    default_model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings=ceilings)
    explicit_model = build_lp_model(
        skus, warehouse_capacity=1000, supplier_ceilings=ceilings, weights=(W1, W2, W3)
    )

    default_coeffs = {v.name: c for v, c in default_model.objective.items()}
    explicit_coeffs = {v.name: c for v, c in explicit_model.objective.items()}
    assert default_coeffs == pytest.approx(explicit_coeffs)


def test_build_lp_model_weights_overridable_for_sensitivity_analysis():
    """Story 58: a caller can still pass a different weights tuple (e.g.
    for sensitivity analysis) without touching lp.py, and it actually
    changes the objective."""
    skus = [SKUInput("SKU-1", "unilever", rop=100, procurement_cost_per_unit=2.0, storage_cost_per_unit=0.5)]
    ceilings = {"unilever": 1000}

    default_model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings=ceilings)
    overridden_model = build_lp_model(
        skus, warehouse_capacity=1000, supplier_ceilings=ceilings, weights=(0.9, 0.05, 0.05)
    )

    default_coeff = dict(default_model.objective.items())[list(default_model.sku_variables.values())[0]]
    overridden_coeff = dict(overridden_model.objective.items())[
        list(overridden_model.sku_variables.values())[0]
    ]
    assert overridden_coeff != pytest.approx(default_coeff)


# ---------------------------------------------------------------------------
# Story 59 — SKUInput.resolved_max_order_qty()
# ---------------------------------------------------------------------------


def test_resolved_max_order_qty_prefers_explicit_value():
    sku = SKUInput(
        "SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1,
        max_order_qty=42.0, daily_demand=5.0, max_holding_days=100.0,
    )
    assert sku.resolved_max_order_qty() == 42.0


def test_resolved_max_order_qty_derived_from_daily_demand_and_holding_days():
    sku = SKUInput(
        "SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1,
        daily_demand=5.0, max_holding_days=4.0,
    )
    assert sku.resolved_max_order_qty() == pytest.approx(20.0)


def test_resolved_max_order_qty_none_when_unset():
    sku = SKUInput("SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1)
    assert sku.resolved_max_order_qty() is None


# ---------------------------------------------------------------------------
# Story 59 — volume-weighted warehouse capacity constraint
# ---------------------------------------------------------------------------


def test_warehouse_capacity_constraint_is_volume_weighted():
    """Each SKU's coefficient in the warehouse_capacity constraint should
    be its unit_volume, not a flat 1."""
    skus = [
        SKUInput("SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1, unit_volume=2.0),
        SKUInput("SKU-2", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1, unit_volume=3.5),
    ]
    model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings={"unilever": 1000})
    # PuLP sanitizes "-" to "_" in variable names internally (Q_SKU-1 -> Q_SKU_1).
    coeffs = {v.name: c for v, c in model.constraints["warehouse_capacity"].items()}
    assert coeffs["Q_SKU_1"] == pytest.approx(2.0)
    assert coeffs["Q_SKU_2"] == pytest.approx(3.5)


def test_warehouse_capacity_defaults_to_unweighted_when_unit_volume_omitted():
    """unit_volume defaults to 1.0, so the constraint reduces to the old
    sum(Q_i) <= warehouse_capacity behavior for callers that never set it."""
    skus = [
        SKUInput("SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1),
    ]
    model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings={"unilever": 1000})
    coeffs = {v.name: c for v, c in model.constraints["warehouse_capacity"].items()}
    assert coeffs["Q_SKU_1"] == pytest.approx(1.0)


def test_warehouse_capacity_infeasible_due_to_volume_even_though_unit_count_fits():
    """rop=100 alone would fit under capacity=300 as a raw count, but at
    unit_volume=5 the required volume is 500 > 300 — must be infeasible."""
    skus = [
        SKUInput("SKU-1", "unilever", rop=100, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1, unit_volume=5.0),
    ]
    model = build_lp_model(skus, warehouse_capacity=300, supplier_ceilings={"unilever": 1000})
    assert solve_lp(model) is None


# ---------------------------------------------------------------------------
# Story 59 — shelf-life / max order bound constraint
# ---------------------------------------------------------------------------


def test_shelf_life_limit_constraint_named_per_sku():
    skus = [
        SKUInput("SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1, max_order_qty=50.0),
        SKUInput("SKU-2", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1),
    ]
    model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings={"unilever": 1000})
    # PuLP sanitizes "-" to "_" in constraint names internally.
    assert "shelf_life_limit_SKU_1" in model.constraints
    assert "shelf_life_limit_SKU_2" not in model.constraints  # no bound set -> no constraint added


def test_shelf_life_limit_bounds_q_when_feasible():
    skus = [
        SKUInput("SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1, max_order_qty=50.0),
    ]
    model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings={"unilever": 1000})
    result = solve_lp(model)
    assert result is not None
    assert result["SKU-1"] <= 50.0 + 1e-6


def test_shelf_life_limit_via_max_holding_days_and_daily_demand():
    skus = [
        SKUInput(
            "SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1,
            daily_demand=5.0, max_holding_days=4.0,  # resolved max_order_qty = 20
        ),
    ]
    model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings={"unilever": 1000})
    result = solve_lp(model)
    assert result is not None
    assert result["SKU-1"] <= 20.0 + 1e-6


def test_shelf_life_limit_below_rop_is_infeasible():
    """demand_coverage (Q >= rop=100) directly conflicts with
    shelf_life_limit (Q <= max_order_qty=50) — infeasible by construction."""
    skus = [
        SKUInput("SKU-1", "unilever", rop=100, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1, max_order_qty=50.0),
    ]
    model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings={"unilever": 1000})
    assert solve_lp(model) is None


def test_build_lp_model_rejects_negative_unit_volume():
    skus = [
        SKUInput("SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1, unit_volume=-1.0),
    ]
    with pytest.raises(ValueError):
        build_lp_model(skus, warehouse_capacity=100, supplier_ceilings={"unilever": 100})


def test_build_lp_model_rejects_negative_max_order_qty():
    skus = [
        SKUInput("SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1, max_order_qty=-5.0),
    ]
    with pytest.raises(ValueError):
        build_lp_model(skus, warehouse_capacity=100, supplier_ceilings={"unilever": 100})


# ---------------------------------------------------------------------------
# Story 61 — diagnose_infeasibility()
# ---------------------------------------------------------------------------


def test_diagnose_infeasibility_warehouse_capacity_bottleneck():
    skus = [SKUInput("SKU-1", "unilever", rop=500, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1)]
    explanation, bottlenecks = diagnose_infeasibility(
        skus, warehouse_capacity=100, supplier_ceilings={"unilever": 1000}
    )
    assert "warehouse_capacity" in bottlenecks
    assert "Warehouse capacity (100)" in explanation
    assert "500" in explanation  # required volume


def test_diagnose_infeasibility_supplier_ceiling_bottleneck():
    skus = [SKUInput("SKU-1", "unilever", rop=500, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1)]
    explanation, bottlenecks = diagnose_infeasibility(
        skus, warehouse_capacity=1000, supplier_ceilings={"unilever": 100}
    )
    assert "supplier_ceiling_unilever" in bottlenecks
    assert "Supplier ceiling for unilever (100)" in explanation
    assert "500" in explanation


def test_diagnose_infeasibility_shelf_life_conflict():
    skus = [
        SKUInput("SKU-1", "unilever", rop=100, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1, max_order_qty=50.0),
    ]
    explanation, bottlenecks = diagnose_infeasibility(
        skus, warehouse_capacity=1000, supplier_ceilings={"unilever": 1000}
    )
    assert "shelf_life_limit_SKU-1" in bottlenecks
    assert "SKU-1" in explanation
    assert "shelf-life maximum order limit" in explanation


def test_diagnose_infeasibility_reports_multiple_bottlenecks_together():
    skus = [
        SKUInput("SKU-1", "unilever", rop=500, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1),
        SKUInput("SKU-2", "delmonte", rop=50, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1, max_order_qty=10.0),
    ]
    explanation, bottlenecks = diagnose_infeasibility(
        skus, warehouse_capacity=1, supplier_ceilings={"unilever": 1, "delmonte": 1000}
    )
    assert "warehouse_capacity" in bottlenecks
    assert "supplier_ceiling_unilever" in bottlenecks
    assert "shelf_life_limit_SKU-2" in bottlenecks


def test_diagnose_infeasibility_returns_empty_when_no_explicit_conflict():
    """No pre-check should fire for a plain feasible setup — the function
    is a diagnostic on request, not a general feasibility oracle."""
    skus = [SKUInput("SKU-1", "unilever", rop=10, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1)]
    explanation, bottlenecks = diagnose_infeasibility(
        skus, warehouse_capacity=1000, supplier_ceilings={"unilever": 1000}
    )
    assert explanation == ""
    assert bottlenecks == []


# ---------------------------------------------------------------------------
# Story 61 — solve_lp_detailed() / LPResult
# ---------------------------------------------------------------------------


def test_solve_lp_detailed_optimal_matches_solve_lp():
    skus = [
        SKUInput("SKU-1", "unilever", rop=100, procurement_cost_per_unit=2.0, storage_cost_per_unit=0.5),
    ]
    ceilings = {"unilever": 1000}
    plain_model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings=ceilings)
    plain_result = solve_lp(plain_model)

    detailed_model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings=ceilings)
    detailed = solve_lp_detailed(detailed_model, skus, warehouse_capacity=1000, supplier_ceilings=ceilings)

    assert isinstance(detailed, LPResult)
    assert detailed.status == "Optimal"
    assert detailed.explanation is None
    assert detailed.bottlenecks == []
    assert detailed.recommendations == pytest.approx(plain_result)


def test_solve_lp_detailed_reports_diagnosed_bottleneck_on_infeasible():
    skus = [SKUInput("SKU-1", "unilever", rop=500, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1)]
    ceilings = {"unilever": 100}  # ceiling below rop=500 -> infeasible
    model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings=ceilings)

    result = solve_lp_detailed(model, skus, warehouse_capacity=1000, supplier_ceilings=ceilings)

    assert result.status == "Infeasible"
    assert result.recommendations is None
    assert "supplier_ceiling_unilever" in result.bottlenecks
    assert result.explanation is not None
    assert "Supplier ceiling for unilever" in result.explanation


def test_solve_lp_preserves_backward_compatible_none_on_infeasible():
    """Re-affirms solve_lp()'s pre-Story-61 contract still holds: bare
    dict[str, float] | None, no diagnostics, never raises."""
    skus = [SKUInput("SKU-1", "unilever", rop=500, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.1)]
    model = build_lp_model(skus, warehouse_capacity=1000, supplier_ceilings={"unilever": 100})
    assert solve_lp(model) is None
