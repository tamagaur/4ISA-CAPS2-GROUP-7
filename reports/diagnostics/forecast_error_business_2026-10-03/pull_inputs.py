"""
One read-only pull for the forecast-error-in-pieces-and-pesos diagnostic (2026-10-03).

One transaction: BEGIN; SET TRANSACTION READ ONLY; ...; ROLLBACK (the harness's
read_only_cursor). No session-level SET, nothing written. Everything after this
works offline from inputs/.

Generated rows: every demand figure comes from Unilever_SKU_Demand_Fact_Real, the view
that keeps only is_demo = false rows (schema.sql:865-866). The is_demo = true rows (the
2021-22 placeholders and the 2026-03..08 gap rows) are counted in base_is_demo_summary.csv
so the exclusion is visible, never read as data.

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/forecast_error_business_2026-10-03/pull_inputs.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "reports", "diagnostics", "fit_diagnosis_2026-10"))
import run_fit_diagnosis as F  # noqa: E402  (same Tier A / demand / forecast_result SQL as the served-run check)

OUT = os.path.join(HERE, "inputs")


def frame(cur, sql, params=None):
    cur.execute(sql, params)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


def main():
    os.makedirs(OUT, exist_ok=True)
    conn, cur = F.read_only_cursor()
    try:
        meta = frame(cur, "SELECT now() AS pulled_at, current_setting('transaction_read_only') AS read_only")
        base = F.load_inputs(cur)                       # tier_a, demand (all Unilever SKUs, _Real view), live
        keys = base["tier_a"]["product_key"].astype(int).tolist()
        dims = frame(cur, """
            SELECT product_key, sku_code, product_name, category_path, category_path_source,
                   brand, brand_source, pack_size, unit_price::float AS unit_price, status
            FROM product_dimension WHERE product_key = ANY(%s) ORDER BY product_key""", (keys,))
        money = frame(cur, """
            SELECT product_key, calendar_month, SUM(quantity_sold)::float AS quantity,
                   SUM(net_amount)::float AS net_amount, SUM(gsv)::float AS gsv,
                   count(*) AS source_rows, count(net_amount) AS net_amount_rows, count(gsv) AS gsv_rows,
                   bool_or(is_demo) AS any_is_demo
            FROM Unilever_SKU_Demand_Fact_Real WHERE product_key = ANY(%s)
            GROUP BY product_key, calendar_month ORDER BY product_key, calendar_month""", (keys,))
        live_full = frame(cur, """
            SELECT product_key, forecast_date, status, forecast_value::float, confidence_lower::float,
                   confidence_upper::float, mape::float, mase::float, model_params::text, generated_at
            FROM forecast_result WHERE product_key = ANY(%s) ORDER BY product_key, forecast_date""", (keys,))
        fr_dates = frame(cur, "SELECT forecast_date, count(*) AS rows FROM forecast_result GROUP BY 1 ORDER BY 1")
        is_demo = frame(cur, """
            SELECT is_demo, min(calendar_month) AS first_month, max(calendar_month) AS last_month, count(*) AS rows
            FROM Unilever_SKU_Demand_Fact GROUP BY is_demo ORDER BY is_demo""")
        cols = frame(cur, """
            SELECT table_name, column_name, data_type FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN ('unilever_sku_demand_fact', 'product_dimension', 'forecast_result', 'sales_fact')
            ORDER BY table_name, ordinal_position""")
        # Sales_Fact (the sales register) has no product_key column - table_columns.csv lists what it has
        sales_unilever = frame(cur, """
            SELECT is_demo, count(*) AS rows
            FROM sales_fact WHERE principal = 'unilever' GROUP BY is_demo ORDER BY is_demo""")
    finally:
        conn.rollback()
        conn.close()

    demand_a = base["demand"][base["demand"]["product_key"].isin(keys)]
    files = {
        "pull_meta.csv": meta, "tier_a.csv": base["tier_a"], "demand_real_tierA.csv": demand_a,
        "forecast_result_live.csv": base["live"], "forecast_result_full.csv": live_full,
        "forecast_result_dates.csv": fr_dates, "product_dimension_tierA.csv": dims,
        "demand_money_tierA.csv": money, "base_is_demo_summary.csv": is_demo,
        "table_columns.csv": cols, "sales_fact_unilever_summary.csv": sales_unilever,
    }
    for name, df in files.items():
        df.to_csv(os.path.join(OUT, name), index=False)
        print(f"{name:34s} {len(df):6d} rows")


if __name__ == "__main__":
    main()
