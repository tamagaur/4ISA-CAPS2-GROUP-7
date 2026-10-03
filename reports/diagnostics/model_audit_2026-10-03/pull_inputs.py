"""
Model audit 2026-10-03 - the ONE read-only pull. Everything after this works offline from inputs/.

One transaction: BEGIN; SET TRANSACTION READ ONLY; ...; ROLLBACK (fit_diagnosis's read_only_cursor,
which checks transaction_read_only = on before any query). No session-level SET, nothing written.

Generated rows: every demand figure comes from Unilever_SKU_Demand_Fact_Real, the view that keeps only
is_demo = false rows (schema.sql:865-866). The base table is read for COUNTS ONLY (provenance.csv), to
show that no is_demo = false row carries a fill_source tag (migration 0038:56-57 makes that a CHECK).

Pulled for ALL Unilever products (not only Tier A as of 2026-02) so the audit can test the cohort
choice and a wider XGBoost training pool.

    SUPABASE_DIRECT_URL= ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/pull_inputs.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "reports", "diagnostics", "fit_diagnosis_2026-10"))
import run_fit_diagnosis as F  # noqa: E402  (read_only_cursor + the served-run Tier A / demand SQL)

OUT = os.path.join(HERE, "inputs")


def frame(cur, sql, params=None):
    cur.execute(sql, params)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


def main():
    os.makedirs(OUT, exist_ok=True)
    conn, cur = F.read_only_cursor()
    try:
        files = {
            "pull_meta.csv": frame(cur, """
                SELECT now() AS pulled_at, current_setting('transaction_read_only') AS read_only,
                       inet_server_port() AS server_port"""),
            # served-run inputs, same SQL as the runner (tier_a, demand, live forecast_result 2026-03)
            **{f"served_{k}.csv": v for k, v in F.load_inputs(cur).items()},
            "demand_real_all.csv": frame(cur, """
                SELECT product_key, sku_code, calendar_month,
                       SUM(quantity_sold)::float AS quantity, SUM(net_amount)::float AS net_amount,
                       count(*) AS source_rows, count(quantity_sold) AS quantity_rows, bool_or(is_demo) AS any_is_demo
                FROM Unilever_SKU_Demand_Fact_Real
                GROUP BY product_key, sku_code, calendar_month ORDER BY product_key, calendar_month"""),
            "abc_single_history.csv": frame(cur, """
                SELECT product_key, classification_period, tier, revenue_share::float, run_id
                FROM abc_classification WHERE principal = 'unilever' AND method = 'single'
                ORDER BY classification_period, product_key"""),
            "product_dimension_unilever.csv": frame(cur, """
                SELECT pd.product_key, pd.sku_code, pd.product_name, pd.category_path, pd.brand, pd.pack_size,
                       pd.status, pd.supersedes_product_key
                FROM product_dimension pd
                WHERE pd.product_key IN (SELECT DISTINCT product_key FROM Unilever_SKU_Demand_Fact_Real)
                ORDER BY pd.product_key"""),
            # counts only - the base table is never read as data
            "provenance.csv": frame(cur, """
                SELECT is_demo, fill_source, min(calendar_month) AS first_month, max(calendar_month) AS last_month,
                       count(*) AS rows, count(DISTINCT product_key) AS products
                FROM Unilever_SKU_Demand_Fact GROUP BY is_demo, fill_source ORDER BY is_demo, fill_source"""),
            "real_view_vs_base.csv": frame(cur, """
                SELECT (SELECT count(*) FROM Unilever_SKU_Demand_Fact_Real) AS real_view_rows,
                       (SELECT count(*) FROM Unilever_SKU_Demand_Fact WHERE is_demo = false) AS base_is_demo_false_rows,
                       (SELECT count(*) FROM Unilever_SKU_Demand_Fact
                         WHERE is_demo = false AND fill_source IS NOT NULL) AS base_real_rows_with_fill_source"""),
            "forecast_result_2026_03.csv": frame(cur, """
                SELECT product_key, status, forecast_value::float, mape::float, mase::float,
                       model_params->>'method' AS method, model_params->>'bin' AS bin, generated_at
                FROM forecast_result WHERE forecast_date = '2026-03-01' ORDER BY product_key"""),
        }
    finally:
        conn.rollback()
        conn.close()
    for name, df in files.items():
        df.to_csv(os.path.join(OUT, name), index=False)
        print(f"{name:34s} {len(df):7d} rows")


if __name__ == "__main__":
    main()
