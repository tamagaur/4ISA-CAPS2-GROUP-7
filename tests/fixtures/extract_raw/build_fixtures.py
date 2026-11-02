"""Builds the synthetic raw files in this folder (python tests/fixtures/extract_raw/build_fixtures.py).

Every product, customer and number below is invented. No SSM row is copied here. Each file has the smallest shape that
sends the real Extract driver down the same path as the real corpus: the filename picks the family
(profiling.profile_files.DOC_TYPE_PATTERNS), the layout picks the header row, grain and sheet role. The committed .xlsx
and .xls files are the output of this script. Rerun it after changing a layout and commit the result.

One file per family:
  SYNTH SALES REGISTER 2024 JANUARY.xlsx     two sheets, one totals row that matches and one that does not (a staged mismatch)
  SYNTH Unilever LaUnion SKU.xls             an MHTML web archive named .xls (the real file's disguise): monthly-sku grain
  SYNTH INVENTORY SIGN OFF 2024 JANUARY.xlsx a header-less code column (col 0) holding integers
  SYNTH SELL OUT 2024 JANUARY.xlsx           category grain
  SYNTH PURCHASE ORDER 2024 JANUARY.xlsx     invoice grain with an Untaxed Amount total
  SYNTH RMR GS BO 2024 JANUARY.xlsx          three sheets: ONE PAGER, GS and BO
"""
from __future__ import annotations

import datetime
from pathlib import Path

from openpyxl import Workbook

HERE = Path(__file__).resolve().parent
FIXED = datetime.datetime(2026, 1, 1)


def _save(wb: Workbook, name: str) -> None:
    wb.properties.creator = "synthetic"
    wb.properties.created = FIXED
    wb.properties.modified = FIXED
    wb.save(HERE / name)


def _sheet(wb: Workbook, title: str, rows: list[list], first: bool = False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    for r in rows:
        ws.append(r)
    return ws


def _invoice_rows(n: int, doc: str) -> list[list]:
    return [[datetime.datetime(2024, 1, 1 + i), f"INV/2024/{doc}{100 + i}", f"TEST CUSTOMER {chr(65 + i)}",
             "SYNTH SALESMAN", 1000.0 * (i + 1), 120.0 * (i + 1), 1120.0 * (i + 1)] for i in range(n)]


SALES_HEAD = ["Invoice Date", "Invoice Number", "Customer", "Salesman", "Untaxed Amount", "Tax Amount", "Net Amount"]


def sales_register() -> None:
    wb = Workbook()
    rows = _invoice_rows(4, "A")
    net = sum(r[6] for r in rows)
    # Sheet 1: the totals row (above the header) matches the Net Amount column.
    _sheet(wb, "PANGASINAN SALES REGISTER",
           [["SYNTH SALES REGISTER JANUARY 2024"], [None, None, None, None, None, None, net], SALES_HEAD] + rows, first=True)
    # Sheet 2: the totals row is wrong on purpose, so the sheet is staged with checksum_status "mismatch".
    _sheet(wb, "ILOCOS SALES REGISTER",
           [["SYNTH SALES REGISTER JANUARY 2024"], [None, None, None, None, None, None, net + 500.0], SALES_HEAD]
           + _invoice_rows(4, "B"))
    _save(wb, "SYNTH SALES REGISTER 2024 JANUARY.xlsx")


def unilever_sku() -> None:
    head = ["Calendar Month", "Product", "Pack Size", "Quantity Sold"]
    products = [("UNI0001", "12X100G"), ("UNI0002", "24X50G")]
    body = "".join(
        f"<tr><td>{m}.2023</td><td>{p}</td><td>{pack}</td><td>{10 * (i + 1) + k}</td></tr>"
        for k, m in enumerate(("01", "02", "03")) for i, (p, pack) in enumerate(products))
    html = ("<html><body><table><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>" + body + "</table></body></html>")
    text = ("MIME-Version: 1.0\r\nContent-Type: multipart/related; boundary=\"----=_NextPart_SYNTH\"\r\n\r\n"
            "------=_NextPart_SYNTH\r\nContent-Type: text/html; charset=\"utf-8\"\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"
            + html + "\r\n------=_NextPart_SYNTH--\r\n")
    (HERE / "SYNTH Unilever LaUnion SKU.xls").write_bytes(text.encode("utf-8"))


def inventory_signoff() -> None:
    wb = Workbook()
    _sheet(wb, "ILOCOS SIGN OFF", [
        ["SYNTH INVENTORY SIGN OFF JANUARY 2024"],
        [None, "Description", "Quantity", "Cost", "Valuation"],
        [100234, "SYNTH PRODUCT ONE", 10, 5.0, 50.0],
        [100235, "SYNTH PRODUCT TWO", 20, 6.0, 120.0],
        [100236, "SYNTH PRODUCT THREE", 30, 7.0, 210.0],
    ], first=True)
    _save(wb, "SYNTH INVENTORY SIGN OFF 2024 JANUARY.xlsx")


def sell_out() -> None:
    wb = Workbook()
    _sheet(wb, "PANG_SELL OUT", [
        ["Category", "Sales Value", "Quantity"],
        ["/SYNTH/CATEGORY A", 1000.0, 10],
        ["/SYNTH/CATEGORY B", 2000.0, 20],
        ["/SYNTH/CATEGORY C", 3000.0, 30],
    ], first=True)
    _save(wb, "SYNTH SELL OUT 2024 JANUARY.xlsx")


def purchase_order() -> None:
    wb = Workbook()
    rows = [[datetime.datetime(2024, 1, 5 + i), f"INV/2024/P{200 + i}", "SYNTH VENDOR", 2000.0 * (i + 1),
             2240.0 * (i + 1)] for i in range(3)]
    untaxed = sum(r[3] for r in rows)
    _sheet(wb, "PURCHASE ORDERS", [["SYNTH PURCHASE ORDERS JANUARY 2024"], [None, None, None, untaxed, None],
                                   ["Invoice Date", "Invoice Number", "Vendor", "Untaxed Amount", "Net Amount"]] + rows,
           first=True)
    _save(wb, "SYNTH PURCHASE ORDER 2024 JANUARY.xlsx")


def rmr_gs_bo() -> None:
    wb = Workbook()
    head = ["Invoice Date", "Invoice Number", "Return Type", "Net Amount"]
    gs = [[datetime.datetime(2024, 1, 3), "INV/2024/R1", "GS", 500.0], [datetime.datetime(2024, 1, 4), "INV/2024/R2", "GS", 700.0]]
    bo = [[datetime.datetime(2024, 1, 6), "INV/2024/R3", "BO", 300.0], [datetime.datetime(2024, 1, 7), "INV/2024/R4", "BO", 100.0]]
    _sheet(wb, "PANG ONE PAGER", [head] + gs + bo, first=True)
    _sheet(wb, "PANG GS", [head] + gs)
    _sheet(wb, "PANG BO", [head] + bo)
    _save(wb, "SYNTH RMR GS BO 2024 JANUARY.xlsx")


if __name__ == "__main__":
    for fn in (sales_register, unilever_sku, inventory_signoff, sell_out, purchase_order, rmr_gs_bo):
        fn()
    print("built", sorted(p.name for p in HERE.iterdir() if p.name != "build_fixtures.py"))
