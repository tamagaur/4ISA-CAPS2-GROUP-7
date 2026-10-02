import os
import sys

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics.classification.fsn import no_sale_in_last_months  # noqa: E402
from analytics.params import DEAD_SKU_MONTHS  # noqa: E402

# Every active Unilever product with a demand row, and the last month it SOLD
# (quantity_sold > 0). The LEFT JOIN keeps a product that never sold — only
# returns or zero rows — with last_sale_month NULL, so it is judged dead
# rather than dropped from the candidates (2026-09-30: 272 such products
# were silently skipped by an inner join on the sales-only subquery).
CANDIDATES_QUERY = """
    WITH products_with_rows AS (
        SELECT DISTINCT product_key FROM unilever_sku_demand_fact_real
    ),
    last_sales AS (
        SELECT product_key, MAX(calendar_month) AS last_sale_month
        FROM unilever_sku_demand_fact_real
        WHERE quantity_sold > 0
        GROUP BY product_key
    )
    SELECT p.product_key, p.sku_code, s.last_sale_month
    FROM products_with_rows r
    JOIN Product_Dimension p ON p.product_key = r.product_key
    LEFT JOIN last_sales s ON s.product_key = r.product_key
    WHERE p.principal = 'unilever'
      AND p.status = 'ACTIVE'
"""


def is_dead_sku(last_sale_month: str | None, max_month: str) -> bool:
    """The runner's and FSN's rule (fsn.no_sale_in_last_months): no sale in
    the last DEAD_SKU_MONTHS calendar months up to max_month. A product that
    never sold (last_sale_month None) has no sale in any window: dead."""
    sold = [] if last_sale_month is None else [last_sale_month]
    return no_sale_in_last_months(sold, [1.0] * len(sold), max_month, DEAD_SKU_MONTHS)


def clean_dead_skus():
    """
    Disables SKUs in Product_Dimension that haven't had a single sale (quantity > 0)
    in the last DEAD_SKU_MONTHS calendar months — the runner's and FSN's rule —
    including SKUs that never had one (only returns or zero rows).
    Until 2026-09-30 any row counted, so a returns-only month kept a SKU alive.
    """
    load_dotenv('.env')
    conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
    cur = conn.cursor()

    print(f"Identifying dead SKUs (no sales in last {DEAD_SKU_MONTHS} months)...")

    cur.execute("SELECT MAX(calendar_month) FROM unilever_sku_demand_fact_real")
    max_month = cur.fetchone()[0]

    if not max_month:
        print("No sales data found.")
        return

    cur.execute(CANDIDATES_QUERY)
    dead_skus = [row for row in cur.fetchall() if is_dead_sku(row[2], max_month)]

    if not dead_skus:
        print("No dead SKUs found.")
        return

    never_sold = sum(1 for row in dead_skus if row[2] is None)
    print(f"Found {len(dead_skus)} dead SKUs ({never_sold} never sold). Disabling them...")
    dead_keys = tuple([row[0] for row in dead_skus])

    update_query = "UPDATE Product_Dimension SET status = 'DISABLED' WHERE product_key IN %s"
    cur.execute(update_query, (dead_keys,))
    conn.commit()
    print(f"Successfully disabled {len(dead_keys)} SKUs.")

if __name__ == "__main__":
    clean_dead_skus()
