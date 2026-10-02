"""tests/etl/test_layout.py - identifying a raw file by its content (2026-09-30,
layout guard: analytics/etl/extract/layout.py). No database, no raw files: every
workbook here is a small in-memory grid (or an xlsx written to tmp_path).

Covers: the column-map signatures load (and never leak into the column maps),
identification by sheet name + required headers with the file name as a hint
only, the header row chosen by content (including the stale-header case),
extra rows, extra / reordered / renamed columns, header-less columns read by
position only when they hold text, and the month taken from invoice dates when
the path names none.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import openpyxl
import pytest

from analytics.etl.extract import layout as L
from analytics.etl.transform import load_column_map
from profiling.reader import SheetGrid

SR_HEADER = ["Invoice Date", "Salesman", "Town Display", "Branch Code", "Customer Name", "Invoice Num", "REFNBR",
             "Untaxed Amount", "Discount Rate", "Discount Amount", "Tax", "Net Amount", "Balance", "Posted"]
SR_ROW = ["2025-12-02", "JUAN", "DAGUPAN", "000001", "STORE A", "INV/2025/0001", "DMP1", 1000.0, "Public", 0.0,
          120.0, 1120.0, 0.0, "Yes"]
SELL_OUT = [[None, None, None], ["SELL OUT REPORT", None, None], [None, "Product Quantity", "Total Without Tax"],
            ["/ACE/BASE", 10, 5000.0], ["/TETRA/BASE", 4, 1200.0]]


def sales_register(name="PANGASINAN SALES REGISTER", header=SR_HEADER, row=SR_ROW, above=0):
    return SheetGrid(name, [[None] * len(header)] * above + [["PANGASINAN SITE"], header, row, row])


def ident(path: str, *sheets, real_format="xlsx"):
    return L.identify(Path(path), list(sheets), real_format)


# --- signatures ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("doc_type", sorted({m for maps in L.FAMILY_MAPS.values() for m in maps}))
def test_every_family_map_carries_a_signature_that_is_not_a_column(doc_type):
    sig = L.load_signature(doc_type)
    assert sig.required and all(sig.required)
    assert not set(L.RESERVED_KEYS) & set(load_column_map(doc_type).canonical_to_raw)


def test_every_required_field_is_reachable_through_the_map():
    for maps in L.FAMILY_MAPS.values():
        for doc_type in maps:
            sig = L.load_signature(doc_type)
            for layout in sig.required:
                for name in layout:
                    assert name in sig.aliases.values() or L._norm(name) in sig.known_raw, (doc_type, name)


# --- identification --------------------------------------------------------------------------------------------

def test_a_file_is_its_content_and_the_name_only_a_hint():
    fl = ident("data/raw/2025 DECEMBER SALES REGISTER.xlsx", sales_register())
    assert (fl.ok, fl.family, fl.month, fl.month_source) == (True, "sales_register", "2025-12", "path")
    renamed = ident("x/DECEMBER 2025 export v2.xlsx", sales_register())
    assert (renamed.ok, renamed.family, renamed.month) == (True, "sales_register", "2025-12")


def test_a_name_that_contradicts_the_sheets_is_refused():
    fl = ident("x/2025 DECEMBER SALES REGISTER.xlsx", sales_register(name="PANGASINAN PURCHASE"))
    assert (fl.reason, fl.family) == ("layout_changed", None)
    assert "purchase_order" in fl.problem


def test_shared_template_sheets_with_no_deciding_name_need_the_file_name():
    bare = sales_register(name="PANGASINAN")
    assert ident("x/2025 DECEMBER SALES REGISTER.xlsx", bare).family == "sales_register"
    fl = ident("x/DECEMBER 2025 export.xlsx", bare)
    assert fl.reason == "unknown_layout" and "sales_register" in fl.problem and "purchase_order" in fl.problem


def test_unrecognised_content_is_unknown_layout():
    fl = ident("x/notes 2025-12.xlsx", SheetGrid("Sheet1", [["a", "b"], [1, 2]]))
    assert (fl.ok, fl.reason, fl.family) == (False, "unknown_layout", None)


def test_a_required_header_renamed_to_an_alias_is_the_same_file():
    header = ["Invoice Date", "Salesman", "AREA", "Customer Name", "REFERENCE #", "NET VALUE", "DISCOUNT AMNT.",
              "TAX AMNT.", "AMOUNT"]
    fl = ident("x/2025 DECEMBER SALES REGISTER.xlsx", sales_register(header=header, row=SR_ROW[:9]))
    assert fl.ok and fl.family == "sales_register" and fl.unmapped == []


def test_a_required_header_renamed_to_an_unknown_name_is_refused_naming_what_is_missing():
    header = [h if h != "Net Amount" else "Net Amt (final)" for h in SR_HEADER]
    fl = ident("x/2025 DECEMBER SALES REGISTER.xlsx", sales_register(header=header))
    assert fl.reason == "layout_changed" and "net_amount" in fl.problem


def test_extra_rows_above_the_header_move_the_verified_header_row():
    fl = ident("x/2025 DECEMBER SALES REGISTER.xlsx", sales_register(above=7))
    assert fl.ok and fl.sheets["PANGASINAN SALES REGISTER"].header_row == 8


def test_an_extra_unknown_column_loads_and_is_reported():
    fl = ident("x/2025 DECEMBER SALES REGISTER.xlsx", sales_register(header=SR_HEADER + ["Truck Plate"],
                                                                      row=SR_ROW + ["ABC 123"]))
    assert fl.ok and fl.unmapped == ["Truck Plate"]


def test_reordered_named_columns_are_the_same_layout():
    order = list(reversed(range(len(SR_HEADER))))
    fl = ident("x/2025 DECEMBER SALES REGISTER.xlsx",
               sales_register(header=[SR_HEADER[i] for i in order], row=[SR_ROW[i] for i in order]))
    assert fl.ok and fl.family == "sales_register"


def test_the_header_row_is_the_one_the_aliases_map_most_completely():
    # 2025 Sep/Dec sales-return GS/BO sheets: a stale copy of the older header
    # two rows above the real one, which adds Total CAS / Total PCS.
    stale = ["Invoice Date", "Salesman", "Town Display", "Branch Code", "Customer Name", "Invoice Num", "REFNBR",
             "Untaxed Amount", "Discount Rate", "Discount Amount", "Tax", "Net Amount", "Balance", "Posted",
             "Return Slip #", "Return Type"]
    real = stale[:7] + ["Total CAS", "Total PCS"] + stale[7:]
    grid = [["PANGASINAN SITE-"], [None] * 9 + [742118.38], stale, ["Good Stock"], real,
            ["2025-12-29", "A", "B", "L12F", "C", "INV/2025/9099", "DMP1", 24, 8, 23633.04, "P", 984.71, 2835.96,
             26469.0, 0, "Yes", "RMR47461", "GS"]]
    fl = ident("x/2025 DECEMBER SALES RETURN.xlsx", SheetGrid("PANGASINAN GS", grid))
    assert fl.ok and fl.sheets["PANGASINAN GS"].header_row == 4


def test_a_headerless_column_is_read_by_position_only_while_it_holds_text():
    assert ident("x/2025 DECEMBER SELL OUT.xlsx", SheetGrid("PANG_SELL OUT", SELL_OUT)).ok
    moved = [r[1:] + r[:1] for r in SELL_OUT]      # category column moved to the end
    fl = ident("x/2025 DECEMBER SELL OUT.xlsx", SheetGrid("PANG_SELL OUT", moved))
    assert fl.reason == "layout_changed"
    swapped_in = [[None, "Product Quantity", "Total Without Tax"] if i == 2 else [r[1], r[0], r[2]] if i >= 3 else r
                  for i, r in enumerate(SELL_OUT)]   # quantity moved into the header-less first column
    fl = ident("x/2025 DECEMBER SELL OUT.xlsx", SheetGrid("PANG_SELL OUT", swapped_in))
    assert fl.reason == "layout_changed" and "numbers" in fl.problem


def test_a_non_invoice_file_with_no_month_is_refused():
    fl = ident("x/sell out export.xlsx", SheetGrid("PANG_SELL OUT", SELL_OUT))
    assert (fl.family, fl.reason) == ("sell_out", "month_unknown")


def test_unilever_rows_carry_their_own_month():
    header = ["Calendar\r\n  Month", "Product", None, "Pack Size", "Sale Quantity in\r\n  Aggr.CS",
              "Sale Quantity in\r\n  Aggr.PC", "GSV", "Total Sales Amt\r\n  Inc. Tax"]
    grid = [["meta"]] * 11 + [header, ["01.2026", "64401259", "DOVE 340ML", "12", "1", "12", "100.00", "112.00"]]
    fl = ident("x/LU export.xls", SheetGrid("sheet1", grid), real_format="mhtml")
    assert (fl.ok, fl.family, fl.month, fl.month_source) == (True, "unilever_sku", None, "rows")
    assert fl.sheets["sheet1"].header_row == 11


# --- month from invoice dates (a real xlsx: the dates need a full read) -----------------------------------------

def _write_register(path: Path, dates: list[date]):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PANGASINAN SALES REGISTER"
    ws.append(["PANGASINAN SITE"])
    ws.append(SR_HEADER)
    for i, d in enumerate(dates):
        ws.append([d] + SR_ROW[1:5] + [f"INV/{i}"] + SR_ROW[6:])
    wb.save(path)


def test_a_file_with_no_month_in_its_name_takes_its_invoice_dates_month(tmp_path):
    f = tmp_path / "register export.xlsx"
    _write_register(f, [date(2025, 12, 1)] * 5 + [date(2025, 11, 30)])
    fl = L.identify(f)
    assert (fl.ok, fl.family, fl.month, fl.month_source) == (True, "sales_register", "2025-12", "invoice_dates")


def test_invoice_dates_split_evenly_between_months_give_no_month(tmp_path):
    f = tmp_path / "register export.xlsx"
    _write_register(f, [date(2025, 12, 1), date(2025, 11, 30)])
    fl = L.identify(f)
    assert (fl.family, fl.reason) == ("sales_register", "month_unknown")


def test_layouts_round_trip_through_the_cache_form():
    fl = ident("x/2025 DECEMBER SALES REGISTER.xlsx", sales_register(header=SR_HEADER + ["Truck Plate"],
                                                                      row=SR_ROW + ["x"]))
    back = L.from_json(fl.path, L.to_json(fl))
    assert (back.family, back.month, back.sheets, back.unmapped) == (fl.family, fl.month, fl.sheets, fl.unmapped)


def test_a_moved_file_takes_its_principal_from_its_content_and_a_contradicting_folder_is_refused():
    fl = ident("drills/x/2025 DECEMBER SELL OUT.xlsx", SheetGrid("PANG_SELL OUT", SELL_OUT))
    assert fl.ok and fl.principal == "delmonte"
    fl = ident("data/raw/Unilever/2025 DECEMBER SELL OUT.xlsx", SheetGrid("PANG_SELL OUT", SELL_OUT))
    assert fl.reason == "layout_changed" and "unilever" in fl.problem
