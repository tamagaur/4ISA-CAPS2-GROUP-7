"""analytics/month_file.py: a sales file says which month it is for from what is INSIDE it; its name plays no part; what cannot be dated is refused with the reason."""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from analytics.month_file import read_month_file


def csv(tmp_path, text, name="whatever.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


MONTH_COLUMN = "sku_code,calendar_month,quantity_sold,net_amount\nA1,2026-03,5,100\nB2,2026-03,7,50.5\n"


def test_a_month_column_dates_the_file_and_the_name_is_never_consulted(tmp_path):
    for name in ("whatever.csv", "sales_2026-02.csv", "Copy of final (2).csv", "mar.CSV"):
        found = read_month_file(csv(tmp_path, MONTH_COLUMN, name))
        assert found.ok and found.period == "2026-03" and [r["sku_code"] for r in found.rows] == ["A1", "B2"], name


def test_a_name_that_says_a_month_does_not_date_a_file_that_says_nothing(tmp_path):
    found = read_month_file(csv(tmp_path, "sku_code,quantity_sold,net_amount\nA1,5,100\n", "sales_2026-03.csv"))
    assert not found.ok and found.period is None
    assert "cannot be dated" in found.message() and "never from its name" in found.message()


def test_daily_rows_give_the_month_and_the_first_and_last_day_and_are_summed_per_product(tmp_path):
    text = "SKU,Date,Qty,Net Sales\nA1,2026-04-02,5,100\nA1,2026-04-09,2,40\nB2,2026-04-30,7,50\n"
    found = read_month_file(csv(tmp_path, text))
    assert found.ok and found.period == "2026-04" and (found.first_day, found.last_day) == ("2026-04-02", "2026-04-30")
    assert {r["sku_code"]: (r["quantity_sold"], r["net_amount"]) for r in found.rows} == {"A1": (7.0, 140.0), "B2": (7.0, 50.0)}


def test_a_product_listed_twice_in_a_file_that_carries_only_a_month_is_refused(tmp_path):
    found = read_month_file(csv(tmp_path, MONTH_COLUMN + "A1,2026-03,1,1\n"))
    assert not found.ok and "A1 appears twice" in found.message()


def test_a_file_dated_in_two_months_is_refused_naming_both(tmp_path):
    found = read_month_file(csv(tmp_path, "sku_code,calendar_month,quantity_sold,net_amount\nA1,2026-03,5,100\nB2,2026-04,7,50\n"))
    assert not found.ok and "2026-03 (1 rows), 2026-04 (1 rows)" in found.message() and "covers one month" in found.message()


def test_a_date_that_could_be_two_things_is_refused_not_guessed(tmp_path):
    found = read_month_file(csv(tmp_path, "sku_code,date,quantity_sold,net_amount\nA1,03/04/2026,5,100\n"))
    assert not found.ok and "March 4 or April 3" in found.message()
    assert read_month_file(csv(tmp_path, "sku_code,date,quantity_sold,net_amount\nA1,17/03/2026,5,100\n")).period == "2026-03"      # unambiguous: day first


def test_a_month_written_in_words_or_above_the_table_dates_the_file(tmp_path):
    assert read_month_file(csv(tmp_path, "sku_code,month,quantity_sold,net_amount\nA1,March 2026,5,100\n")).period == "2026-03"
    titled = "Unilever sales per product, March 2026\n\nsku_code,quantity_sold,net_amount\nA1,5,100\n"
    found = read_month_file(csv(tmp_path, titled))
    assert found.ok and found.period == "2026-03" and "March 2026" in found.basis
    two = "Sales March 2026 and April 2026\nsku_code,quantity_sold,net_amount\nA1,5,100\n"
    assert not read_month_file(csv(tmp_path, two)).ok


def test_columns_are_found_by_name_in_any_order_and_a_title_block_above_is_fine(tmp_path):
    text = "Report,x\n\nNet Sales,Material,Region,Qty,Period\n10,A1,La Union,3,2026-03\n"
    found = read_month_file(csv(tmp_path, text))
    assert found.ok and found.rows == [{"sku_code": "A1", "quantity_sold": 3.0, "net_amount": 10.0, "gsv": None, "region": "La Union"}]


def test_what_is_wrong_is_refused_per_row_with_its_reason(tmp_path):
    text = "sku_code,calendar_month,quantity_sold,net_amount\nA,2026-03,x,1\nB,2026-03,-1,1\n,2026-03,1,1\nE,2026-03,2,3\n"
    found = read_month_file(csv(tmp_path, text))
    joined = " | ".join(found.problems)
    assert not found.ok and "A has a quantity" in joined and "B has a negative" in joined and "no product code" in joined


def test_a_file_with_no_table_an_empty_one_and_a_wrong_format_are_refused(tmp_path):
    assert "no table with a product code" in read_month_file(csv(tmp_path, "a,b\n1,2\n")).message()
    assert "no sales rows" in read_month_file(csv(tmp_path, "sku_code,calendar_month,quantity_sold,net_amount\n")).message() or not read_month_file(csv(tmp_path, "sku_code,calendar_month,quantity_sold,net_amount\n")).ok
    other = tmp_path / "sales.pdf"
    other.write_bytes(b"%PDF")
    assert ".csv, .xlsx or .xls" in read_month_file(other).message()


@pytest.mark.parametrize("suffix", [".xlsx"])
def test_a_workbook_is_read_the_same_way(tmp_path, suffix):
    path = tmp_path / f"anything{suffix}"
    pd.DataFrame({"Material": ["A1", "B2"], "Month": [pd.Timestamp("2026-03-15")] * 2, "Qty": [1, 2], "Net Amount": [3.5, 4]}).to_excel(path, index=False)
    found = read_month_file(path)
    assert found.ok and found.period == "2026-03" and found.first_day == "2026-03-15"
    path2 = tmp_path / "titled.xlsx"
    with pd.ExcelWriter(path2) as writer:
        pd.DataFrame([["Sales, April 2026", None, None], ["sku_code", "quantity_sold", "net_amount"], ["A1", 5, 10.0]]).to_excel(writer, index=False, header=False)
    assert read_month_file(path2).period == "2026-04"


def test_a_corrupt_workbook_is_a_refusal_with_a_reason_not_a_crash(tmp_path):
    bad = tmp_path / "broken.xlsx"
    bad.write_bytes(b"not a workbook")
    found = read_month_file(bad)
    assert not found.ok and "could not be read as XLSX" in found.message()


def test_a_python_date_cell_is_a_date(tmp_path):
    path = tmp_path / "d.xlsx"
    pd.DataFrame({"sku_code": ["A1"], "date": [datetime.date(2026, 5, 3)], "quantity_sold": [1], "net_amount": [2]}).to_excel(path, index=False)
    assert read_month_file(path).period == "2026-05"
