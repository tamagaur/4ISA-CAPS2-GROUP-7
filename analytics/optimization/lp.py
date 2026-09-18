"""
analytics.optimization.lp — Safety stock, ROP, and LP optimization (PuLP/CBC).

Phase 5 (CLAUDE.md Steps 17–21):

  Step 17 — Safety Stock:
    SS_i = Z × σ_di   where Z = 1.28 (90% service level, hardcoded constant)
    σ_di from reconstructed daily demand series (granularity.py output).

    Step 18 — Reorder Point:
    ROP_i = Ŷ_(t+1,i) + SS_i
    Ŷ_(t+1,i) = one-month-ahead forecast (scripts/run_baseline_forecast.py's
    deployed MA3 output, Forecast_Result.forecast_value — SARIMA was
    retired; see analytics/forecasting/baseline.py's module docstring for
    the bake-off evidence).

  Step 19 — LP Model (PuLP):
    Decision variable: Q_i (replenishment quantity per SKU)
    Objective: Minimize Z = w₁·TC − w₂·SL + w₃·SC
      w₁ = 0.45, w₂ = 0.35, w₃ = 0.20
    Constraints:
      1. Warehouse capacity
      2. Supplier ceiling (per-principal allocation limit)
      3. Demand coverage (Q_i ≥ ROP_i)

  Step 20 — Solver:
    Solver: CBC (default PuLP).
    INFEASIBLE result → surface warning to dashboard. NEVER crash silently.
    Feasibility check BEFORE accepting Q_i values.

  Step 21 — Storage:
    Write Q_i, ROP_i, SS_i per SKU per planning cycle to Supabase.
    Link each record to ABC_Classification for dashboard filtering.

Constants:
  Z_SCORE = 1.28
  W1, W2, W3 = 0.45, 0.35, 0.20

Constants:
  Z_SCORE = 1.28
  W1, W2, W3 = 0.45, 0.35, 0.20

Implements:
  compute_safety_stock(sigma_d) -> float               (Step 17)
  compute_rop(forecast, safety_stock) -> float          (Step 18)
  build_lp_model(skus, warehouse_capacity, supplier_ceilings) -> pulp.LpProblem  (Step 19)
  solve_lp(model) -> dict[str, float] | None            (Step 20)

Objective modeling note (Step 19's Z = w1*TC - w2*SL + w3*SC, spelled out
here since the docstring names the terms but not their formulas — flagged,
not silently assumed, per this repo's convention):
  TC (Total Cost)     = sum(procurement_cost_i * Q_i)   — minimize
  SL (Service Level)  = sum(Q_i) / sum(ROP_i)           — maximize (hence
                         the minus sign: minimizing -SL maximizes SL)
  SC (Storage Cost)   = sum(storage_cost_i * Q_i)       — minimize
All three are linear in Q_i, so the objective stays a valid LP. Demand
coverage (Q_i >= ROP_i, Step 19 constraint 3) is a HARD constraint per
the spec above, not a soft penalty — so a tight warehouse_capacity or
supplier_ceiling relative to total ROP is exactly what produces the
INFEASIBLE case Step 20 requires solve_lp() to handle gracefully.
"""
from __future__ import annotations

from dataclasses import dataclass

import pulp

Z_SCORE = 1.28
W1, W2, W3 = 0.45, 0.35, 0.20

assert abs((W1 + W2 + W3) - 1.00) < 1e-9, "W1+W2+W3 must sum to 1.00 (Step 19 weighting)"


@dataclass
class SKUInput:
    """One SKU's inputs to the LP for a single planning cycle."""
    sku_id: str
    principal: str            # 'unilever' | 'delmonte' — must match a key in supplier_ceilings
    rop: float                # ROP_i from compute_rop() — hard lower bound on Q_i
    procurement_cost_per_unit: float
    storage_cost_per_unit: float


def compute_safety_stock(sigma_d: float, z: float = Z_SCORE) -> float:
    """Step 17: SS_i = Z x sigma_di, Z=1.28 fixed (90% service level).

    sigma_d is the standard deviation of the reconstructed DAILY demand
    series for one SKU (granularity.py's output) — this function does not
    reconstruct or aggregate that series itself, it only applies the
    formula, so it stays a pure, trivially-testable unit.
    """
    if sigma_d < 0:
        raise ValueError(f"sigma_d (a standard deviation) cannot be negative: {sigma_d}")
    return z * sigma_d


def compute_rop(forecast: float, safety_stock: float) -> float:
    """Step 18: ROP_i = Y_hat_(t+1,i) + SS_i."""
    if safety_stock < 0:
        raise ValueError(f"safety_stock cannot be negative: {safety_stock}")
    return forecast + safety_stock


def build_lp_model(
    skus: list[SKUInput],
    warehouse_capacity: float,
    supplier_ceilings: dict[str, float],
    weights: tuple[float, float, float] = (W1, W2, W3),
) -> pulp.LpProblem:
    """Step 19: builds (does not solve) the replenishment LP.

    Decision variables: one continuous Q_i >= 0 per SKU.
    Objective: minimize w1*TC - w2*SL + w3*SC (see module docstring for
    the TC/SL/SC formulas).
    Constraints:
      1. warehouse_capacity: sum(Q_i) <= warehouse_capacity
      2. supplier ceiling: sum(Q_i for SKUs of principal p) <= supplier_ceilings[p],
         for every principal present in `skus`
      3. demand_coverage: Q_i >= rop_i, per SKU (hard)

    Raises ValueError if `skus` is empty, or if any SKU's principal has
    no entry in supplier_ceilings (a silently-missing ceiling would mean
    that principal's SKUs are unconstrained, contradicting Step 19).

    The returned LpProblem carries an extra `.sku_variables` attribute
    (dict[sku_id, LpVariable]) so solve_lp() can map the solution back to
    SKU ids without re-deriving PuLP's internal variable names — a
    deviation from the bare `pulp.LpProblem` the original TODO signature
    implied, flagged here rather than silently done, since a plain
    LpProblem alone has no clean way to recover which variable is which SKU.
    """
    if not skus:
        raise ValueError("build_lp_model requires at least one SKU")

    w1, w2, w3 = weights
    if abs((w1 + w2 + w3) - 1.00) > 1e-9:
        raise ValueError(f"weights must sum to 1.00; got {w1 + w2 + w3}")

    missing_ceilings = {sku.principal for sku in skus} - set(supplier_ceilings)
    if missing_ceilings:
        raise ValueError(
            f"supplier_ceilings is missing an entry for principal(s) {missing_ceilings}; "
            f"every principal represented in `skus` must have an explicit ceiling."
        )

    problem = pulp.LpProblem("SSM_Replenishment", pulp.LpMinimize)

    variables: dict[str, pulp.LpVariable] = {
        sku.sku_id: pulp.LpVariable(f"Q_{sku.sku_id}", lowBound=0, cat="Continuous")
        for sku in skus
    }

    total_rop = sum(sku.rop for sku in skus)
    if total_rop <= 0:
        raise ValueError("sum of ROP across all SKUs must be positive to define service level")

    total_cost = pulp.lpSum(sku.procurement_cost_per_unit * variables[sku.sku_id] for sku in skus)
    service_level = pulp.lpSum(variables[sku.sku_id] for sku in skus) / total_rop
    storage_cost = pulp.lpSum(sku.storage_cost_per_unit * variables[sku.sku_id] for sku in skus)

    # ── Objective normalization (added 2026-09; see CHANGE LOG) ────────────
    # The three terms are measured in incommensurate units: TC and SC are
    # pesos (each Q_i carries a coefficient of ~1e1-1e2), while SL is a
    # dimensionless ratio whose per-unit coefficient is 1/total_rop (~1e-8
    # on real data). Weighting raw terms therefore compared a peso against
    # a ratio: the cost coefficients outweighed the service coefficient by
    # ~9 orders of magnitude, every objective coefficient stayed positive,
    # and CBC drove every Q_i to its lower bound. That is exactly what the
    # live 2026-03 cycle shows — Q_i == ROP_i on 227 of 251 rows (90%) —
    # i.e. w1/w2/w3 had no influence on the solution at all.
    #
    # Each term is now divided by its own value at the reference point
    # Q_i = ROP_i (the minimum feasible solution, given constraint 3), so
    # all three read 1.0 there and the weights trade like-for-like: a 1%
    # rise in normalized cost is directly comparable to a 1% rise in
    # normalized service. This rescales the objective ONLY — the feasible
    # region, the constraints and the reported Q_i units are unchanged,
    # and an LP objective is invariant to positive scaling of its terms.
    tc_ref = sum(sku.procurement_cost_per_unit * sku.rop for sku in skus)
    sc_ref = sum(sku.storage_cost_per_unit * sku.rop for sku in skus)
    # SL at the reference point is total_rop/total_rop = 1.0 by construction.

    # A zero reference means that term is identically zero across the whole
    # feasible region (every unit cost is 0), so it cannot be normalized and
    # contributes nothing. Falling back to 1.0 leaves it at its raw value
    # (still zero) rather than dividing by zero — never silently dropped.
    tc_scale = tc_ref if tc_ref > 0 else 1.0
    sc_scale = sc_ref if sc_ref > 0 else 1.0

    problem += (
        w1 * (total_cost / tc_scale)
        - w2 * service_level
        + w3 * (storage_cost / sc_scale),
        "objective",
    )

    # Constraint 1 — warehouse capacity
    problem += (
        pulp.lpSum(variables.values()) <= warehouse_capacity,
        "warehouse_capacity",
    )

    # Constraint 2 — supplier ceiling, per principal
    principals = {sku.principal for sku in skus}
    for principal in principals:
        principal_qty = pulp.lpSum(
            variables[sku.sku_id] for sku in skus if sku.principal == principal
        )
        problem += (
            principal_qty <= supplier_ceilings[principal],
            f"supplier_ceiling_{principal}",
        )

    # Constraint 3 — demand coverage, per SKU (hard lower bound)
    for sku in skus:
        problem += (
            variables[sku.sku_id] >= sku.rop,
            f"demand_coverage_{sku.sku_id}",
        )

    problem.sku_variables = variables  # type: ignore[attr-defined]
    return problem


def solve_lp(model: pulp.LpProblem) -> dict[str, float] | None:
    """Step 20: solves with CBC (PuLP's default solver).

    Returns a dict {sku_id: Q_i} on an Optimal solution. Returns None —
    NEVER raises — for Infeasible, Unbounded, or Undefined status, so the
    caller can surface a clear warning to the dashboard instead of the
    pipeline crashing. Feasibility is checked BEFORE any Q_i value is
    read off the model, per Step 20's checkpoint.
    """
    model.solve(pulp.PULP_CBC_CMD(msg=False))
    status = pulp.LpStatus[model.status]

    if status != "Optimal":
        return None

    sku_variables: dict[str, pulp.LpVariable] = getattr(model, "sku_variables", {})
    return {sku_id: float(var.value()) for sku_id, var in sku_variables.items()}
