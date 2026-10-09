"""One-time read-only extract for the Tier A basis check (2026-10-03).

Pulls everything run_tier_a_basis.py needs into CSVs, in ONE read-only,
repeatable-read transaction (one consistent snapshot while another session
writes), then rolls back. No session-level SET (pooler :6543 leak).

Output goes to --out, which must sit OUTSIDE the repo: these are SSM client
sales rows, never committed (.gitignore "raw inputs are never committed").

    python pull_extract.py --out <scratch dir> --env <repo>/.env [--only followup]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

QUERIES = {
    # What the base table holds, real and generated, so the README can say
    # what the _Real view left out. fill_source is added to the select only
    # if the column exists on public (0038 may not be applied).
    "base_counts": """
        SELECT is_demo, {fill_col} AS fill_source,
               MIN(calendar_month) AS first_month, MAX(calendar_month) AS last_month,
               COUNT(*) AS rows, COUNT(DISTINCT product_key) AS products,
               SUM(net_amount) AS net_amount
        FROM unilever_sku_demand_fact
        GROUP BY 1, 2 ORDER BY 1, 2
    """,
    # Real Unilever SKU sales: the _Real view (WHERE is_demo = false).
    "demand_real": """
        SELECT product_key, sku_code, calendar_month, region,
               quantity_sold, net_amount
        FROM unilever_sku_demand_fact_real
        ORDER BY product_key, calendar_month
    """,
    "product_dim": """
        SELECT product_key, sku_code, product_name, pack_size, brand, status,
               supersedes_product_key
        FROM product_dimension
        WHERE principal = 'unilever'
        ORDER BY product_key
    """,
    # The live tier table, to check the recomputation reproduces it.
    "abc_live": """
        SELECT product_key, classification_period, method, run_id, tier,
               revenue_share, cumulative_share
        FROM abc_classification
        WHERE principal = 'unilever' AND classification_period >= '2024-01'
        ORDER BY classification_period, method, cumulative_share
    """,
    # Cost per case per product x month, averaged over rows with a cost,
    # same as run_lp.py STOCK_AND_COST_QUERY's lateral (it then takes the
    # latest period). Real stock file rows only (inventory_fact_real).
    "unit_cost": """
        SELECT inv.product_key, inv._period,
               AVG(inv.unit_cost_per_case) AS cost_per_case, COUNT(*) AS rows
        FROM inventory_fact_real inv
        JOIN product_dimension p ON p.product_key = inv.product_key
        WHERE p.principal = 'unilever' AND inv.unit_cost_per_case > 0
        GROUP BY inv.product_key, inv._period
        ORDER BY inv.product_key, inv._period
    """,
}

# Follow-up pull (README §8), run later with --only followup.
FOLLOWUP = {
    # Proves the sales rows are the ones the first pull saw.
    "demand_fingerprint": """
        SELECT COUNT(*) AS rows, COUNT(DISTINCT product_key) AS products,
               MIN(calendar_month) AS first_month, MAX(calendar_month) AS last_month,
               SUM(net_amount) AS net_amount, SUM(quantity_sold) AS quantity_sold
        FROM unilever_sku_demand_fact_real
    """,
    # Which Unilever stock files exist (the latest is the one the LP and the
    # dashboard read, backend/stock_units.STOCK_AT_LATEST_SQL).
    "stock_periods": """
        SELECT _period, COUNT(*) AS rows, COUNT(DISTINCT product_key) AS products,
               COUNT(*) FILTER (WHERE product_key IS NULL) AS rows_without_product
        FROM inventory_fact_real
        WHERE principal = 'unilever'
        GROUP BY _period ORDER BY _period DESC
    """,
    "stock_2026_03": """
        SELECT product_key, COUNT(*) AS rows, SUM(quantity_on_hand) AS cases,
               SUM(quantity_pieces) AS loose_pieces
        FROM inventory_fact_real
        WHERE principal = 'unilever' AND _period = '2026-03' AND product_key IS NOT NULL
        GROUP BY product_key ORDER BY product_key
    """,
    "forecast_dates": """
        SELECT fr.forecast_date, fr.status, COUNT(*) AS rows,
               MIN(fr.generated_at) AS first_generated, MAX(fr.generated_at) AS last_generated
        FROM forecast_result fr
        JOIN product_dimension p ON p.product_key = fr.product_key
        WHERE p.principal = 'unilever'
        GROUP BY 1, 2 ORDER BY 1 DESC, 2
    """,
    "forecast_latest": """
        SELECT fr.product_key, fr.forecast_date, fr.status, fr.mase, fr.generated_at,
               fr.model_params::text AS model_params
        FROM forecast_result fr
        JOIN product_dimension p ON p.product_key = fr.product_key
        WHERE p.principal = 'unilever'
          AND fr.forecast_date = (SELECT MAX(f2.forecast_date) FROM forecast_result f2
                                  JOIN product_dimension p2 ON p2.product_key = f2.product_key
                                  WHERE p2.principal = 'unilever')
        ORDER BY fr.product_key
    """,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--env", default=Path(".env"), type=Path, help="the .env holding SUPABASE_DB_URL")
    ap.add_argument("--only", choices=["main", "followup"], default="main",
                    help="main: the first pull (README §1-6); followup: stock and forecasts (§8)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    queries = QUERIES if args.only == "main" else FOLLOWUP

    load_dotenv(dotenv_path=args.env, override=False)
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    conn.autocommit = True  # so BEGIN/ROLLBACK below are the only transaction
    meta = {"pulled_at_utc": datetime.now(timezone.utc).isoformat(), "files": {}}
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'unilever_sku_demand_fact'
                  AND column_name = 'fill_source'
            """)
            has_fill = cur.fetchone() is not None
            meta["fill_source_column_on_public"] = has_fill
            for name, sql in queries.items():
                cur.execute(sql.format(fill_col="fill_source" if has_fill else "NULL::text"))
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                with open(args.out / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    w.writerow(cols)
                    w.writerows(rows)
                meta["files"][name] = len(rows)
                print(f"{name}: {len(rows)} rows")
            cur.execute("ROLLBACK")
    finally:
        conn.close()
    meta_name = "extract_meta.json" if args.only == "main" else "extract_meta_followup.json"
    (args.out / meta_name).write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
