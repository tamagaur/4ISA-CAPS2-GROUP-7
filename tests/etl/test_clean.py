"""
tests/etl/test_clean.py — Tests for analytics.etl.clean.

  test_outliers_are_flagged_not_dropped
  test_bo_rate_null_when_units_received_is_zero
  test_bo_rate_null_when_bo_units_missing
  test_branch_code_leading_zero_preserved
  test_flag_quantity_issues_detects_zero_negative_and_outlier
  test_flag_quantity_issues_never_mutates_or_drops_rows
  test_flag_quantity_issues_missing_column_returns_empty_report
"""
import pandas as pd

from analytics.etl.clean import clean_pipeline, compute_bo_rate, flag_iqr_outliers, flag_quantity_issues


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


def test_flag_quantity_issues_detects_zero_negative_and_outlier():
    df = pd.DataFrame({
        "_src_file": ["f1", "f1", "f1", "f1"],
        "_src_sheet": ["s1", "s1", "s1", "s1"],
        "quantity_sold": [100.0, 0.0, -50.0, 5000.0],
    })
    report = flag_quantity_issues(df, "quantity_sold")
    assert report.total_rows == 4
    assert report.zero_count == 1
    assert report.negative_count == 1
    assert report.outlier_count == 1
    assert report.zero_rows[0]["quantity_sold"] == 0.0
    assert report.negative_rows[0]["quantity_sold"] == -50.0
    assert report.outlier_rows[0]["quantity_sold"] == 5000.0
    # identifying context is carried through for a human to trace back
    assert report.zero_rows[0]["_src_file"] == "f1"


def test_flag_quantity_issues_never_mutates_or_drops_rows():
    df = pd.DataFrame({"quantity_sold": [100.0, 0.0, -50.0]})
    original = df.copy()
    report = flag_quantity_issues(df, "quantity_sold")
    pd.testing.assert_frame_equal(df, original)  # caller's df untouched
    assert report.total_rows == len(df)  # nothing dropped from the report either


def test_flag_quantity_issues_missing_column_returns_empty_report():
    df = pd.DataFrame({"other_col": [1, 2, 3]})
    report = flag_quantity_issues(df, "quantity_sold")
    assert report.total_rows == 3
    assert report.zero_count == 0
    assert report.negative_count == 0
    assert report.outlier_count == 0
    assert report.zero_rows == []
