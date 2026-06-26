"""
tests/optimization/test_lp.py — Tests for analytics.optimization.lp.

Phase 5 (CLAUDE.md Steps 17–21):
  test_safety_stock_formula       — SS = Z × σ_d with Z=1.28 exactly
  test_rop_formula                — ROP = forecast + SS
  test_lp_feasible_result         — Q_i values within allocation ceiling
  test_lp_infeasible_returns_none — infeasible LP returns None, does not raise
  test_weights_sum_to_one         — w1+w2+w3 == 1.00

TODO: Implement after SARIMA forecasting is complete (Phase 4).
"""

import pytest


def test_placeholder():
    """Placeholder — remove when real tests are implemented."""
    assert True
