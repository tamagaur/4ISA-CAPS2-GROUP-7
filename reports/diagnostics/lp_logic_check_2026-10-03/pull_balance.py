"""
Second read-only pull for the stock balance check (2026-10-03): is there any
Unilever sales or receipts source for 2025-09..2026-04 besides the SKU demand
fact pulled by pull_data.py?

Same rules as pull_data.py: one REPEATABLE READ, READ ONLY transaction (set
with SET TRANSACTION, never a session SET), rolled back; output to the
gitignored scratch folder. Counts are taken from the BASE tables split by
is_demo / fill_source, so a generated row is visible as generated rather than
silently filtered; only is_demo = false rows count as real.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "scratch" / "lp_logic_check_2026-10-03" / "pull"
LO, HI = "2025-09", "2026-04"

QUERIES = {
    # Every place a Unilever sale, return, purchase or receipt could sit, by month.
    "balance_sources": f"""
        SELECT 'unilever_sku_demand_fact' AS source, calendar_month AS month, is_demo,
               COALESCE(fill_source, '') AS fill_source, COUNT(*) AS row_count, SUM(net_amount) AS amount
        FROM unilever_sku_demand_fact WHERE calendar_month BETWEEN '{LO}' AND '{HI}' GROUP BY 1, 2, 3, 4
        UNION ALL
        SELECT 'sales_fact', _period, is_demo, '', COUNT(*), SUM(net_amount)
        FROM sales_fact WHERE principal = 'unilever' AND _period BETWEEN '{LO}' AND '{HI}' GROUP BY 1, 2, 3, 4
        UNION ALL
        SELECT 'salesreturn_fact', _period, is_demo, '', COUNT(*), SUM(net_amount)
        FROM salesreturn_fact WHERE principal = 'unilever' AND _period BETWEEN '{LO}' AND '{HI}' GROUP BY 1, 2, 3, 4
        UNION ALL
        SELECT 'purchase_fact', _period, is_demo, '', COUNT(*), SUM(net_amount)
        FROM purchase_fact WHERE principal = 'unilever' AND _period BETWEEN '{LO}' AND '{HI}' GROUP BY 1, 2, 3, 4
        UNION ALL
        SELECT 'sku_demand_fill', _period, is_demo, '', COUNT(*), SUM(net_amount)
        FROM sku_demand_fill WHERE principal = 'unilever' AND _period BETWEEN '{LO}' AND '{HI}' GROUP BY 1, 2, 3, 4
        UNION ALL
        SELECT 'derived_receipt_fact', _period, is_demo, '', COUNT(*), SUM(receipt_value)
        FROM derived_receipt_fact WHERE principal = 'unilever' AND _period BETWEEN '{LO}' AND '{HI}' GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2, 3, 4
    """,
    "sales_fact_principals": "SELECT principal, is_demo, MIN(_period) AS first, MAX(_period) AS last, COUNT(*) AS row_count "
                             "FROM sales_fact GROUP BY 1, 2 ORDER BY 1, 2",
    "purchase_fact_principals": "SELECT principal, is_demo, MIN(_period) AS first, MAX(_period) AS last, COUNT(*) AS row_count "
                                "FROM purchase_fact GROUP BY 1, 2 ORDER BY 1, 2",
    "etl_coverage_unilever": f"SELECT * FROM etl_coverage WHERE principal = 'unilever' AND month BETWEEN '{LO}' AND '{HI}' ORDER BY month",
    "etl_load_event_unilever": f"SELECT * FROM etl_load_event WHERE principal = 'unilever' AND month BETWEEN '{LO}' AND '{HI}' ORDER BY month",
    "derived_receipt_fact_unilever": f"SELECT * FROM derived_receipt_fact WHERE principal = 'unilever' AND _period BETWEEN '{LO}' AND '{HI}'",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    load_dotenv(ROOT / ".env")
    load_dotenv(Path("C:/Users/kyuan/Capstone-Project/.env"))  # the worktree has no .env of its own
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    frames = {}
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        cur.execute("SELECT current_setting('transaction_read_only'), now()")
        ro, now = cur.fetchone()
        assert ro == "on"
        print(f"transaction_read_only={ro} snapshot_time={now}")
        for name, sql in QUERIES.items():
            cur.execute(sql)
            frames[name] = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
    finally:
        conn.rollback()
        conn.close()
    for name, df in frames.items():
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"{name:<32} {len(df):>6} rows")


if __name__ == "__main__":
    main()
