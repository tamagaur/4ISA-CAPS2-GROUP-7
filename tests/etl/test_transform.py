"""
tests/etl/test_transform.py — Tests for analytics.etl.transform.

  test_vocab_a_and_b_map_to_same_canonical_schema — the core Transform problem
  test_unmapped_raw_header_is_reported_not_dropped
  test_source_of_truth_filter_drops_cross_check_role
  test_dedup_collapses_true_duplicate
  test_dedup_flags_conflicting_amount_without_choosing
  test_missing_natural_key_column_raises
"""
import pandas as pd
import pytest

from analytics.etl.transform import (
    apply_column_map,
    dedup_facts,
    filter_source_of_truth,
)


def test_vocab_a_and_b_map_to_same_canonical_schema():
    df_a = pd.DataFrame({"Invoice Date": ["2024-01-05"], "REFNBR": ["INV-1"], "Net Amount": [100.0]})
    df_b = pd.DataFrame({"Invoice Date": ["2025-03-10"], "REFERENCE #": ["INV-2"], "AMOUNT": [200.0]})

    mapped_a, _ = apply_column_map(df_a, "sales_register")
    mapped_b, _ = apply_column_map(df_b, "sales_register")

    assert set(mapped_a.columns) == {"invoice_date", "invoice_num", "net_amount"}
    assert set(mapped_b.columns) == {"invoice_date", "invoice_num", "net_amount"}


def test_unmapped_raw_header_is_reported_not_dropped():
    df = pd.DataFrame({"REFNBR": ["INV-1"], "Some New Column Nobody Confirmed Yet": ["x"]})
    mapped, report = apply_column_map(df, "sales_register")

    assert "Some New Column Nobody Confirmed Yet" in mapped.columns  # not dropped
    assert "Some New Column Nobody Confirmed Yet" in report.unmapped_raw


def test_source_of_truth_filter_drops_cross_check_role():
    df = pd.DataFrame({
        "invoice_num": ["INV-1", "INV-1"],
        "_sheet_role": ["data", "scratch"],
    })
    out = filter_source_of_truth(df, fact="sales", principal="delmonte")
    assert len(out) == 1
    assert out["_sheet_role"].iloc[0] == "data"


def test_dedup_collapses_true_duplicate():
    df = pd.DataFrame({"invoice_num": ["INV-1", "INV-1"], "net_amount": [100.0, 100.0]})
    out, report = dedup_facts(df, ["invoice_num"], amount_col="net_amount")
    assert len(out) == 1
    assert report.conflicting_groups == []


def test_dedup_flags_conflicting_amount_without_choosing():
    df = pd.DataFrame({"invoice_num": ["INV-1", "INV-1"], "net_amount": [100.0, 150.0]})
    out, report = dedup_facts(df, ["invoice_num"], amount_col="net_amount")
    assert len(out) == 2  # both kept, not silently resolved
    assert len(report.conflicting_groups) == 1


def test_missing_natural_key_column_raises():
    df = pd.DataFrame({"net_amount": [100.0]})
    with pytest.raises(KeyError):
        dedup_facts(df, ["invoice_num"])
