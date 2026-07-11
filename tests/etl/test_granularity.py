"""
tests/etl/test_granularity.py — Tests for analytics.etl.granularity.

  test_delmonte_monthly_total_reconciles_after_distribution
  test_delmonte_output_has_no_date_gaps
  test_unilever_dispatch_requires_sku_daily_df
  test_unknown_principal_raises
"""
import pandas as pd
import pytest

from analytics.etl.granularity import resolve_granularity


def test_delmonte_monthly_total_reconciles_after_distribution():
    monthly = pd.DataFrame({
        "_period": ["2024-02"], "category": ["ACE"], "net_amount": [30000.0],
    })
    daily, result = resolve_granularity(monthly, None, "delmonte")
    assert abs(daily["net_amount"].sum() - 30000.0) < 0.01
    assert result.total_mismatch is None


def test_delmonte_output_has_no_date_gaps():
    monthly = pd.DataFrame({
        "_period": ["2024-02"], "category": ["ACE"], "net_amount": [30000.0],
    })
    _, result = resolve_granularity(monthly, None, "delmonte")
    assert result.date_gaps == []
    assert result.ok


def test_unilever_dispatch_requires_sku_daily_df():
    monthly = pd.DataFrame({"_period": ["2024-02"], "net_amount": [1.0]})
    with pytest.raises(ValueError):
        resolve_granularity(monthly, None, "unilever")


def test_unknown_principal_raises():
    monthly = pd.DataFrame({"_period": ["2024-02"], "net_amount": [1.0]})
    with pytest.raises(ValueError):
        resolve_granularity(monthly, None, "magnolia")
