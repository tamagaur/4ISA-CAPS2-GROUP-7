"""scripts/clean_dead_skus.py - disable Unilever SKUs with no sale in the last DEAD_SKU_MONTHS months.

GATED (2026-10-21). Run with no arguments it is a DRY RUN: it reads, prints what it WOULD disable
(totals, how many are Tier A on the current basis, how many never sold, a sample) and exits having
written nothing. On 2026-10-20 that was 837 of 1,807 Unilever SKUs including 5 Tier A, and a disabled
product leaves every plan and screen.

It writes only with BOTH:
    --approved-by "<name>"     who approved the disabling (printed, never checked against a list)
    --expect-disable <N>       the exact count the dry run printed; any other count refuses, so an approval
                               is of THAT list and not of whatever the data says on the day.
Product_Dimension.status is a live table: after an approved run, take a backup first (scripts/backup_tables.py
product_dimension) and keep the printed keys. Nothing is run by importing this module.
"""
import argparse
import os
import sys

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics.classification.fsn import no_sale_in_last_months  # noqa: E402
from analytics.params import DEAD_SKU_MONTHS, abc_method_sql  # noqa: E402

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


def find_dead_skus(cur) -> tuple[str | None, list[tuple]]:
    """(latest demand month, [(product_key, sku_code, last_sale_month)] judged dead). Reads only."""
    cur.execute("SELECT MAX(calendar_month) FROM unilever_sku_demand_fact_real")
    max_month = cur.fetchone()[0]
    if not max_month:
        return None, []
    cur.execute(CANDIDATES_QUERY)
    return max_month, [row for row in cur.fetchall() if is_dead_sku(row[2], max_month)]


def tier_a_among(cur, keys: list[int]) -> tuple[str | None, int]:
    """(the latest Unilever ABC period, how many of `keys` are Tier A in it), on the current basis."""
    if not keys:
        return None, 0
    cur.execute(
        f"SELECT MAX(ac.classification_period) FROM abc_classification ac WHERE ac.principal = 'unilever' AND {abc_method_sql('ac')}"
    )
    period = cur.fetchone()[0]
    cur.execute(
        f"SELECT COUNT(*) FROM abc_classification ac WHERE ac.principal = 'unilever' AND {abc_method_sql('ac')} "
        "AND ac.classification_period = %s AND ac.tier = 'A' AND ac.product_key = ANY(%s)",
        (period, keys),
    )
    return period, cur.fetchone()[0]


def report(max_month, dead, tier_a_period, tier_a_count) -> None:
    never_sold = sum(1 for row in dead if row[2] is None)
    print(f"Latest demand month: {max_month}. Dead = no sale in the last {DEAD_SKU_MONTHS} calendar months.")
    print(f"WOULD DISABLE {len(dead)} Unilever SKUs: {never_sold} never sold, {len(dead) - never_sold} stopped selling.")
    print(f"Of them, Tier A (Unilever, ABC period {tier_a_period}, current basis): {tier_a_count}.")
    for key, sku, last in dead[:10]:
        print(f"  product_key {key}  sku {sku}  last sale {last or 'never'}")
    if len(dead) > 10:
        print(f"  ... and {len(dead) - 10} more")


def clean_dead_skus(approved_by: str | None = None, expect_disable: int | None = None) -> int:
    """Dry run unless approved_by AND expect_disable are both given and expect_disable equals the number
    of SKUs found. Returns the number disabled (0 for a dry run or a refusal)."""
    load_dotenv('.env')
    conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
    cur = conn.cursor()
    cur.execute("BEGIN")
    cur.execute("SET TRANSACTION READ ONLY")  # transaction-scoped, never session-level (the :6543 pooler leaks it)

    max_month, dead = find_dead_skus(cur)
    if not max_month:
        print("No sales data found.")
        conn.rollback()
        return 0
    if not dead:
        print("No dead SKUs found.")
        conn.rollback()
        return 0
    report(max_month, dead, *tier_a_among(cur, [row[0] for row in dead]))
    conn.rollback()

    if not (approved_by and approved_by.strip() and expect_disable is not None):
        print("\nDRY RUN: nothing was written. To disable these, rerun with "
              f"--approved-by \"<name>\" --expect-disable {len(dead)}.")
        return 0
    if expect_disable != len(dead):
        print(f"\nREFUSED: --expect-disable {expect_disable} but {len(dead)} SKUs are dead now. "
              "The approval was for a different list. Nothing was written.")
        return 0

    print(f"\nApproved by {approved_by.strip()!r}. Disabling {len(dead)} SKUs...")
    dead_keys = tuple(row[0] for row in dead)
    cur.execute("UPDATE Product_Dimension SET status = 'DISABLED' WHERE product_key IN %s", (dead_keys,))
    conn.commit()
    print(f"Successfully disabled {len(dead_keys)} SKUs. product_keys: {sorted(dead_keys)}")
    return len(dead_keys)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Disable Unilever SKUs with no recent sale. Dry run by default.")
    parser.add_argument("--approved-by", metavar="NAME", help="who approved the disabling; required to write")
    parser.add_argument("--expect-disable", type=int, metavar="N",
                        help="the count the dry run printed; required to write, must match exactly")
    args = parser.parse_args(argv)
    clean_dead_skus(args.approved_by, args.expect_disable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
