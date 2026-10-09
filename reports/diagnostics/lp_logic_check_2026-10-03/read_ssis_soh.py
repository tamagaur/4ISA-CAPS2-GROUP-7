"""
Read-only: the SOH sheet of each SSIS monthly workbook, summed in pesos per
column the loader does NOT use (PO Qty = open purchase orders, Open SO
Quantity = open customer orders, Balance Quantity = stock minus open orders,
Blocked Stock), next to Stock Quantity and the sheet's own Stock Value.

Quantities are 'cases/pieces' text (e.g. '14/26'), valued like the source's
own valuation: cases x Last Purchase Price(GSV/CS) + pieces x price / pack size
(backend/stock_units.py: 689 of 689 rows reconcile that way). Writes
ssis_soh_columns.csv beside this file (totals only).
"""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_ssis_sales import FILES, RAW  # noqa: E402  same workbooks

OUT = Path(__file__).resolve().parent
QTY = {"stock": "Stock Quantity (CS/PC)", "po": "PO Qty", "open_so": "Open SO Quantity",
       "balance": "Balance Quantity", "blocked": "Blocked Stock(CS/PC)"}


def cs_pc(v) -> tuple[float, float] | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        return float(v), 0.0
    parts = str(v).replace(",", "").split("/")
    try:
        return float(parts[0] or 0), float(parts[1] or 0) if len(parts) > 1 else 0.0
    except ValueError:
        return None


rows = []
for month, rel in FILES.items():
    wb = openpyxl.load_workbook(RAW / rel, read_only=True, data_only=True)
    ws = next(w for w in wb.worksheets if w.title.upper().startswith("SOH"))
    it = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(it)]
    ix = {h: i for i, h in enumerate(header)}
    tot = {k: 0.0 for k in QTY} | {"stock_value_col": 0.0, "lines": 0}
    nonblank = {k: 0 for k in QTY}
    for r in it:
        if not r or r[ix["Article No"]] in (None, ""):
            continue
        price, pack = r[ix["Last Purchase Price(GSV/CS)"]], r[ix["PACK SIZE"]]
        price = float(price) if isinstance(price, (int, float)) else 0.0
        pack = float(pack) if isinstance(pack, (int, float)) and pack > 0 else None
        tot["lines"] += 1
        sv = r[ix["Stock Value"]]
        tot["stock_value_col"] += float(sv) if isinstance(sv, (int, float)) else 0.0
        for k, col in QTY.items():
            q = cs_pc(r[ix[col]]) if col in ix else None
            if q is None:
                continue
            nonblank[k] += 1
            tot[k] += q[0] * price + (q[1] * price / pack if pack else 0.0)
    # The workbook's own INVENTORY summary ("Schedules of Ending Invty"): warehouse retail stock
    # with VAT, without VAT, and AT COST without VAT; BO (bad order) stock on its own line.
    inv = {}
    ws_inv = next((w for w in wb.worksheets if w.title.upper().strip() == "INVENTORY"), None)
    if ws_inv is not None:
        for r in ws_inv.iter_rows(values_only=True):
            label = str(r[1]).strip() if len(r) > 1 and r[1] else ""
            if label.startswith("SANSAN"):
                inv["inventory_sheet_title"] = label
            for key, prefix in (("whse_retail", "Whse Inventory"), ("bo", "BO Invty"), ("total", "TOTAL")):
                if label.startswith(prefix):
                    inv[f"{key}_with_vat"], inv[f"{key}_without_vat"], inv[f"{key}_at_cost"] = (
                        (float(v) if isinstance(v, (int, float)) else None) for v in r[2:5])
    rows.append({"period": month, "sheet": ws.title, **{f"{k}_php": round(v, 2) for k, v in tot.items() if k != "lines"},
                 "lines": tot["lines"], **{f"{k}_rows": n for k, n in nonblank.items()}, **inv})
    wb.close()

out = pd.DataFrame(rows)
out.to_csv(OUT / "ssis_soh_columns.csv", index=False)
pd.set_option("display.width", 250)
print(out.to_string(index=False))
