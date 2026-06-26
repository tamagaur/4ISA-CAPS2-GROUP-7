"""
analytics.optimization.lp — Safety stock, ROP, and LP optimization (PuLP/CBC).

Phase 5 (CLAUDE.md Steps 17–21):

  Step 17 — Safety Stock:
    SS_i = Z × σ_di   where Z = 1.28 (90% service level, hardcoded constant)
    σ_di from reconstructed daily demand series (granularity.py output).

  Step 18 — Reorder Point:
    ROP_i = Ŷ_(t+1,i) + SS_i
    Ŷ_(t+1,i) = one-month-ahead SARIMA forecast (sarima.py output).

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

TODO: Implement compute_safety_stock(sigma_d: float) -> float.
      Implement compute_rop(forecast: float, safety_stock: float) -> float.
      Implement build_lp_model(skus: list, ...) -> pulp.LpProblem.
      Implement solve_lp(model: pulp.LpProblem) -> dict[str, float] | None.
      Return None (not raise) when infeasible; caller surfaces to dashboard.
"""
