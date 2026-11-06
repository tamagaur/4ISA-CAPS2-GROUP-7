"""scripts/check_upload.py: a file is judged by what is in it, by the loader's own rules, and what is missing is named."""
from __future__ import annotations

import pandas as pd
import pytest

from scripts import check_upload as cu

SALES_HEADER = ["Calendar\r\n  Month", "Product", None, "Pack Size", "Sale Quantity in\r\n  Aggr.CS", "Sale Quantity in\r\n  Aggr.PC", "GSV",
                "Total Sales Amt\r\n  Inc. Tax"]
SALES_ROW = ["03.2026", "12345678", "SOME PRODUCT", 12, 1, 12, 100.0, 112.0]
SOH_HEADER = ["Article No", "Article Description", "PACK SIZE", "Stock Quantity (CS/PC)", "Stock Value", "PO Qty", "Open SO Quantity",
              "Balance Quantity", "Status", "CATEGORY DESC"]
SOH_ROW = ["12345678", "SOME PRODUCT", 12, "1/2", 100.0, 0, 0, "1/2", "ok", "CATEGORY"]


def _xlsx(path, sheets):
    with pd.ExcelWriter(path) as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name, header=False, index=False)
    return path


def _csv(path, rows):
    pd.DataFrame(rows).to_csv(path, header=False, index=False)
    return path


def test_a_whole_sales_file_passes_as_xlsx_and_csv(tmp_path):
    rows = [SALES_HEADER, SALES_ROW]
    for path in (_xlsx(tmp_path / "unilever la union march.xlsx", {"Sheet1": rows}), _csv(tmp_path / "unilever la union.csv", rows)):
        got = cu.check(path, "sales", "2026-03")
        assert got["ok"], got["message"]


def test_a_header_is_matched_regardless_of_case_and_spacing(tmp_path):
    header = [" CALENDAR  MONTH ", "product", None, "pack size", "SALE QUANTITY IN AGGR.CS", "Sale  Quantity in Aggr.PC", "gsv", "total sales amt inc. tax"]
    assert cu.check(_csv(tmp_path / "unilever la union.csv", [header, SALES_ROW]), "sales", "2026-03")["ok"]


def test_a_csv_saved_by_excel_with_a_byte_order_mark_passes(tmp_path):
    path = tmp_path / "unilever la union.csv"
    pd.DataFrame([SALES_HEADER, SALES_ROW]).to_csv(path, header=False, index=False, encoding="utf-8-sig")
    assert cu.check(path, "sales", "2026-03")["ok"]


def test_a_missing_sales_column_is_named_in_the_files_words(tmp_path):
    header = [h for h in SALES_HEADER if h != "GSV"]
    got = cu.check(_csv(tmp_path / "unilever la union.csv", [header, SALES_ROW[:6] + SALES_ROW[7:]]), "sales", "2026-03")
    assert not got["ok"] and got["missing"] == ["GSV"] and "GSV" in got["message"]


def test_the_extension_does_not_save_a_file_with_the_wrong_content(tmp_path):
    got = cu.check(_xlsx(tmp_path / "unilever la union.xlsx", {"Sheet1": [["a", "b"], [1, 2]]}), "sales", "2026-03")
    assert not got["ok"] and "Calendar Month" in got["missing"]


def test_a_stock_workbook_in_the_sales_slot_says_what_it_is(tmp_path):
    path = _xlsx(tmp_path / "SSIS MARCH 2026.xlsx", {"SOH(APRIL 06,2026)": [SOH_HEADER, SOH_ROW]})
    got = cu.check(path, "sales", "2026-03")
    assert not got["ok"] and "SSIS workbook" in got["message"]


def test_a_stock_count_passes_with_its_sheet_columns_and_month(tmp_path):
    path = _xlsx(tmp_path / "SSIS MARCH 2026.xlsx", {"SOH(APRIL 06,2026)": [SOH_HEADER, SOH_ROW]})
    got = cu.check(path, "count", "2026-03")
    assert got["ok"], got["message"]
    assert got["month"] == "2026-03"


def test_a_stock_count_with_no_soh_sheet_is_refused(tmp_path):
    got = cu.check(_xlsx(tmp_path / "SSIS MARCH 2026.xlsx", {"RAW DATA": [SOH_HEADER, SOH_ROW]}), "count", "2026-03")
    assert not got["ok"] and got["missing"] == ["a sheet named SOH(<date>)"]


def test_a_stock_count_as_csv_is_refused_and_says_why(tmp_path):
    got = cu.check(_csv(tmp_path / "SSIS MARCH 2026.csv", [SOH_HEADER, SOH_ROW]), "count", "2026-03")
    assert not got["ok"] and "has no sheet name" in got["message"]


def test_a_stock_count_missing_a_column_names_it(tmp_path):
    header = [h for h in SOH_HEADER if h != "PO Qty"]
    got = cu.check(_xlsx(tmp_path / "SSIS MARCH 2026.xlsx", {"SOH(APRIL 06,2026)": [header, SOH_ROW[:5] + SOH_ROW[6:]]}), "count", "2026-03")
    assert not got["ok"] and got["missing"] == ["PO Qty"]


def test_a_stock_count_with_no_month_in_its_name_is_refused(tmp_path):
    got = cu.check(_xlsx(tmp_path / "stock.xlsx", {"SOH(APRIL 06,2026)": [SOH_HEADER, SOH_ROW]}), "count", "2026-03")
    assert not got["ok"] and "file name" in got["message"]


@pytest.mark.parametrize("name,kind,rows,sheet", [
    ("SSIS FEBRUARY 2026.xlsx", "count", [SOH_HEADER, SOH_ROW], "SOH(MARCH 02,2026)"),
    ("unilever la union february 2026.xlsx", "sales", [SALES_HEADER, SALES_ROW], "Sheet1"),
])
def test_a_file_that_names_another_month_is_refused(tmp_path, name, kind, rows, sheet):
    got = cu.check(_xlsx(tmp_path / name, {sheet: rows}), kind, "2026-03")
    assert not got["ok"] and "2026-02" in got["message"]


def test_a_sales_file_without_its_branch_in_the_name_is_refused(tmp_path):
    got = cu.check(_csv(tmp_path / "march sales.csv", [SALES_HEADER, SALES_ROW]), "sales", "2026-03")
    assert not got["ok"] and got["missing"] == ["La Union in the file name"]
    assert cu.check(_csv(tmp_path / "UnileverLaUnionSalesperSKU.csv", [SALES_HEADER, SALES_ROW]), "sales", "2026-03")["ok"]


def test_something_that_is_no_spreadsheet_is_refused(tmp_path):
    path = tmp_path / "unilever la union.xlsx"
    path.write_bytes(b"\x00\x01\x02 not a workbook")
    assert not cu.check(path, "sales", "2026-03")["ok"]
