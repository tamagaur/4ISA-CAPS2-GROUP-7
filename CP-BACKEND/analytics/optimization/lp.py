"""
analytics.optimization.lp — Safety stock, ROP, and LP optimization (PuLP/CBC).

Phase 5 (CLAUDE.md Steps 17–21):

  Step 17 — Safety Stock:
    SS_i = Z × σ_di   where Z comes from config/analytics_params.yaml
    (service_level.z_score, default 1.28 / 90% service level — Story 55).
    σ_di from reconstructed daily demand series (granularity.py output).

  Step 18 — Reorder Point:
    ROP_i = Ŷ_(t+1,i) + SS_i
    Ŷ_(t+1,i) = one-month-ahead SARIMA forecast (sarima.py output).

  Step 19 — LP Model (PuLP):
    Decision variable: Q_i (replenishment quantity per SKU)
    Objective: Minimize Z = w₁·TC − w₂·SL + w₃·SC
      w₁, w₂, w₃ come from config/analytics_params.yaml (Story 58).
    Constraints:
      1. Warehouse capacity — volume-weighted (Story 59):
         sum(unit_volume_i * Q_i) <= warehouse_capacity
      2. Supplier ceiling (per-principal allocation limit)
      3. Demand coverage (Q_i ≥ ROP_i)
      4. Shelf-life / max order bound (Story 59, only for SKUs that set
         max_order_qty or max_holding_days): Q_i <= max_order_qty_i

  Step 20 — Solver:
    Solver: CBC (default PuLP).
    INFEASIBLE result → surface warning to dashboard. NEVER crash silently.
    Feasibility check BEFORE accepting Q_i values.
    solve_lp_detailed() (Story 61) additionally diagnoses *why* an
    infeasible/unbounded/undefined result happened, pinpointing which
    constraint is the bottleneck, instead of a bare None.

  Step 21 — Storage:
    Write Q_i, ROP_i, SS_i per SKU per planning cycle to Supabase.
    Link each record to ABC_Classification for dashboard filtering.

Constants:
  Z_SCORE, W1, W2, W3 — loaded from config/analytics_params.yaml at import
  time (analytics.config.load_analytics_params), not hardcoded (Story 55, 58).

Implements:
  compute_safety_stock(sigma_d) -> float               (Step 17)
  compute_rop(forecast, safety_stock) -> float          (Step 18)
  build_lp_model(skus, warehouse_capacity, supplier_ceilings) -> pulp.LpProblem  (Step 19)
  solve_lp(model) -> dict[str, float] | None            (Step 20)
  solve_lp_detailed(model, skus, warehouse_capacity, supplier_ceilings) -> LPResult  (Story 61)
  diagnose_infeasibility(skus, warehouse_capacity, supplier_ceilings) -> tuple[str, list[str]]  (Story 61)

Objective modeling note (Step 19's Z = w1*TC - w2*SL + w3*SC, spelled out
here since the docstring names the terms but not their formulas — flagged,
not silently assumed, per this repo's convention):
  TC (Total Cost)     = sum(procurement_cost_i * Q_i)   — minimize
  SL (Service Level)  = sum(Q_i) / sum(ROP_i)           — maximize (hence
                         the minus sign: minimizing -SL maximizes SL)
  SC (Storage Cost)   = sum(storage_cost_i * Q_i)       — minimize
All three are linear in Q_i, so the objective stays a valid LP. Demand
coverage (Q_i >= ROP_i, Step 19 constraint 3) is a HARD constraint per
the spec above, not a soft penalty — so a tight warehouse_capacity,
supplier_ceiling, or shelf-life bound relative to total ROP is exactly
what produces the INFEASIBLE case Step 20 requires solve_lp() to handle
gracefully (and solve_lp_detailed() to explain, Story 61).

Story 59 note on max_order_qty resolution: SKUInput.resolved_max_order_qty()
prefers an explicit max_order_qty when given; otherwise, if both
daily_demand and max_holding_days are set, it derives
daily_demand * max_holding_days. daily_demand isn't part of the original
Step 17/18 pipeline output, so it's an optional SKUInput field added
specifically to make the shelf-life bound computable — flagged here since
it's new surface area, not implied by the CLAUDE.md steps above.
"""
from __future__ import annotations

from dataclasses import dataclass

import pulp

from analytics.config import load_analytics_params

_params = load_analytics_params()
Z_SCORE = _params.z_score
W1, W2, W3 = _params.w1, _params.w2, _params.w3

assert abs((W1 + W2 + W3) - 1.00) < 1e-9, "W1+W2+W3 must sum to 1.00 (Step 19 weighting)"


@dataclass
class SKUInput:
    """One SKU's inputs to the LP for a single planning cycle."""
    sku_id: str
    principal: str            # 'unilever' | 'delmonte' — must match a key in supplier_ceilings
    rop: float                # ROP_i from compute_rop() — hard lower bound on Q_i
    procurement_cost_per_unit: float
    storage_cost_per_unit: float

    # Story 59 — warehouse volume and shelf-life bounds. All optional and
    # backwards-compatible: a SKUInput built the old way (positional/kwargs
    # covering only the five fields above) behaves exactly as before.
    unit_volume: float = 1.0
    shelf_life_days: float | None = None
    max_holding_days: float | None = None
    max_order_qty: float | None = None
    daily_demand: float | None = None

    def resolved_max_order_qty(self) -> float | None:
        """An explicit max_order_qty always wins. Otherwise, if both
        daily_demand and max_holding_days are set, derive the bound as
        daily_demand * max_holding_days (days-of-supply cap). Returns
        None if neither is available — meaning no shelf-life bound
        applies to this SKU."""
        if self.max_order_qty is not None:
            return self.max_order_qty
        if self.daily_demand is not None and self.max_holding_days is not None:
            return self.daily_demand * self.max_holding_days
        return None


@dataclass
class LPResult:
    """Story 61 — structured outcome of solve_lp_detailed(), so a caller
    (e.g. the dashboard) can show *why* replenishment failed instead of a
    blank state on infeasibility."""
    status: str                              # 'Optimal', 'Infeasible', 'Unbounded', 'Undefined'
    recommendations: dict[str, float] | None  # {sku_id: Q_i} if Optimal, else None
    explanation: str | None                   # Human-readable explanation if not Optimal
    bottlenecks: list[str]                    # Identified constraining factor(s), possibly several


def compute_safety_stock(sigma_d: float, z: float = Z_SCORE) -> float:
    """Step 17: SS_i = Z x sigma_di. Z defaults to the configured service
    level's Z-score (config/analytics_params.yaml, Story 55) but stays a
    plain parameter so callers/tests can override it explicitly.

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
      1. warehouse_capacity: sum(unit_volume_i * Q_i) <= warehouse_capacity
         (Story 59 — defaults to sum(Q_i) <= warehouse_capacity when every
         SKU's unit_volume is the default 1.0, so existing callers that
         never set unit_volume see unchanged behavior)
      2. supplier ceiling: sum(Q_i for SKUs of principal p) <= supplier_ceilings[p],
         for every principal present in `skus`
      3. demand_coverage: Q_i >= rop_i, per SKU (hard)
      4. shelf_life_limit_{sku_id} (Story 59): Q_i <= max_order_qty_i, only
         for SKUs where resolved_max_order_qty() is not None

    Raises ValueError if `skus` is empty, if any SKU's principal has no
    entry in supplier_ceilings (a silently-missing ceiling would mean that
    principal's SKUs are unconstrained, contradicting Step 19), or if any
    SKU has a negative unit_volume or resolved max_order_qty (nonsensical
    inputs, not a modeling infeasibility — those are reserved for
    diagnose_infeasibility to explain).

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

    negative_volume_skus = [sku.sku_id for sku in skus if sku.unit_volume < 0]
    if negative_volume_skus:
        raise ValueError(f"unit_volume cannot be negative: {negative_volume_skus}")

    negative_max_qty_skus = [
        sku.sku_id for sku in skus
        if (max_qty := sku.resolved_max_order_qty()) is not None and max_qty < 0
    ]
    if negative_max_qty_skus:
        raise ValueError(f"resolved max_order_qty cannot be negative: {negative_max_qty_skus}")

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

    problem += w1 * total_cost - w2 * service_level + w3 * storage_cost, "objective"

    # Constraint 1 — warehouse capacity, volume-weighted (Story 59)
    problem += (
        pulp.lpSum(sku.unit_volume * variables[sku.sku_id] for sku in skus) <= warehouse_capacity,
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

    # Constraint 4 — shelf-life / max order bound, per SKU (Story 59),
    # only added for SKUs that actually specify a bound.
    for sku in skus:
        max_qty = sku.resolved_max_order_qty()
        if max_qty is not None:
            problem += (
                variables[sku.sku_id] <= max_qty,
                f"shelf_life_limit_{sku.sku_id}",
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

    Kept deliberately dumb (bare dict/None, no diagnostics) for backward
    compatibility with existing callers — see solve_lp_detailed() (Story
    61) for the version that explains *why* an infeasible result happened.
    """
    model.solve(pulp.PULP_CBC_CMD(msg=False))
    status = pulp.LpStatus[model.status]

    if status != "Optimal":
        return None

    sku_variables: dict[str, pulp.LpVariable] = getattr(model, "sku_variables", {})
    return {sku_id: float(var.value()) for sku_id, var in sku_variables.items()}


def diagnose_infeasibility(
    skus: list[SKUInput],
    warehouse_capacity: float,
    supplier_ceilings: dict[str, float],
) -> tuple[str, list[str]]:
    """Story 61: inspects the *inputs* (not the solved model) for known,
    explicitly-checkable conflicts that make demand coverage impossible on
    their own, independent of what CBC reports. Every check runs
    regardless of earlier hits — this is diagnostic, not short-circuit —
    so multiple co-occurring bottlenecks (e.g. an over-tight warehouse cap
    AND an over-tight supplier ceiling) are all surfaced together.

    Returns (explanation, bottlenecks). explanation is "" and bottlenecks
    is [] if none of these explicit pre-checks explain the infeasibility —
    the caller (solve_lp_detailed) falls back to a generic "active
    constraints" summary in that case, since CBC can report Infeasible for
    combinations of constraints that no single pre-check here catches.
    """
    bottlenecks: list[str] = []
    explanations: list[str] = []

    # Warehouse capacity: total *required* (ROP-driven) volume vs capacity.
    # This mirrors constraint 1 in build_lp_model but evaluated at the hard
    # ROP floor, i.e. the smallest volume any feasible solution could use.
    required_volume = sum(sku.unit_volume * sku.rop for sku in skus)
    if required_volume > warehouse_capacity:
        bottlenecks.append("warehouse_capacity")
        diff = required_volume - warehouse_capacity
        explanations.append(
            f"Warehouse capacity ({warehouse_capacity}) is insufficient for total "
            f"required safety stock/ROP volume ({required_volume}). Shortfall: {diff}."
        )

    # Supplier ceiling: per principal, required ROP vs that principal's cap.
    principals = {sku.principal for sku in skus}
    for principal in sorted(principals):
        ceiling = supplier_ceilings.get(principal)
        if ceiling is None:
            continue
        required_rop = sum(sku.rop for sku in skus if sku.principal == principal)
        if required_rop > ceiling:
            bottlenecks.append(f"supplier_ceiling_{principal}")
            diff = required_rop - ceiling
            explanations.append(
                f"Supplier ceiling for {principal} ({ceiling}) is less than total "
                f"required ROP ({required_rop}). Shortfall: {diff}."
            )

    # Shelf-life / max order qty conflict: ROP floor exceeds the SKU's own
    # upper bound, i.e. the demand-coverage and shelf-life constraints
    # directly contradict each other for this one SKU.
    for sku in skus:
        max_qty = sku.resolved_max_order_qty()
        if max_qty is not None and sku.rop > max_qty:
            bottlenecks.append(f"shelf_life_limit_{sku.sku_id}")
            explanations.append(
                f"SKU '{sku.sku_id}' requires ROP of {sku.rop}, which exceeds its "
                f"shelf-life maximum order limit of {max_qty}."
            )

    return " ".join(explanations), bottlenecks


def solve_lp_detailed(
    model: pulp.LpProblem,
    skus: list[SKUInput],
    warehouse_capacity: float,
    supplier_ceilings: dict[str, float],
) -> LPResult:
    """Story 61: same CBC solve as solve_lp(), but returns a structured
    LPResult instead of a bare dict/None. On Optimal, `recommendations` is
    populated exactly like solve_lp()'s return value. On anything else,
    `explanation` and `bottlenecks` pinpoint which constraint(s) caused
    it, using diagnose_infeasibility() against the same `skus`,
    `warehouse_capacity`, and `supplier_ceilings` the model was built
    from — so a caller (e.g. the dashboard) can show *why* replenishment
    failed instead of a blank state.

    `model` must be the LpProblem returned by build_lp_model() for these
    same `skus`/`warehouse_capacity`/`supplier_ceilings` — this function
    solves it directly rather than rebuilding it, so the diagnostic
    inputs and the solved model always describe the same problem.
    """
    model.solve(pulp.PULP_CBC_CMD(msg=False))
    status = pulp.LpStatus[model.status]

    if status == "Optimal":
        sku_variables: dict[str, pulp.LpVariable] = getattr(model, "sku_variables", {})
        recommendations = {sku_id: float(var.value()) for sku_id, var in sku_variables.items()}
        return LPResult(status=status, recommendations=recommendations, explanation=None, bottlenecks=[])

    explanation, bottlenecks = diagnose_infeasibility(skus, warehouse_capacity, supplier_ceilings)

    if not explanation:
        # No single explicit pre-check explains it — fall back to a
        # readable dump of every active constraint so the caller still
        # gets something actionable instead of a bare status string.
        constraint_lines = [f"  {name}: {constraint}" for name, constraint in model.constraints.items()]
        explanation = (
            f"LP solver returned status '{status}' with no single obvious pre-check "
            f"failure. Active constraints:\n" + "\n".join(constraint_lines)
        )
        bottlenecks = [f"unresolved_{status.lower()}"]

    return LPResult(status=status, recommendations=None, explanation=explanation, bottlenecks=bottlenecks)
