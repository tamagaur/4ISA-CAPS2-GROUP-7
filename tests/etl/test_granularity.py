"""
tests/etl/test_granularity.py — Tests for analytics.etl.granularity.

  test_delmonte_monthly_total_reconciles_after_distribution
  test_delmonte_output_has_no_date_gaps
  test_unilever_dispatch_requires_sku_daily_df
  test_unknown_principal_raises
  test_delmonte_category_grain_rejects_wrong_doc_type
  test_delmonte_category_grain_accepts_matching_doc_type
  test_unilever_sku_grain_requires_explicit_quantity_col
  test_unilever_sku_grain_rejects_unconfirmed_quantity_col
  test_unilever_sku_grain_detects_month_gap
  test_unilever_sku_grain_no_gap_on_continuous_months
  test_resolve_granularity_requires_unilever_quantity_col
"""
import pandas as pd
import pytest

from analytics.etl.granularity import (
    resolve_delmonte_category_grain,
    resolve_granularity,
    resolve_unilever_sku_grain,
)


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


def test_delmonte_category_grain_rejects_wrong_doc_type():
    """DEC-03/§5.1: Del Monte category-grain must come from sell_out, not
    invoice-grain sales_register — this must be a loud error, not a
    plausible-looking fabricated result."""
    monthly = pd.DataFrame({
        "_period": ["2024-02"], "category": ["ACE"], "net_amount": [30000.0],
        "_doc_type": ["sales_register"],
    })
    with pytest.raises(ValueError):
        resolve_delmonte_category_grain(monthly)


def test_delmonte_category_grain_accepts_matching_doc_type():
    monthly = pd.DataFrame({
        "_period": ["2024-02"], "category": ["ACE"], "net_amount": [30000.0],
        "_doc_type": ["sell_out"],
    })
    daily, result = resolve_delmonte_category_grain(monthly)
    assert result.ok
    assert abs(daily["net_amount"].sum() - 30000.0) < 0.01


def test_unilever_sku_grain_requires_explicit_quantity_col():
    """quantity_col has no default — which field is canonical
    quantity_sold is unconfirmed against real data (see the module-level
    TODO), so the function refuses to guess rather than defaulting."""
    df = pd.DataFrame({
        "sku_code": ["123"], "calendar_month": ["2025-01"], "sale_quantity_cases": [10.0],
    })
    with pytest.raises(TypeError):
        resolve_unilever_sku_grain(df)  # noqa - missing required positional arg


def test_unilever_sku_grain_rejects_unconfirmed_quantity_col():
    df = pd.DataFrame({
        "sku_code": ["123"], "calendar_month": ["2025-01"], "gsv": [100.0],
    })
    with pytest.raises(ValueError):
        resolve_unilever_sku_grain(df, quantity_col="gsv")  # gsv explicitly ruled out


def test_unilever_sku_grain_detects_month_gap():
    df = pd.DataFrame({
        "sku_code": ["123", "123"],
        "calendar_month": ["2025-01", "2025-03"],  # February missing
        "sale_quantity_cases": [10.0, 12.0],
    })
    _, result = resolve_unilever_sku_grain(df, quantity_col="sale_quantity_cases")
    assert not result.ok
    assert "2025-02" in result.date_gaps


def test_unilever_sku_grain_no_gap_on_continuous_months():
    df = pd.DataFrame({
        "sku_code": ["123", "123", "123"],
        "calendar_month": ["2025-01", "2025-02", "2025-03"],
        "sale_quantity_cases": [10.0, 11.0, 12.0],
    })
    out, result = resolve_unilever_sku_grain(df, quantity_col="sale_quantity_cases")
    assert result.ok
    assert result.date_gaps == []
    assert len(out) == 3  # passthrough, never alters the data


def test_resolve_granularity_requires_unilever_quantity_col():
    monthly = pd.DataFrame({"_period": ["2024-02"], "net_amount": [1.0]})
    sku_daily = pd.DataFrame({
        "sku_code": ["123"], "calendar_month": ["2025-01"], "sale_quantity_cases": [10.0],
    })
    with pytest.raises(ValueError):
        resolve_granularity(monthly, sku_daily, "unilever")
