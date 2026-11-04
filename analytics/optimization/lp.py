"""
analytics.optimization.lp — safety stock, target stock and the replenishment
LP (PuLP/CBC).

Reworked 2026-09-29 to plan the way SSM orders (reports/
LP_CLIENT_ALIGNMENT_PLAN_2026-09-29.md, Step B, agreed with Yuan): weekly
purchase orders against a yearly supplier allocation, keeping about 3 weeks
of sales in stock (Sir Abe, SSM). The model it replaces ordered
Q_i >= ROP_i = forecast + SS for every SKU, ignored stock on hand, and with
flat costs always returned Q_i = ROP_i (reports/LP_READINESS.md, B1).

Per SKU i, for one monthly planning cycle (quantities in pieces):

  SS_i    = Z x sigma_i, Z = 1.28 (90% service level). sigma_i is the demand
            variability over the review period + lead time (scripts/run_lp.py's
            safety_stock_for; analytics.params.SAFETY_STOCK_ASSUMPTION states what
            that scaling assumes).
  w_i     = F_i / WEEKS_PER_MONTH, the weekly rate of the month's forecast F_i.
  T_i     = w_i x (R + L) / 5 + SS_i, the target stock: demand over the review
            period R plus the lead time L (business days), plus safety stock.
            Under the 'per-sku' cover rule T_i is at least N x w_i.
  need_i  = max(0, F_i + T_i - S_i): the month's demand plus the gap to the
            target, net of the stock on hand S_i.

Decision variable: 0 <= Q_i <= need_i, the month's order, one figure per SKU.
Q_i never exceeds the need, so an overstocked SKU orders 0.

The 8-business-day review-and-lead window (R + L in T_i and SS_i) assumes SSM's
own stated practice of ordering weekly (Sir Abe), which the system neither
implements nor verifies: no code here or in the app splits Q_i into weekly
purchase orders, and nothing checks how SSM actually orders.

Constraints:
  1. warehouse   sum(S_i + Q_i) <= W. Counts the month's deliveries as if
                 they all arrived at once, so it errs on the safe side.
  2. allocation  sum(Q_i) <= A_p for each principal p.
  3. cover rule  'aggregate' only, soft: the planned month-end stock, valued
                 at cost c_i, covers N weeks of the planned SKUs' sales:
                 sum(c_i (S_i + Q_i - F_i)) + short >= N x sum(c_i w_i).

Each need is filled in three layers, in this order of importance:
  demand         max(0, F_i - S_i): this month's sales, so no SKU is planned
                 to run out
  safety stock   up to a month-end stock of SS_i
  rest of target up to T_i (the demand over the review period + lead time,
                 and the 'per-sku' 3-week floor)

Objective, in stages; each holds the ones before at their optimum:
  1. fill     maximize the pieces ordered in each layer, one layer at a time:
              order as much of the need as the allocation and warehouse
              allow, and when that isn't all of it, cut the rest of the
              target first and this month's demand last.
  2. cover    minimize `short` (skipped under 'per-sku').
  3. weights  minimize w1 x TC - w2 x SL + w3 x SC, each term relative to its
              value at full fill (Q = need):
                TC = sum(c_i Q_i)                   procurement cost
                SL = sum(r_i Q_i) / sum(r_i need_i)  the need met, each piece
                                                    weighted by its SKU's
                                                    revenue weight r_i
                SC = sum(h_i Q_i)                   storage cost
With enough allocation, stage 1 fills every need and nothing is left for the
weights to decide. When the allocation is short, stage 1 fixes how much each
layer gets and stage 3 decides who comes up short within the layer being cut:
per piece, SKU i scores w2 x r_i/r - w1 x c_i/c - w3 x h_i/h (r, c and h are
need-weighted averages), and the lowest scores give up that layer first. An
LP picks corners, so within that layer the lowest SKUs can lose all of it
before anyone else loses a piece; the layers keep that from reaching
anyone's safety stock or month of demand while the allocation allows.
(Filled as one block, the first dry run, 2026-09-29, ordered 0 for SKUs with
less stock than a month's forecast.)

Why stages and not one weighted sum: with every term at 1.0 at full fill, the
cost weights (0.45 + 0.20) outweigh service (0.35), so a single weighted sum
would order nothing, the mirror image of the old Q_i = ROP_i. The old model
hid that behind its hard Q_i >= ROP_i floor. Here the floor is the target,
kept as the first priority rather than a hard constraint, so a short
allocation gives a plan instead of INFEASIBLE.

Constants (from analytics.params):
  Z_SCORE = SERVICE_Z (1.28)
  W1, W2, W3 = LP_WEIGHTS (0.45, 0.35, 0.20)
"""
from __future__ import annotations

from dataclasses import dataclass

import pulp

from analytics.params import BUSINESS_DAYS_PER_WEEK, LP_WEIGHTS, SERVICE_Z, WEEKS_PER_MONTH

Z_SCORE = SERVICE_Z
W1, W2, W3 = LP_WEIGHTS["cost"], LP_WEIGHTS["service_level"], LP_WEIGHTS["storage"]

assert abs((W1 + W2 + W3) - 1.00) < 1e-9, "W1+W2+W3 must sum to 1.00 (Step 19 weighting)"


@dataclass
class SKUInput:
    """One SKU's inputs to the LP for a single planning cycle, in pieces."""
    sku_id: str
    principal: str            # 'unilever' | 'delmonte' — must match a key in supplier_ceilings
    demand: float             # F_i: this month's forecast
    target_stock: float       # T_i: see target_stock()
    stock_on_hand: float      # S_i: stock at the start of the month
    safety_stock: float       # SS_i, the part of T_i filled before the rest
    procurement_cost_per_unit: float  # c_i, ₱ per piece; also values stock for the cover rule
    storage_cost_per_unit: float      # h_i, ₱ per piece
    revenue_weight: float = 1.0       # r_i: priority when the allocation is short

    @property
    def need(self) -> float:
        return net_need(self.demand, self.target_stock, self.stock_on_hand)


def compute_safety_stock(sigma_d: float, z: float = Z_SCORE) -> float:
    """Step 17: SS_i = Z x sigma_di, Z=1.28 fixed (90% service level).

    sigma_d is the standard deviation of demand over the period the buffer
    covers — this function does not derive or rescale it, it only applies
    the formula, so it stays a pure, trivially-testable unit.
    """
    if sigma_d < 0:
        raise ValueError(f"sigma_d (a standard deviation) cannot be negative: {sigma_d}")
    return z * sigma_d


def weekly_demand(monthly_demand: float) -> float:
    """A month's demand as a weekly rate (the dashboard's weeks convention)."""
    return monthly_demand / WEEKS_PER_MONTH


def target_stock(
    monthly_demand: float,
    safety_stock: float,
    review_days: float,
    lead_days: float,
    floor_weeks: float | None = None,
) -> float:
    """T_i = demand over the review period + lead time (business days) +
    safety stock. With floor_weeks (the 'per-sku' cover rule), never less
    than that many weeks of sales."""
    if safety_stock < 0:
        raise ValueError(f"safety_stock cannot be negative: {safety_stock}")
    if review_days < 0 or lead_days < 0:
        raise ValueError(f"review_days and lead_days cannot be negative: {review_days}, {lead_days}")
    weekly = weekly_demand(monthly_demand)
    target = weekly * (review_days + lead_days) / BUSINESS_DAYS_PER_WEEK + safety_stock
    if floor_weeks is not None:
        target = max(target, floor_weeks * weekly)
    return target


def net_need(monthly_demand: float, target: float, stock_on_hand: float) -> float:
    """need_i = max(0, F_i + T_i - S_i): what the month's orders must bring
    in to cover its demand and end the month at the target."""
    return max(0.0, monthly_demand + target - stock_on_hand)


FILL_LAYERS = ("demand", "safety_stock", "rest_of_target")
HOLD_SLACK_REL = 1e-7   # solve_lp's retry only: below CBC's own 1e-6 feasibility tolerance; 1e-7 of ~208,000 pieces = 0.02 piece


def fill_layers(sku: SKUInput) -> tuple[float, float, float]:
    """need_i split into the FILL_LAYERS, filled in that order: this month's
    demand, then safety stock, then the rest of the target. Sums to need_i."""
    need = sku.need
    demand = min(need, max(0.0, sku.demand - sku.stock_on_hand))
    safety = min(need, max(0.0, sku.demand + sku.safety_stock - sku.stock_on_hand)) - demand
    return demand, safety, need - demand - safety


def build_lp_model(
    skus: list[SKUInput],
    warehouse_capacity: float,
    supplier_ceilings: dict[str, float],
    weights: tuple[float, float, float] = (W1, W2, W3),
    min_cover_weeks: float | None = None,
) -> pulp.LpProblem:
    """Builds (does not solve) the LP in the module docstring.
    min_cover_weeks turns on the aggregate cover rule (constraint 3).

    Raises ValueError if `skus` is empty, the weights don't sum to 1, or a
    principal in `skus` has no supplier ceiling (a silently-missing ceiling
    would leave that principal's SKUs unconstrained).

    The problem carries `.sku_orders` ({sku_id: Q_i as an expression}) and
    `.stages`, the (name, expression) pairs solve_lp() minimizes in turn.
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

    # One variable per SKU and layer, Q_i their sum. Named by position: PuLP
    # rewrites characters it can't use in a name, so two SKU ids could
    # otherwise end up as one variable.
    needs = {sku.sku_id: sku.need for sku in skus}
    layers: dict[str, list[pulp.LpVariable]] = {name: [] for name in FILL_LAYERS}
    variables: dict[str, pulp.LpAffineExpression] = {}
    for n, sku in enumerate(skus):
        parts = []
        for name, cap in zip(FILL_LAYERS, fill_layers(sku)):
            if cap > 0:
                part = pulp.LpVariable(f"Q_{n}_{name}", lowBound=0, upBound=cap, cat="Continuous")
                layers[name].append(part)
                parts.append(part)
        variables[sku.sku_id] = pulp.lpSum(parts)
    order = pulp.lpSum(variables.values())

    # Constraint 1 — warehouse capacity, stock on hand included
    problem += (order + sum(sku.stock_on_hand for sku in skus) <= warehouse_capacity, "warehouse_capacity")

    # Constraint 2 — supplier allocation, per principal
    for principal in sorted({sku.principal for sku in skus}):
        problem += (
            pulp.lpSum(variables[sku.sku_id] for sku in skus if sku.principal == principal)
            <= supplier_ceilings[principal],
            f"supplier_ceiling_{principal}",
        )

    stages: list[tuple[str, pulp.LpAffineExpression]] = [
        (f"fill_{name}", -pulp.lpSum(layers[name])) for name in FILL_LAYERS
    ]

    # Constraint 3 — the aggregate cover rule, soft
    if min_cover_weeks is not None:
        short = pulp.LpVariable("cover_short", lowBound=0)
        planned = pulp.lpSum(
            sku.procurement_cost_per_unit * (sku.stock_on_hand + variables[sku.sku_id] - sku.demand)
            for sku in skus
        )
        required = min_cover_weeks * sum(sku.procurement_cost_per_unit * weekly_demand(sku.demand) for sku in skus)
        problem += (planned + short >= required, "cover_rule")
        stages.append(("cover_short", pulp.lpSum([short])))

    # Stage 3 — the weights. Each term is relative to its value at full fill
    # (Q = need), so all three read 1.0 there and trade like for like.
    total_need = sum(needs.values())
    tc_ref = sum(sku.procurement_cost_per_unit * needs[sku.sku_id] for sku in skus)
    sc_ref = sum(sku.storage_cost_per_unit * needs[sku.sku_id] for sku in skus)
    sl_ref = sum(sku.revenue_weight * needs[sku.sku_id] for sku in skus)
    total_cost = pulp.lpSum(sku.procurement_cost_per_unit * variables[sku.sku_id] for sku in skus)
    storage_cost = pulp.lpSum(sku.storage_cost_per_unit * variables[sku.sku_id] for sku in skus)
    if sl_ref > 0:
        service_level = pulp.lpSum(sku.revenue_weight * variables[sku.sku_id] for sku in skus) / sl_ref
    else:  # no revenue weights at all: every piece counts the same
        service_level = order / total_need if total_need > 0 else pulp.LpAffineExpression()
    # A zero reference means every unit cost is 0, so the term is 0 everywhere
    # and is left at its raw value rather than divided by zero.
    weighted = (
        w1 * (total_cost / (tc_ref if tc_ref > 0 else 1.0))
        - w2 * service_level
        + w3 * (storage_cost / (sc_ref if sc_ref > 0 else 1.0))
    )
    # Scaled by the total need so a piece's coefficient is O(1): unscaled it
    # sits near 1e-7, CBC's own tolerance, where two SKUs can't be told
    # apart. A positive rescale doesn't move the optimum.
    stages.append(("weights", weighted * (total_need if total_need > 0 else 1.0)))

    problem.sku_orders = variables  # type: ignore[attr-defined]
    problem.stages = stages  # type: ignore[attr-defined]
    return problem


PACK_TOLERANCE = 1e-6   # pieces: a quantity within this of a whole pack counts as whole


def _packs(quantity: float, pack: float) -> tuple[float, float]:
    """(whole packs at or below, whole packs at or above) `quantity`, in pieces.
    A quantity within PACK_TOLERANCE of a whole pack is that pack, both ways."""
    packs = quantity / pack
    nearest = round(packs)
    if abs(packs - nearest) * pack <= PACK_TOLERANCE:
        return nearest * pack, nearest * pack
    below = float(int(packs))
    return below * pack, (below + 1.0) * pack


def constraint_slacks(
    skus: list[SKUInput], orders: dict[str, float], warehouse_capacity: float, supplier_ceilings: dict[str, float],
) -> dict[str, float]:
    """Room left under each hard constraint of build_lp_model, in pieces:
    'warehouse' and 'allocation:<principal>'. Zero means binding."""
    stock = sum(s.stock_on_hand for s in skus)
    slacks = {"warehouse": warehouse_capacity - stock - sum(orders[s.sku_id] for s in skus)}
    for principal in sorted({s.principal for s in skus}):
        slacks[f"allocation:{principal}"] = supplier_ceilings[principal] - sum(
            orders[s.sku_id] for s in skus if s.principal == principal)
    return slacks


def round_to_case_packs(
    skus: list[SKUInput],
    orders: dict[str, float],
    pack_sizes: dict[str, float | None],
    warehouse_capacity: float,
    supplier_ceilings: dict[str, float],
) -> tuple[dict[str, float], list[dict]]:
    """Round each order to whole case packs INSIDE the ceilings the LP solved
    under, not after them. Returns ({sku_id: rounded order}, one audit row per
    SKU).

    A SKU with no pack size, or a pack size of 1 or less, is unchanged, and so
    is an order of 0 or one already in whole packs. Every other order goes UP
    to the next whole pack, unless that would take the warehouse
    (sum(S_i + Q_i) <= W) or its principal's allocation (sum(Q_i) <= A_p) over
    its ceiling, and then that row goes DOWN to the whole pack below (possibly
    0). Rows are tried in descending revenue_weight (the LP's own priority),
    then sku_id, so the result does not depend on input order. need_i, the
    target and the safety stock are not touched: a rounded-up row can end above
    its need by less than one pack.

    The rounded total never exceeds a ceiling the unrounded one was inside of:
    every row starts at its pack below (which only lowers the totals), and a
    row is raised only while the room that leaves covers the raise."""
    rounded: dict[str, float] = {}
    audit: dict[str, dict] = {}
    movable: list[tuple[SKUInput, float, float, float]] = []   # sku, pack, below, above
    for s in skus:
        q = orders[s.sku_id]
        pack = pack_sizes.get(s.sku_id)
        row = {"sku_id": s.sku_id, "pack_size": pack, "before": q, "after": q, "action": "unchanged"}
        audit[s.sku_id] = row
        rounded[s.sku_id] = q
        if pack is None or pack <= 1:
            row["reason"] = "no pack size" if pack is None else "pack size 1"
            continue
        if q <= PACK_TOLERANCE:
            row["reason"] = "order is 0"
            continue
        below, above = _packs(q, pack)
        if above == below:
            rounded[s.sku_id] = row["after"] = below   # snaps solver noise onto the pack
            row["reason"] = "already whole packs"
            continue
        rounded[s.sku_id] = below
        movable.append((s, pack, below, above))

    stock = sum(s.stock_on_hand for s in skus)
    room_warehouse = warehouse_capacity - stock - sum(rounded.values())
    room_principal = {p: supplier_ceilings[p] - sum(rounded[s.sku_id] for s in skus if s.principal == p)
                      for p in {s.principal for s in skus}}
    for s, pack, below, above in sorted(movable, key=lambda m: (-m[0].revenue_weight, m[0].sku_id)):
        raise_by = above - below
        if raise_by <= room_warehouse + 1e-9 and raise_by <= room_principal[s.principal] + 1e-9:
            rounded[s.sku_id] = above
            room_warehouse -= raise_by
            room_principal[s.principal] -= raise_by
    for s, pack, below, above in movable:
        row = audit[s.sku_id]
        row["after"] = rounded[s.sku_id]
        row["action"] = "rounded_up" if rounded[s.sku_id] == above else "rounded_down_at_ceiling"
    return rounded, [audit[s.sku_id] for s in skus]


def solve_lp(model: pulp.LpProblem) -> dict[str, float] | None:
    """Step 20: solves the stages in order with CBC (PuLP's default
    solver), holding each at its optimum before the next.

    Returns {sku_id: Q_i} when every stage is Optimal. Returns None — NEVER
    raises — for Infeasible, Unbounded or Undefined, so the caller can
    surface a clear warning to the dashboard instead of the pipeline
    crashing. No Q_i is read off the model before that check.

    Sets model.stage_values ({stage name: its optimum}) for the caller's
    report; 'cover_short' is the aggregate cover rule's shortfall in pesos.
    """
    stages = getattr(model, "stages", None) or [("objective", model.objective)]
    model.stage_values = {}  # type: ignore[attr-defined]
    held: list[tuple[str, pulp.LpAffineExpression, float]] = []
    for n, (name, expression) in enumerate(stages):
        model.setObjective(expression)
        model.solve(pulp.PULP_CBC_CMD(msg=False))
        if pulp.LpStatus[model.status] != "Optimal" and held:
            # Q = 0 is always feasible, so an Infeasible stage after Optimal
            # ones is the holds below being tighter than CBC's own round-off
            # (2026-03 cycle, 2026-10-19: three Optimal fill stages, then the
            # cover stage Infeasible, no plan written). Retry once with every
            # hold loosened to HOLD_SLACK_REL; a run that solves first time is
            # untouched.
            for held_name, held_expr, held_value in held:
                model.constraints[f"hold_{held_name}"] = (
                    held_expr <= held_value + HOLD_SLACK_REL * max(1.0, abs(held_value)) + 1e-7)
            model.solve(pulp.PULP_CBC_CMD(msg=False))
        if pulp.LpStatus[model.status] != "Optimal":
            return None
        value = float(pulp.value(expression) or 0.0)
        model.stage_values[name] = value
        if n < len(stages) - 1:
            # Hold this stage at its optimum. The slack only absorbs float
            # round-off: the later stages lean on it (stage 3's costs pull the
            # order down), so a looser one shows up as orders just under need.
            model += (expression <= value + 1e-9 * max(1.0, abs(value)) + 1e-7, f"hold_{name}")
            held.append((name, expression, value))

    sku_orders: dict[str, pulp.LpAffineExpression] = getattr(model, "sku_orders", {})
    return {sku_id: float(pulp.value(expr) or 0.0) for sku_id, expr in sku_orders.items()}
