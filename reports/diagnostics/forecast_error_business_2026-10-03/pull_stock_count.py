"""
Second read-only pull (added 2026-10-03 at Yuan's request): the Unilever stock count for
March 2026, taken 6 April 2026, to derive a cost per piece for valuing surplus months.

One transaction: BEGIN; SET TRANSACTION READ ONLY; ...; ROLLBACK. Nothing written.

Column meaning (analytics/etl/transform_ssis_soh.py:21-35, config/column_maps/ssis_soh.yaml):
  quantity_on_hand   = "Stock Quantity (CS/PC)" cases part
  quantity_pieces    = the same cell's loose-pieces part
  valuation          = "Stock Value" (pesos)
  unit_cost_per_case = "Last Purchase Price(GSV/CS)", per case
Generated rows: is_demo = false AND fill_source IS NULL (both flag columns, base table).

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/forecast_error_business_2026-10-03/pull_stock_count.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "reports", "diagnostics", "fit_diagnosis_2026-10"))
import run_fit_diagnosis as F  # noqa: E402

OUT = os.path.join(HERE, "inputs")
SNAPSHOT = "2026-04-06"


def frame(cur, sql, params=None):
    cur.execute(sql, params)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


def main():
    keys = pd.read_csv(os.path.join(OUT, "tier_a.csv"))["product_key"].astype(int).tolist()
    conn, cur = F.read_only_cursor()
    try:
        snapshots = frame(cur, """
            SELECT snapshot_date, _period, is_demo, fill_source, count(*) AS rows, count(product_key) AS rows_with_key
            FROM inventory_fact WHERE principal = 'unilever' AND snapshot_date >= '2026-02-01'
            GROUP BY 1, 2, 3, 4 ORDER BY 1, 3""")
        rows = frame(cur, """
            SELECT product_key, sku_code, snapshot_date, _period, quantity_on_hand::float AS cases,
                   quantity_pieces::float AS loose_pieces, valuation::float AS stock_value,
                   unit_cost_per_case::float AS unit_cost_per_case, blocked_qty_cases::float AS blocked_cases,
                   blocked_qty_pieces::float AS blocked_pieces, stock_status, _src_file, _src_sheet
            FROM inventory_fact
            WHERE principal = 'unilever' AND snapshot_date = %s
              AND is_demo = false AND fill_source IS NULL AND product_key = ANY(%s)
            ORDER BY product_key""", (SNAPSHOT, keys))
    finally:
        conn.rollback()
        conn.close()
    snapshots.to_csv(os.path.join(OUT, "stock_count_snapshots.csv"), index=False)
    rows.to_csv(os.path.join(OUT, "stock_count_2026-04-06_tierA.csv"), index=False)
    print(snapshots.to_string(index=False))
    print(f"Tier A rows at {SNAPSHOT}: {len(rows)} ({rows['product_key'].nunique()} products)")


if __name__ == "__main__":
    main()
