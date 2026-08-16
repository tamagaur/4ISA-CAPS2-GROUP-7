"""
tests/etl/test_transform.py — Tests for analytics.etl.transform.

  test_vocab_a_and_b_map_to_same_canonical_schema — the core Transform problem
  test_unmapped_raw_header_is_reported_not_dropped
  test_source_of_truth_filter_drops_cross_check_role
  test_dedup_collapses_true_duplicate
  test_dedup_flags_conflicting_amount_without_choosing
  test_missing_natural_key_column_raises
  test_backfill_provenance_fields_copies_from_underscore_columns
  test_backfill_provenance_fields_does_not_overwrite_real_column
  test_filter_source_of_truth_drops_cross_check_doc_type
  test_inventory_natural_key_no_longer_collapses_cross_region_rows
  test_sell_out_natural_key_no_longer_collapses_cross_region_rows
  test_purchase_natural_key_no_longer_collapses_cross_region_rows
  test_coerce_numeric_columns_handles_commas_and_decimals
  test_coerce_numeric_columns_flags_unparseable_without_dropping_row
  test_normalize_quantities_trusts_reported_pieces_over_cases_times_pack_size
  test_normalize_quantities_agreeing_row_is_not_flagged
  test_normalize_quantities_missing_pieces_is_null_not_derived_from_cases
  test_normalize_quantities_derives_delmonte_pieces_from_pcs_and_leaves_cases_untouched
  test_normalize_quantities_unrelated_doc_type_is_a_passthrough
  test_reformat_calendar_month_converts_mm_dot_yyyy_to_yyyy_mm
  test_reformat_calendar_month_unparsable_value_is_null_not_guessed
  test_transform_fact_reformats_calendar_month_for_unilever_sku
  test_inventory_snapshot_date_is_first_of_period_and_period_column_kept
  test_inventory_snapshot_date_null_when_period_unknown
"""
import pandas as pd
import pytest

from analytics.etl.transform import (
    apply_column_map,
    backfill_provenance_fields,
    coerce_numeric_columns,
    dedup_facts,
    filter_source_of_truth,
    load_source_of_truth,
    normalize_quantities,
    reformat_calendar_month,
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


def test_backfill_provenance_fields_copies_from_underscore_columns():
    df = pd.DataFrame({"_principal": ["delmonte"], "_region": ["ilocos"], "invoice_num": ["INV-1"]})
    out = backfill_provenance_fields(df)
    assert out["principal"].iloc[0] == "delmonte"
    assert out["region"].iloc[0] == "ilocos"


def test_backfill_provenance_fields_does_not_overwrite_real_column():
    """A real mapped "region" column (e.g. from sales_register's "Area"
    header) must win over the provenance tag, never be clobbered."""
    df = pd.DataFrame({"_principal": ["delmonte"], "_region": ["ilocos"], "region": ["pangasinan"]})
    out = backfill_provenance_fields(df)
    assert out["region"].iloc[0] == "pangasinan"


def test_backfill_provenance_fields_fills_per_row_nulls_not_just_missing_column():
    """Real Sales_Fact data: region is a real mapped column but blank on
    ~38% of rows because the raw "Town Display"/"AREA" source cell itself
    is blank. _region provenance is 0% null for the same rows and should
    recover it row-by-row, without touching rows that already have a real
    region."""
    df = pd.DataFrame({
        "_region": ["ilocos", "pangasinan"],
        "region": [None, "pangasinan"],
    })
    out = backfill_provenance_fields(df)
    assert out["region"].iloc[0] == "ilocos"
    assert out["region"].iloc[1] == "pangasinan"


def test_backfill_provenance_fields_never_copies_placeholder_sentinels():
    """_region can literally be the string "unknown" (extract/_shared.py
    infer_sheet_region's own fallback when neither sheet name nor file
    path matches a region pattern) and _principal can be "ambiguous" -
    these mean "Extract couldn't tell", not a real value, so they must
    never be copied into the bare column (anti-fabrication)."""
    df = pd.DataFrame({
        "_principal": ["ambiguous"],
        "_region": ["unknown"],
        "principal": [None],
        "region": [None],
    })
    out = backfill_provenance_fields(df)
    assert pd.isna(out["principal"].iloc[0])
    assert pd.isna(out["region"].iloc[0])


def test_filter_source_of_truth_drops_cross_check_doc_type():
    """sales/delmonte's cross_check_doc_types: [daily_sales_report] must
    be dropped even though daily_sales_report shares _sheet_role="data"
    with sales_register (role alone can't distinguish them - DEC-07)."""
    df = pd.DataFrame({
        "invoice_num": ["INV-1", "INV-2"],
        "_sheet_role": ["data", "data"],
        "_doc_type": ["sales_register", "daily_sales_report"],
    })
    out = filter_source_of_truth(df, fact="sales", principal="delmonte")
    assert len(out) == 1
    assert out["_doc_type"].iloc[0] == "sales_register"


def test_inventory_natural_key_no_longer_collapses_cross_region_rows():
    """Fixed 2026-08: inventory's natural_key now includes region -
    two real rows (same SKU/month, different region) must both survive
    dedup instead of one being silently discarded."""
    rule = load_source_of_truth("inventory", "both")
    df = pd.DataFrame({
        "sku_code": ["9DMR56831", "9DMR56831"],
        "snapshot_date": ["2025-08", "2025-08"],
        "region": ["pangasinan", "ilocos"],
        "quantity_on_hand": [100.0, 50.0],
    })
    out, report = dedup_facts(df, rule.natural_key)
    assert len(out) == 2
    assert report.duplicate_groups == 0


def test_sell_out_natural_key_no_longer_collapses_cross_region_rows():
    rule = load_source_of_truth("sell_out", "delmonte")
    df = pd.DataFrame({
        "category_path": ["/ACE/BASE", "/ACE/BASE"],
        "_period": ["2025-08", "2025-08"],
        "region": ["pangasinan", "ilocos"],
        "net_amount": [1000.0, 500.0],
    })
    out, report = dedup_facts(df, rule.natural_key)
    assert len(out) == 2
    assert report.duplicate_groups == 0


def test_purchase_natural_key_no_longer_collapses_cross_region_rows():
    rule = load_source_of_truth("purchase", "both")
    df = pd.DataFrame({
        "invoice_num": ["BILL/2025/001", "BILL/2025/001"],
        "principal": ["delmonte", "delmonte"],
        "region": ["pangasinan", "ilocos"],
        "untaxed_amount": [1000.0, 500.0],
    })
    out, report = dedup_facts(df, rule.natural_key)
    assert len(out) == 2
    assert report.duplicate_groups == 0


def test_coerce_numeric_columns_handles_commas_and_decimals():
    df = pd.DataFrame({
        "sale_quantity_pieces": ["24,190", "8,465"],
        "gsv": ["6,711.21", "-422.58"],
        "untouched": ["x", "y"],
    })
    out, unparseable = coerce_numeric_columns(df, ["sale_quantity_pieces", "gsv"])
    assert float(out["sale_quantity_pieces"].iloc[0]) == 24190.0
    assert float(out["gsv"].iloc[1]) == -422.58
    assert unparseable == []
    assert out["untouched"].iloc[0] == "x"  # column not in the coercion list, left alone


def test_coerce_numeric_columns_flags_unparseable_without_dropping_row():
    df = pd.DataFrame({"gsv": ["6,711.21", "not a number"]})
    out, unparseable = coerce_numeric_columns(df, ["gsv"])
    assert len(out) == 2  # row kept, never dropped
    assert pd.isna(out["gsv"].iloc[1])  # unparseable cell -> null, not zero, not guessed
    assert unparseable == ["gsv"]


def test_normalize_quantities_trusts_reported_pieces_over_cases_times_pack_size():
    """DEC-11: reported pieces wins even when cases x pack_size disagrees -
    cases x pack_size is only ~84% consistent with reported pieces on real
    Unilever data, so it must never override the reported figure."""
    df = pd.DataFrame({
        "sale_quantity_pieces": ["24,190"],   # reported value - trusted
        "sale_quantity_cases": ["20.04"],
        "pack_size": ["360"],                  # 20.04 x 360 = 7,214.4, nowhere close to 24,190
    })
    out, report = normalize_quantities(df, doc_type="unilever_sku")
    assert out["quantity_sold"].iloc[0] == 24190.0
    assert report.checked_rows == 1
    assert len(report.mismatched) == 1
    assert report.mismatched[0]["reported_pieces"] == 24190.0


def test_normalize_quantities_agreeing_row_is_not_flagged():
    df = pd.DataFrame({
        "sale_quantity_pieces": ["7,214.4"],
        "sale_quantity_cases": ["20.04"],
        "pack_size": ["360"],
    })
    out, report = normalize_quantities(df, doc_type="unilever_sku")
    assert out["quantity_sold"].iloc[0] == 7214.4
    assert report.checked_rows == 1
    assert report.mismatched == []


def test_normalize_quantities_missing_pieces_is_null_not_derived_from_cases():
    """Anti-fabrication: no reported pieces value means quantity_sold is
    null, never silently backfilled from cases x pack_size."""
    df = pd.DataFrame({
        "sale_quantity_pieces": [None],
        "sale_quantity_cases": ["20.04"],
        "pack_size": ["360"],
    })
    out, report = normalize_quantities(df, doc_type="unilever_sku")
    assert pd.isna(out["quantity_sold"].iloc[0])
    assert report.checked_rows == 0
    assert report.mismatched == []


def test_normalize_quantities_derives_delmonte_pieces_from_pcs_and_leaves_cases_untouched():
    df = pd.DataFrame({
        "pieces": ["1,200"],
        "cases": ["50"],
        "packages": ["10"],
    })
    out, report = normalize_quantities(df, doc_type="inventory_sign_off")
    assert out["quantity_pieces"].iloc[0] == 1200.0
    assert out["cases"].iloc[0] == "50"       # not converted - no Del Monte pack_size exists
    assert out["packages"].iloc[0] == "10"    # not converted
    assert report is None


def test_normalize_quantities_unrelated_doc_type_is_a_passthrough():
    df = pd.DataFrame({"net_amount": [100.0]})
    out, report = normalize_quantities(df, doc_type="sales_register")
    assert out is df
    assert report is None


def test_reformat_calendar_month_converts_mm_dot_yyyy_to_yyyy_mm():
    df = pd.DataFrame({"calendar_month": ["01.2023", "10.2025", "12.2026"]})
    out, report = reformat_calendar_month(df)
    assert list(out["calendar_month"]) == ["2023-01", "2025-10", "2026-12"]
    assert report.reformatted == 3
    assert report.unparsable == 0


def test_reformat_calendar_month_unparsable_value_is_null_not_guessed():
    df = pd.DataFrame({"calendar_month": ["01.2023", "not a date", None]})
    out, report = reformat_calendar_month(df)
    assert out["calendar_month"].iloc[0] == "2023-01"
    assert pd.isna(out["calendar_month"].iloc[1])
    assert pd.isna(out["calendar_month"].iloc[2])
    assert report.reformatted == 1
    assert report.unparsable == 1   # the None cell is not counted as unparsable, just blank


def test_transform_fact_reformats_calendar_month_for_unilever_sku():
    df = pd.DataFrame({
        "Calendar\r\n  Month": ["01.2023"],
        "Product": ["64997199"],
        "Sale Quantity in\r\n  Aggr.PC": ["1,000"],
        "_sheet_role": ["data"],
        "_principal": ["unilever"],
    })
    out, report = transform_fact(df, fact="sales_unilever_sku_demand", principal="unilever")
    assert out["calendar_month"].iloc[0] == "2023-01"
    assert report["date_reformat"].reformatted == 1


def test_inventory_snapshot_date_is_first_of_period_and_period_column_kept():
    # Uses the already-canonical "Quantity" header plus a raw
    # "sku_description_raw"-named column directly (like
    # test_split_sku_description_separates_code_and_name does) rather than
    # inventory_sign_off's real "__col1__" placeholder header, which hits
    # an unrelated pre-existing bug: apply_column_map() skips ANY column
    # starting with "_", including the "__col0__"/"__col1__" placeholders
    # the real column map relies on - a separate issue, out of scope here.
    df = pd.DataFrame({
        "sku_description_raw": ["9DMR56831 DM QUICK N EASY MECHADO SAUCE (Royce)"],
        "Quantity": [100],
        "_period": ["2023-07"],
        "_sheet_role": ["data"],
        "_principal": ["delmonte"],
        "_region": ["ilocos"],  # inventory's natural key requires region - see DEC-04 fix
    })
    out, report = transform_fact(df, fact="inventory", principal="delmonte")
    assert str(out["snapshot_date"].iloc[0]) == "2023-07-01"
    assert out["_period"].iloc[0] == "2023-07"


def test_inventory_snapshot_date_null_when_period_unknown():
    df = pd.DataFrame({
        "sku_description_raw": ["9DMR56831 DM QUICK N EASY MECHADO SAUCE (Royce)"],
        "Quantity": [100],
        "_period": ["unknown"],
        "_sheet_role": ["data"],
        "_principal": ["delmonte"],
        "_region": ["ilocos"],  # inventory's natural key requires region - see DEC-04 fix
    })
    out, report = transform_fact(df, fact="inventory", principal="delmonte")
    assert pd.isna(out["snapshot_date"].iloc[0])   # never fabricated from "unknown"
