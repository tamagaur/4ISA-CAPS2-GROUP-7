"""
One-time, read-only pull for the LP logic check (2026-10-03).

Everything runs inside ONE transaction: REPEATABLE READ (one consistent
snapshot while another session writes) and READ ONLY, both set with
SET TRANSACTION (transaction-scoped, never a session SET: those leak
through the :6543 pooler). The transaction is rolled back at the end.

Output: CSV files in --out (default scratch/lp_logic_check_2026-10-03/pull,
gitignored: this is client data, same never-committed class as backups/).
analyse.py works from those files only.

Generated data excluded: every fact read goes through a *_Real view
(WHERE is_demo = false, analytics/db/schema.sql:859-866), which drops the
synthetic 2021-22 placeholders. Gap fills and derived receipts live in
separate tables (sku_demand_fill, derived_receipt_fact) that are not read.
The flag columns present on each table are written to columns.csv so the
README can say which ones were checked.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from analytics.params import MASE_GATE  # noqa: E402
from backend.stock_units import PACK_SIZE_NUMERIC, STOCK_PIECES_EXPR, STOCK_VALUE_EXPR  # noqa: E402
from scripts.run_lp import CANDIDATE_QUERY, DEMAND_QUERY, STOCK_AND_COST_QUERY  # noqa: E402

COLUMNS = """
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name IN ('inventory_fact', 'unilever_sku_demand_fact', 'forecast_result',
                         'lp_recommendation', 'abc_classification', 'product_dimension', 'lp_run')
    ORDER BY table_name, ordinal_position
"""

SNAPSHOT_META = """
    SELECT principal, _period,
           MIN(snapshot_date) AS snapshot_min, MAX(snapshot_date) AS snapshot_max,
           COUNT(*) AS row_count, COUNT(DISTINCT product_key) AS products,
           COUNT(*) FILTER (WHERE product_key IS NULL) AS rows_without_product,
           MIN(days_offset) AS days_offset_min, MAX(days_offset) AS days_offset_max,
           COUNT(days_offset) AS days_offset_populated,
           MIN(demand_period) AS demand_period_min, MAX(demand_period) AS demand_period_max,
           SUM(COALESCE(valuation, quantity_on_hand * unit_cost_per_case)) AS value_pesos
    FROM inventory_fact_real
    GROUP BY principal, _period
    ORDER BY principal, _period
"""

# Per product and stock period, the same expressions backend/stock_units.py
# uses (pieces = cases x pack size + loose pieces; value = the file's own
# valuation), plus the period's average cost per case for the LP's cost rule.
STOCK_BY_PERIOD = f"""
    SELECT inv.principal, inv._period, inv.product_key,
           MIN(inv.snapshot_date) AS snapshot_min, MAX(inv.snapshot_date) AS snapshot_max,
           COUNT(*) AS row_count,
           pd_pack.pack_size,
           SUM(inv.quantity_on_hand) AS stock_cases,
           SUM(inv.quantity_pieces) AS loose_pieces,
           {STOCK_PIECES_EXPR} AS stock_pieces,
           {STOCK_VALUE_EXPR} AS stock_value_pesos,
           AVG(inv.unit_cost_per_case) FILTER (WHERE inv.unit_cost_per_case > 0) AS avg_cost_per_case,
           CASE WHEN {PACK_SIZE_NUMERIC} THEN pd_pack.pack_size::numeric END AS pack_size_numeric
    FROM inventory_fact_real inv
    LEFT JOIN product_dimension pd_pack ON pd_pack.product_key = inv.product_key
    GROUP BY inv.principal, inv._period, inv.product_key, pd_pack.pack_size
    ORDER BY inv.principal, inv._period, inv.product_key
"""

UNILEVER_DEMAND = """
    SELECT product_key, sku_code, calendar_month,
           COUNT(*) AS row_count,
           SUM(quantity_sold) AS quantity_sold,
           SUM(net_amount) AS net_amount,
           SUM(gsv) AS gsv,
           COUNT(*) FILTER (WHERE quantity_sold IS NULL) AS qty_null,
           COUNT(*) FILTER (WHERE quantity_sold = 'NaN') AS qty_nan,
           COUNT(*) FILTER (WHERE net_amount IS NULL) AS net_null,
           COUNT(*) FILTER (WHERE gsv IS NULL) AS gsv_null
    FROM unilever_sku_demand_fact_real
    GROUP BY product_key, sku_code, calendar_month
    ORDER BY product_key, calendar_month
"""

FORECAST_DATES = """
    SELECT forecast_date, status, COUNT(*) AS row_count
    FROM forecast_result GROUP BY forecast_date, status ORDER BY forecast_date, status
"""

FORECAST_LATEST = """
    SELECT fr.product_key, pd.principal, fr.forecast_date, fr.forecast_value, fr.mase, fr.mape, fr.status,
           fr.model_params->>'method' AS method, fr.model_params->>'bin' AS bin,
           (fr.model_params->>'train_months')::int AS train_months,
           (fr.model_params->>'holdout_months')::int AS holdout_months,
           fr.model_params->'holdout_metrics_served'->>'mase' AS mase_served_json
    FROM forecast_result fr
    JOIN product_dimension pd ON pd.product_key = fr.product_key
    WHERE fr.forecast_date = (SELECT MAX(forecast_date) FROM forecast_result)
    ORDER BY fr.product_key
"""

ABC_LATEST = """
    WITH latest AS (
        SELECT principal, MAX(classification_period) AS p
        FROM abc_classification WHERE method = 'single' GROUP BY principal
    )
    SELECT ac.product_key, ac.principal, ac.classification_period, ac.tier, ac.revenue_share
    FROM abc_classification ac
    JOIN latest l ON l.principal = ac.principal AND l.p = ac.classification_period
    WHERE ac.method = 'single'
    ORDER BY ac.principal, ac.product_key
"""

LP_COUNTS = """
    SELECT planning_cycle_date, status, COUNT(*) AS row_count, MAX(generated_at) AS generated_at_max
    FROM lp_recommendation GROUP BY planning_cycle_date, status ORDER BY planning_cycle_date, status
"""

LP_CYCLE = """
    SELECT lr.*, pd.principal
    FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE lr.planning_cycle_date = %s
    ORDER BY lr.product_key
"""

PRODUCTS = """
    SELECT product_key, principal, grain, sku_code, product_name, pack_size, category_path
    FROM product_dimension
    WHERE principal = 'unilever'
       OR product_key IN (SELECT product_key FROM forecast_result)
       OR product_key IN (SELECT product_key FROM lp_recommendation)
    ORDER BY product_key
"""


def frame(cur, sql: str, params=None) -> pd.DataFrame:
    cur.execute(sql, params)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--out", default=str(ROOT / "scratch" / "lp_logic_check_2026-10-03" / "pull"))
    ap.add_argument("--cycle", default="2026-03-01")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    load_dotenv(ROOT / ".env")
    load_dotenv(Path("C:/Users/kyuan/Capstone-Project/.env"))  # the worktree has no .env of its own
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        cur = conn.cursor()  # psycopg2 opens the transaction on the first statement
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        cur.execute("SELECT current_setting('transaction_read_only'), current_setting('transaction_isolation'), now()")
        ro, iso, now = cur.fetchone()
        assert ro == "on", f"transaction is not read-only: {ro}"
        print(f"transaction_read_only={ro} isolation={iso} snapshot_time={now}")

        pulls = {
            "columns": frame(cur, COLUMNS),
            "snapshot_meta": frame(cur, SNAPSHOT_META),
            "stock_by_period": frame(cur, STOCK_BY_PERIOD),
            "unilever_demand_monthly": frame(cur, UNILEVER_DEMAND),
            "forecast_dates": frame(cur, FORECAST_DATES),
            "forecast_latest": frame(cur, FORECAST_LATEST),
            "abc_latest": frame(cur, ABC_LATEST),
            "lp_counts": frame(cur, LP_COUNTS),
            "lp_cycle": frame(cur, LP_CYCLE, (args.cycle,)),
            "products": frame(cur, PRODUCTS),
            "candidates": frame(cur, CANDIDATE_QUERY, (MASE_GATE,)),
        }
        keys = [int(k) for k in pulls["candidates"]["product_key"].unique()]
        # run_lp's own inputs, verbatim, for the replay check.
        pulls["run_lp_demand"] = frame(cur, DEMAND_QUERY, (keys,))
        pulls["run_lp_stock_and_cost"] = frame(cur, STOCK_AND_COST_QUERY, (keys,))
        cur.execute("SELECT to_regclass('lp_run') IS NOT NULL")
        if cur.fetchone()[0]:
            pulls["lp_run"] = frame(cur, "SELECT * FROM lp_run ORDER BY 1")
        pd.Series({"snapshot_time": str(now), "isolation": iso, "read_only": ro,
                   "cycle": args.cycle, "mase_gate": MASE_GATE}).to_csv(out / "pull_meta.csv", header=False)
    finally:
        conn.rollback()
        conn.close()

    for name, df in pulls.items():
        df.to_csv(out / f"{name}.csv", index=False)
        print(f"{name:<28} {len(df):>7} rows")


if __name__ == "__main__":
    main()
