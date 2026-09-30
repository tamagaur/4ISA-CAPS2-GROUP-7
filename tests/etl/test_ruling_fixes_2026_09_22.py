"""tests/etl/test_ruling_fixes_2026_09_22.py - Yuan's 2026-09-22 rulings, on a few rows each.

  H1   "PANGASINAN SALES REGISTER (2)" keeps its workbook _period; its FAKE BOOKING rows are marked for quarantine
  D12  2025-09 purchases with untaxed + tax != net are marked; the same arithmetic in another month is not
  X2   sell-out "Total With Tax" becomes net_amount, flagged tax-inclusive
  X3/X4 "Total CAS"/"Total PCS" map to quantity_cases/quantity_pieces, never combined
  sum  the defect-category merge gives NULL, not 0, for an all-missing group
  X1   SOH pack size reaches the SOH-only insert, never an UPDATE
  0026/0027 migrations
No DB.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd

from analytics.etl.transform import (
    QUARANTINE_REASON_COLUMN,
    apply_column_map,
    flag_sellout_tax_inclusive,
    flag_source_quarantine,
    period_from_invoice_date,
    relabel_sellout_source_defect_categories,
)
import scripts.run_canonical_load as loader

MIGRATIONS = Path(__file__).resolve().parents[2] / "analytics/db/migrations"
SHEET2 = "PANGASINAN SALES REGISTER (2)"


def test_exempt_sheet_keeps_the_workbook_period_other_sheets_do_not():
    df = pd.DataFrame({"invoice_date": ["2024-09-17", "2024-09-17"], "_period": ["2025-04", "2025-04"],
                       "_src_sheet": [SHEET2, "PANGASINAN SALES REGISTER"]})
    out, report = period_from_invoice_date(df)
    assert out["_period"].tolist() == ["2025-04", "2024-09"]
    assert report["exempt_sheet_rows"] == 1 and report["period_changed"] == 1


def test_fake_booking_is_marked_only_on_the_hidden_sheet_and_only_for_real_rows():
    df = pd.DataFrame({"REMARKS": [" fake booking", "FAKE BOOKING", None, "FAKE BOOKING"],
                       "_src_sheet": [SHEET2, "PANGASINAN SALES REGISTER", SHEET2, SHEET2],
                       "is_demo": [False, False, False, True]})
    out, report = flag_source_quarantine(df, "sales_register")
    assert out[QUARANTINE_REASON_COLUMN].tolist()[0] == "source remark: FAKE BOOKING"
    # Fix 7 (2026-09-30): the sheet's other REAL rows are held pending SSM, not loaded; the demo
    # row and the ordinary sheet stay unmarked.
    assert out[QUARANTINE_REASON_COLUMN].iloc[2].startswith("sheet 'PANGASINAN SALES REGISTER (2)'")
    assert out[QUARANTINE_REASON_COLUMN].iloc[[1, 3]].isna().all()
    assert report == {"marked": 2, "held": 1}


def test_stale_purchase_cells_are_marked_in_2025_09_only():
    df = pd.DataFrame({"untaxed_amount": [952583.43, 100.0, 952583.43], "tax_amount": [37868.73, 12.0, 37868.73],
                       "net_amount": [353441.46, 112.0, 353441.46], "_period": ["2025-09", "2025-09", "2024-01"]})
    out, report = flag_source_quarantine(df, "purchase_order")
    assert report["marked"] == 1
    assert out[QUARANTINE_REASON_COLUMN].iloc[0].startswith("stale cells: untaxed + tax != net")


def test_tax_inclusive_flag_true_false_null():
    raw = pd.DataFrame({"Total Without Tax": [10.0, np.nan, np.nan], "Total With Tax": [11.2, 11.2, np.nan]})
    flag = flag_sellout_tax_inclusive(raw)
    assert flag.iloc[:2].tolist() == [False, True] and pd.isna(flag.iloc[2])


def test_total_with_tax_becomes_net_amount_when_it_is_the_only_amount():
    raw = pd.DataFrame({"Total With Tax": [432.0], "Product Quantity": [3.0], "__col0__": ["/A/B"]})
    out, _ = apply_column_map(raw, "sell_out")
    assert out["net_amount"].tolist() == [432.0]


def test_total_cas_and_pcs_map_to_separate_quantity_columns():
    for doc_type in ("sales_register", "sales_return"):
        out, _ = apply_column_map(pd.DataFrame({"Total CAS": [14], "Total PCS": [2]}), doc_type)
        assert out[["quantity_cases", "quantity_pieces"]].iloc[0].tolist() == [14, 2]
        assert "bo_units" not in out.columns


def test_defect_merge_gives_null_not_zero_for_an_all_missing_group_and_keeps_real_sums():
    df = pd.DataFrame({
        "category_path": ["False", "False (2)", "False", "/A/B"], "region": ["ilocos", "ilocos", "pangasinan", "ilocos"],
        "_period": ["2023-08"] * 4, "is_demo": [False] * 4,
        "net_amount": [np.nan, np.nan, 5.0, 1.0], "quantity": [1.0, 2.0, np.nan, 1.0],
    })
    out, n = relabel_sellout_source_defect_categories(df)
    merged = out[out["category_path"] == "UNCLASSIFIED"].set_index("region")
    assert n == 3
    assert pd.isna(merged.loc["ilocos", "net_amount"]) and merged.loc["ilocos", "quantity"] == 3.0
    assert merged.loc["pangasinan", "net_amount"] == 5.0 and pd.isna(merged.loc["pangasinan", "quantity"])


def test_soh_pack_size_is_written_by_the_insert_that_never_overwrites():
    src = inspect.getsource(loader.resolve_unilever_inventory_product_key)
    assert ":pack_size" in src and "DO NOTHING" in src and "UPDATE product_dimension" not in src


def test_migration_0026_allows_the_demand_brand_source():
    sql = (MIGRATIONS / "0026_brand_source_demand_first_token_rule.sql").read_text(encoding="utf-8")
    assert "'demand_first_token_rule'" in sql and "'soh_first_token_rule'" in sql


def test_migration_0027_adds_the_five_columns_and_refreshes_the_views():
    sql = (MIGRATIONS / "0027_invoice_quantities_and_sellout_tax_flag.sql").read_text(encoding="utf-8")
    for col in ("Sales_Fact ADD COLUMN IF NOT EXISTS quantity_cases", "Sales_Fact ADD COLUMN IF NOT EXISTS quantity_pieces",
                "SalesReturn_Fact ADD COLUMN IF NOT EXISTS quantity_cases", "SalesReturn_Fact ADD COLUMN IF NOT EXISTS quantity_pieces",
                "SellOut_Fact ADD COLUMN IF NOT EXISTS net_amount_tax_inclusive BOOLEAN"):
        assert col in sql
    assert sql.count("not a SKU quantity; cases and pieces are not additive") == 4
    assert "CHECK" not in loader._strip_sql_file(sql)
    for view in ("Sales_Fact_Real", "SalesReturn_Fact_Real", "SellOut_Fact_Real"):
        assert f"CREATE OR REPLACE VIEW {view}" in sql


def test_demand_product_name_gets_the_same_apostrophe_normalization_as_soh():
    assert loader._clean_text("LADY�S CHOICE CHKSPRD+KPKOSG 12(6+1)27ML") == "LADY'S CHOICE CHKSPRD+KPKOSG 12(6+1)27ML"
    assert loader._clean_text("LADY’S  CHOICE") == "LADY'S CHOICE"
