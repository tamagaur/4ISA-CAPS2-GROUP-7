"""
tests/etl/test_granularity.py — Tests for analytics.etl.granularity.

  test_delmonte_monthly_total_reconciles_after_distribution
  test_delmonte_output_has_no_date_gaps
  test_unilever_dispatch_requires_sku_daily_df
  test_unknown_principal_raises
"""
import pandas as pd
import pytest

from analytics.etl.granularity import resolve_granularity, resolve_unilever_sku_grain


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


def test_unilever_sku_grain_requires_real_transform_output_columns():
    """DEC-10: this used to require {"sku_id", "date", "quantity_sold"} -
    a mismatch against Transform's real unilever_sku output (sku_code,
    calendar_month), never caught because no test constructed real input.
    A realistically-shaped frame must now pass through validated."""
    df = pd.DataFrame({
        "sku_code": ["64997199", "64997199", "64997199"],
        "calendar_month": ["2023-01", "2023-02", "2023-04"],   # gap: 2023-03 missing
        "quantity_sold": [100.0, 120.0, 90.0],
    })
    out, result = resolve_unilever_sku_grain(df)
    assert len(out) == 3
    assert result.date_gaps == ["2023-03"]
    assert not result.ok


def test_unilever_sku_grain_no_gaps_when_months_are_contiguous():
    df = pd.DataFrame({
        "sku_code": ["64997199", "64997199"],
        "calendar_month": ["2023-01", "2023-02"],
        "quantity_sold": [100.0, 120.0],
    })
    _, result = resolve_unilever_sku_grain(df)
    assert result.ok
    assert result.date_gaps == []


def test_unilever_sku_grain_missing_columns_raises():
    df = pd.DataFrame({"sku_id": ["SKU-1"], "date": ["2023-01-01"], "quantity_sold": [1.0]})
    with pytest.raises(KeyError):
        resolve_unilever_sku_grain(df)
