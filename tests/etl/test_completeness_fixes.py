"""tests/etl/test_completeness_fixes.py - the 2026-09-21 completeness-audit fixes and the Unilever demand loader fix.

Each test reproduces, on a few rows, the real defect it guards:
  L1  Unilever demand: net_amount_inc_tax reaches Unilever_SKU_Demand_Fact.net_amount
  F2  purchase: a September row reusing an August bill number is a different purchase, not a duplicate
  F3  Del Monte inventory: sheet "ILO 090223" is Ilocos; null == null on the amount is not agreement
  F4  sales: ONE PAGER invoices found on no daily sheet are kept
  F5  sales: _period comes from invoice_date, not from the workbook the row was read from
No DB.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd

from analytics.etl.extract._shared import infer_sheet_region
from analytics.etl.transform import (
    dedup_facts,
    load_source_of_truth,
    natural_key_series,
    period_from_invoice_date,
    transform_fact,
)
from scripts.run_canonical_load import (
    FACT_COLUMN_RENAMES,
    _clean_text,
    _pack_size_text,
    _rename_to_table_columns,
)


# --- L1 -------------------------------------------------------------------------------------------------------

def test_unilever_demand_net_amount_inc_tax_lands_in_net_amount():
    df = pd.DataFrame({"sku_code": ["20071069"], "calendar_month": ["2025-05"], "gsv": [-748.61], "net_amount_inc_tax": [-821.68]})
    out = _rename_to_table_columns(df, "unilever_sku_demand_fact")
    assert "net_amount_inc_tax" not in out.columns
    assert out["net_amount"].iloc[0] == -821.68
    assert out["gsv"].iloc[0] == -748.61  # a different measure, left alone


def test_rename_never_overwrites_a_column_the_frame_already_has():
    df = pd.DataFrame({"net_amount": [1.0], "net_amount_inc_tax": [2.0]})
    out = _rename_to_table_columns(df, "unilever_sku_demand_fact")
    assert out["net_amount"].iloc[0] == 1.0


def test_rename_is_scoped_to_the_unilever_demand_table():
    assert set(FACT_COLUMN_RENAMES) == {"unilever_sku_demand_fact"}
    df = pd.DataFrame({"net_amount_inc_tax": [2.0]})
    assert list(_rename_to_table_columns(df, "sales_fact").columns) == ["net_amount_inc_tax"]


def test_product_metadata_text_forms_match_the_live_dimension():
    assert _clean_text("MASTER\r\n  CLEANSER OIL CONTROL 144X70ML") == "MASTER CLEANSER OIL CONTROL 144X70ML"
    assert _clean_text("   ") is None and _clean_text(None) is None
    assert _pack_size_text(144.0) == "144" and _pack_size_text("72") == "72"
    assert _pack_size_text(float("nan")) is None
    assert _pack_size_text(1.5) == "1.5"  # not a whole number: kept, never rounded


# --- F2 -------------------------------------------------------------------------------------------------------

def _purchase_rows():
    return pd.DataFrame({
        "invoice_num": ["BILL/2025/0236", "BILL/2025/0236"],
        "principal": ["delmonte", "delmonte"],
        "region": ["pangasinan", "pangasinan"],
        "invoice_date": [pd.Timestamp("2025-08-14"), pd.Timestamp("2025-09-15")],
        "po_number": ["PO02660", "PO02681"],
        "untaxed_amount": [54254.00, 341680.38],
        "net_amount": [60764.48, 60764.48],  # September's net cell is a stale copy of August's
    })


def test_purchase_key_includes_invoice_date():
    assert load_source_of_truth("purchase", "both").natural_key == ["invoice_num", "principal", "region", "invoice_date"]


def test_september_purchase_reusing_an_august_bill_number_is_kept():
    out, report = dedup_facts(_purchase_rows(), load_source_of_truth("purchase", "both").natural_key, amount_col="net_amount")
    assert len(out) == 2
    assert report.conflicting_groups == []  # different keys, so not a conflict either


def test_same_key_and_amount_but_another_business_column_differs_is_a_conflict_not_a_duplicate():
    """The old rule compared the key plus amount_col only and collapsed these two."""
    out, report = dedup_facts(_purchase_rows(), ["invoice_num", "principal", "region"], amount_col="net_amount")
    assert len(out) == 2
    assert len(report.conflicting_groups) == 1
    assert set(report.conflicting_groups[0]["differing_columns"]) == {"invoice_date", "po_number", "untaxed_amount"}


def test_exact_copies_still_collapse_whatever_type_the_cells_arrive_as():
    df = pd.DataFrame({
        "invoice_num": ["INV/2024/5752"] * 3,
        "net_amount": [100.5, "100.50 ", 100.5],
        "customer_name": ["ABC STORE", "ABC STORE", "ABC STORE"],
        "_src_file": ["2025-03.xlsx", "2025-04.xlsx", "2025-06.xlsx"],  # provenance never makes a row distinct
    })
    out, report = dedup_facts(df, ["invoice_num"], amount_col="net_amount")
    assert len(out) == 1 and report.conflicting_groups == []


def test_key_grouping_equates_timestamp_and_date_for_the_same_day():
    df = pd.DataFrame({"invoice_num": ["B1", "B1"], "invoice_date": [pd.Timestamp("2025-09-15"), datetime.date(2025, 9, 15)],
                       "net_amount": [10.0, 10.0]})
    assert df.groupby(natural_key_series(df, ["invoice_num", "invoice_date"]), sort=False).ngroups == 1
    out, _ = dedup_facts(df, ["invoice_num", "invoice_date"], amount_col="net_amount")
    assert len(out) == 1


# --- F3 -------------------------------------------------------------------------------------------------------

AUG_2023 = Path("data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx")


def test_ilo_sheet_is_ilocos_even_though_the_file_name_says_pangasinan_first():
    assert infer_sheet_region(AUG_2023, "ILO 090223") == "ilocos"


def test_the_ilo_rule_does_not_fire_inside_other_words():
    assert infer_sheet_region(Path("x.xlsx"), "PANGASINAN-ACTUAL") == "pangasinan"
    assert infer_sheet_region(Path("x.xlsx"), "KILO PRICE LIST") == "unknown"
    assert infer_sheet_region(Path("x.xlsx"), "ILOCOS  SIGN OFF INVENTORY") == "ilocos"


def test_null_amount_on_both_rows_is_not_agreement_when_the_case_counts_differ():
    df = pd.DataFrame({
        "sku_code": ["56261", "56261"], "snapshot_date": ["2023-08-01"] * 2, "region": ["pangasinan"] * 2,
        "quantity_on_hand": [None, None], "cases": [231.0, 115.0],
    })
    out, report = dedup_facts(df, ["sku_code", "snapshot_date", "region"], amount_col="quantity_on_hand")
    assert len(out) == 2
    assert report.conflicting_groups[0]["differing_columns"] == ["cases"]


def test_null_amount_on_both_rows_still_collapses_when_everything_else_matches():
    df = pd.DataFrame({
        "sku_code": ["58492", "58492"], "snapshot_date": ["2023-08-01"] * 2, "region": ["pangasinan"] * 2,
        "quantity_on_hand": [None, None], "cases": [None, None], "pieces": [0.0, 0.0],
    })
    out, report = dedup_facts(df, ["sku_code", "snapshot_date", "region"], amount_col="quantity_on_hand")
    assert len(out) == 1 and report.conflicting_groups == []


# --- F4 -------------------------------------------------------------------------------------------------------

def _sales_frame():
    return pd.DataFrame({
        "Invoice Date": ["2025-11-20", "2025-11-20", "2025-11-21", None],
        "Invoice Num": ["DMIS0066001", "DMIS0066001", "DMIS0066675", None],
        "Customer Name": ["A STORE", "A STORE", "RCNM CONVENIENCE STORES", None],
        "Town Display": ["PAOAY", "PAOAY", "CITY OF BATAC", None],
        "Tax": [10.0, 10.0, 700.59, None],
        "Net Amount": [100.0, 100.0, 6538.87, 6638.87],
        "_sheet_role": ["data", "one_pager", "one_pager", "one_pager"],
        "_src_sheet": ["ILOCOS SALES REGISTER", "ONE PAGER", "ONE PAGER", "ONE PAGER"],
        "_principal": ["delmonte"] * 4, "_region": ["ilocos"] * 4, "_period": ["2025-11"] * 4,
        "_doc_type": ["sales_register"] * 4,
    })


def test_one_pager_invoice_found_on_no_daily_sheet_is_kept():
    out, report = transform_fact(_sales_frame(), fact="sales", principal="delmonte", amount_col="net_amount")
    assert report["orphan_rescue"] == {"roles": ["one_pager"], "candidate_rows": 3, "rescued_rows": 1}
    assert sorted(out["invoice_num"]) == ["DMIS0066001", "DMIS0066675"]
    assert out.loc[out["invoice_num"] == "DMIS0066675", "net_amount"].iloc[0] == 6538.87


def test_one_pager_copy_of_a_daily_invoice_and_its_total_row_stay_out():
    out, _ = transform_fact(_sales_frame(), fact="sales", principal="delmonte", amount_col="net_amount")
    kept = out[out["invoice_num"] == "DMIS0066001"]
    assert len(kept) == 1 and kept["_src_sheet"].iloc[0] == "ILOCOS SALES REGISTER"
    assert out["invoice_num"].notna().all()  # the ONE PAGER total line has no invoice number: never rescued


# --- F5 -------------------------------------------------------------------------------------------------------

def test_period_is_the_invoice_month_not_the_workbook_month():
    df = pd.DataFrame({"invoice_date": ["2024-09-17", "2025-04-02"], "_period": ["2025-04", "2025-04"]})
    out, report = period_from_invoice_date(df)
    assert out["_period"].tolist() == ["2024-09", "2025-04"]
    assert report["period_changed"] == 1


def test_period_is_left_alone_when_the_invoice_date_does_not_parse():
    df = pd.DataFrame({"invoice_date": [None, "not a date"], "_period": ["2025-04", "2025-04"]})
    out, report = period_from_invoice_date(df)
    assert out["_period"].tolist() == ["2025-04", "2025-04"]
    assert report == {"rows": 2, "period_changed": 0, "unparseable_invoice_date": 2, "exempt_sheet_rows": 0}


def test_hidden_sheet_copied_into_later_workbooks_collapses_to_one_row_in_its_own_month():
    df = pd.DataFrame({
        "Invoice Date": ["2024-09-17"] * 3, "Invoice Num": ["INV/2024/5752"] * 3, "Customer Name": ["A STORE"] * 3,
        "Town Display": ["AGOO"] * 3, "Tax": [1.0] * 3, "Net Amount": [50.0] * 3,
        "_sheet_role": ["data"] * 3, "_principal": ["delmonte"] * 3, "_region": ["pangasinan"] * 3,
        "_period": ["2025-03", "2025-04", "2025-06"], "_doc_type": ["sales_register"] * 3,
    })
    out, _ = transform_fact(df, fact="sales", principal="delmonte", amount_col="net_amount")
    assert len(out) == 1 and out["_period"].iloc[0] == "2024-09"
