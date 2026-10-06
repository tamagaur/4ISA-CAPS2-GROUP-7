"""
One read-only pull for the surplus-bias experiment (2026-10-03): every Unilever stock count
in inventory_fact, so each backtest month can be paired with its own opening and closing count.

One transaction: BEGIN; SET TRANSACTION READ ONLY; ...; ROLLBACK (the shared harness's
read_only_cursor). No session-level SET, nothing written.

Generated rows: the per-product rows are filtered on BOTH flags of the base table,
is_demo = false AND fill_source IS NULL (fill_source may only be set on is_demo rows,
0038_data_fills.sql:46-57, so the second filter is a belt on the first). The snapshot
summary is NOT filtered, so the excluded generated snapshots are visible, never read as data.

Everything else (Tier A list, real demand, forecast_result copy, product dimension) is the
forecast-error diagnostic's pull of 2026-10-03 06:28 UTC, copied into inputs/ unchanged
(kelvin/forecast-error-business, reports/diagnostics/forecast_error_business_2026-10-03/inputs/).

Column meaning (backend/stock_units.py, analytics/etl/transform_ssis_soh.py):
  quantity_on_hand = cases, quantity_pieces = the LOOSE remainder in pieces,
  pieces = cases x pack_size + loose (backend/stock_units.py STOCK_PIECES_EXPR).

    SUPABASE_DIRECT_URL= ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/surplus_bias_experiment_2026-10-03/pull_stock_counts.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "reports", "diagnostics", "fit_diagnosis_2026-10"))
import run_fit_diagnosis as F  # noqa: E402  (read_only_cursor: BEGIN; SET TRANSACTION READ ONLY)

OUT = os.path.join(HERE, "inputs")


def frame(cur, sql, params=None):
    cur.execute(sql, params)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


def main():
    keys = pd.read_csv(os.path.join(OUT, "tier_a.csv"))["product_key"].astype(int).tolist()
    conn, cur = F.read_only_cursor()
    try:
        meta = frame(cur, "SELECT now() AS pulled_at, current_setting('transaction_read_only') AS read_only")
        snapshots = frame(cur, """
            SELECT _period, snapshot_date, is_demo, fill_source, count(*) AS rows,
                   count(product_key) AS rows_with_key, count(DISTINCT product_key) AS products,
                   count(DISTINCT product_key) FILTER (WHERE product_key = ANY(%s)) AS tier_a_products
            FROM inventory_fact WHERE principal = 'unilever'
            GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4""", (keys,))
        stock = frame(cur, """
            SELECT product_key, _period, snapshot_date,
                   SUM(quantity_on_hand)::float AS cases, SUM(quantity_pieces)::float AS loose_pieces,
                   SUM(valuation)::float AS stock_value, count(*) AS source_rows,
                   count(quantity_on_hand) AS cases_rows,
                   count(*) FILTER (WHERE quantity_on_hand = 'NaN') AS cases_nan,
                   count(*) FILTER (WHERE quantity_pieces = 'NaN') AS loose_nan,
                   min(quantity_on_hand)::float AS min_cases_row
            FROM inventory_fact
            WHERE principal = 'unilever' AND is_demo = false AND fill_source IS NULL
              AND product_key = ANY(%s)
            GROUP BY product_key, _period, snapshot_date ORDER BY product_key, _period""", (keys,))
        cols = frame(cur, """
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'inventory_fact' ORDER BY ordinal_position""")
    finally:
        conn.rollback()
        conn.close()
    files = {"stock_pull_meta.csv": meta, "stock_snapshots_unilever.csv": snapshots,
             "stock_real_tierA_by_period.csv": stock, "inventory_fact_columns.csv": cols}
    for name, df in files.items():
        df.to_csv(os.path.join(OUT, name), index=False)
        print(f"{name:36s} {len(df):6d} rows")
    print(meta.to_string(index=False))
    print(snapshots.to_string(index=False))


if __name__ == "__main__":
    main()
