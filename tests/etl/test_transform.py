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
    load_source_of_truth,
    split_sku_description,
    transform_fact,
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


def test_transform_fact_derives_doc_type_from_rule_end_to_end():
    """delmonte sales: sot filter (drops scratch) -> column map (vocab B)
    -> discount alias -> dedup, all driven by fact/principal alone."""
    df = pd.DataFrame({
        "REFERENCE #": ["INV-1", "INV-2", "INV-3"],
        "AMOUNT": [100.0, 200.0, 999.0],
        "DISCOUNT AMNT.": [5.0, 0.0, 0.0],
        "Discount Rate": ["LESS 2%", "Public Pricelist", "Public Pricelist"],
        "_sheet_role": ["data", "data", "scratch"],
        "_principal": ["delmonte", "delmonte", "delmonte"],
        "Area": ["PANGASINAN", "ILOCOS", "ILOCOS"],
    })
    out, report = transform_fact(df, fact="sales", principal="delmonte")

    assert report["doc_type"] == "sales_register"
    assert len(out) == 2  # scratch-role row dropped by source-of-truth filter
    assert set(out["invoice_num"]) == {"INV-1", "INV-2"}
    assert out.loc[out["invoice_num"] == "INV-1", "discount_rate_label"].iloc[0] == "LESS_2PCT"


def test_transform_fact_raises_on_unconfirmed_natural_key():
    """sales/unilever has natural_key: null in source_of_truth.yaml on
    purpose (no invoice/reference column exists in the real source) -
    transform_fact must refuse rather than guess a key."""
    df = pd.DataFrame({"_sheet_role": ["raw_data"], "_principal": ["unilever"]})
    with pytest.raises(ValueError):
        transform_fact(df, fact="sales", principal="unilever")


def test_load_source_of_truth_exposes_none_natural_key():
    rule = load_source_of_truth("sales", "unilever")
    assert rule.natural_key is None
    assert rule.doc_type == "ssis_summary"


def test_split_sku_description_separates_code_and_name():
    df = pd.DataFrame({
        "sku_description_raw": [
            "9DMR56831 DM QUICK N EASY MECHADO SAUCE (Royce)",
            "58740",          # bare numeric ID - must NOT be guessed at
            None,
        ]
    })
    out, report = split_sku_description(df)
    assert out["sku_code"].iloc[0] == "9DMR56831"
    assert out["product_name"].iloc[0] == "DM QUICK N EASY MECHADO SAUCE (Royce)"
    assert pd.isna(out["sku_code"].iloc[1])   # unmatched, not guessed
    assert pd.isna(out["sku_code"].iloc[2])
    assert report.matched == 1
    assert report.unmatched == 2
