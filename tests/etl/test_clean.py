"""
tests/etl/test_clean.py — Tests for analytics.etl.clean.

  test_outliers_are_flagged_not_dropped
  test_bo_rate_null_when_units_received_is_zero
  test_bo_rate_null_when_bo_units_missing
  test_branch_code_leading_zero_preserved
"""
import pandas as pd

from analytics.etl.clean import clean_pipeline, compute_bo_rate, flag_iqr_outliers


def test_outliers_are_flagged_not_dropped():
    df = pd.DataFrame({"net_amount": [100.0, 105.0, 98.0, 5000.0]})
    out = flag_iqr_outliers(df, "net_amount")
    assert len(out) == 4  # nothing dropped
    assert out["_outlier_flag"].tolist() == [False, False, False, True]


def test_bo_rate_null_when_units_received_is_zero():
    df = pd.DataFrame({"bo_units": [2], "units_received": [0]})
    out = compute_bo_rate(df)
    assert pd.isna(out["bo_rate"].iloc[0])  # not fabricated as 0%


def test_bo_rate_null_when_bo_units_missing():
    df = pd.DataFrame({"bo_units": [None], "units_received": [50]})
    out = compute_bo_rate(df)
    assert pd.isna(out["bo_rate"].iloc[0])


def test_branch_code_leading_zero_preserved():
    df = pd.DataFrame({
        "invoice_num": ["A"], "net_amount": [100.0], "_principal": ["delmonte"],
        "_period": ["2024-01"], "branch_code": [" 0032 "],
    })
    out, result = clean_pipeline(df)
    assert out["branch_code"].iloc[0] == "0032"
    assert result.ok
