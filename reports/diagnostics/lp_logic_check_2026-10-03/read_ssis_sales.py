"""
Read-only: monthly sales totals from the SSIS monthly workbooks' INVOICE REG
sheets (data/raw/SSIS/<year>/SSIS <MONTH> <YEAR>.xlsx), for the stock balance
check. These workbooks are the same files the Unilever stock counts (their SOH
sheets) were loaded from; their sales sheets are NOT in the database
(CLAUDE.md: 0 real DB rows trace to the ssis_summary family).

Writes per-month, per-billing-type sums only (no customer or salesman names)
to ssis_sales_monthly.csv beside this file, plus each workbook's distributor
header and sheet names.
"""
from __future__ import annotations

import datetime
from collections import Counter
from pathlib import Path

import openpyxl
import pandas as pd

RAW = Path("C:/Users/kyuan/Capstone-Project/data/raw/SSIS")   # the worktree's data/raw is empty (gitignored)
OUT = Path(__file__).resolve().parent
MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER",
          "OCTOBER", "NOVEMBER", "DECEMBER"]
FILES = {  # 2025-03..2026-03; the February 2026 file is named "SSIS FEBRUARY 202.xlsx" on disk
    **{f"2025-{i:02d}": f"2025/SSIS {m} 2025.xlsx" for i, m in enumerate(MONTHS, 1) if i >= 3},
    "2026-01": "2026/SSIS JANUARY 2026.xlsx", "2026-02": "2026/SSIS FEBRUARY 202.xlsx",
    "2026-03": "2026/SSIS MARCH 2026.xlsx",
}
COLS = {"gsv": 9, "niv": 12, "vat": 13, "total_inc_tax": 14, "ul_gsv": 15}   # INVOICE REG layout, 0-based


def num(v) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


def main() -> None:
    rows, meta = [], []
    for month, rel in FILES.items():
        wb = openpyxl.load_workbook(RAW / rel, read_only=True, data_only=True)
        distributor, months_seen = None, Counter()
        sums: dict[str, Counter] = {}
        for ws in wb.worksheets:
            if not ws.title.upper().startswith("INVOICE REG"):
                continue
            for r in ws.iter_rows(values_only=True):
                if not r:
                    continue
                if r[0] == "Distributor":
                    distributor = r[1]
                if len(r) > 15 and isinstance(r[4], datetime.datetime):
                    months_seen[r[4].strftime("%Y-%m")] += 1
                    c = sums.setdefault(str(r[1]), Counter())
                    c["lines"] += 1
                    for k, i in COLS.items():
                        c[k] += num(r[i])
        meta.append({"month": month, "file": rel, "distributor": distributor,
                     "sheets": "; ".join(ws.title for ws in wb.worksheets),
                     "calendar_months_in_register": dict(months_seen)})
        wb.close()
        for billing, c in sums.items():
            rows.append({"month": month, "billing": billing, **{k: round(v, 2) for k, v in c.items()}})

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "ssis_sales_monthly.csv", index=False)
    pd.DataFrame(meta).to_csv(OUT / "ssis_workbooks.csv", index=False)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(meta)[["month", "distributor", "calendar_months_in_register"]].to_string(index=False))
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
