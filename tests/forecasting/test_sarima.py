"""
tests/forecasting/test_sarima.py — Tests for analytics.forecasting.sarima.

Phase 4 (CLAUDE.md Steps 12–16):
  test_temporal_split_no_leakage  — holdout set contains no training-period dates
  test_mape_gate_flag             — SKUs with MAPE ≥ 20% are flagged, not dropped
  test_forecast_within_range      — one-step forecast is plausible vs. training range
  test_parameter_log_not_empty    — AIC/BIC grid search produces non-empty param log

TODO: Implement after ABC classification is complete (Phase 3C).
"""

import pytest


def test_placeholder():
    """Placeholder — remove when real tests are implemented."""
    assert True
