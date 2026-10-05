"""
Read-only: are the 13 Unilever stock counts used in section 5 (periods
2025-03..2026-03) made only of real rows? Reads the BASE table, so a
generated row would show up rather than be filtered by the _Real view.
One READ ONLY transaction (SET TRANSACTION, never a session SET), rolled back.
Writes counts_are_real.csv beside this file.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(Path("C:/Users/kyuan/Capstone-Project/.env"))
SQL = """
    SELECT _period, is_demo, COALESCE(fill_source, '(null)') AS fill_source,
           COALESCE(valuation_source, '(null)') AS valuation_source,
           MIN(snapshot_date) AS counted_on, COUNT(*) AS row_count,
           SUM(COALESCE(valuation, quantity_on_hand * unit_cost_per_case)) AS value_pesos
    FROM inventory_fact
    WHERE principal = 'unilever' AND _period BETWEEN '2025-03' AND '2026-03'
    GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4
"""
# The README's "generated data excluded" counts, saved so each number has a file behind it.
FLAGS = """
    SELECT 'inventory_fact' AS table_name, principal, is_demo, COALESCE(fill_source, '(null)') AS fill_source,
           COALESCE(valuation_source, '(null)') AS valuation_source,
           CASE WHEN valuation_source = 'derived_cost' THEN _period END AS derived_cost_period, COUNT(*) AS row_count
    FROM inventory_fact GROUP BY 1, 2, 3, 4, 5, 6
    UNION ALL
    SELECT 'unilever_sku_demand_fact', 'unilever', is_demo, COALESCE(fill_source, '(null)'), '(n/a)', NULL, COUNT(*)
    FROM unilever_sku_demand_fact GROUP BY 1, 2, 3, 4, 5, 6
    ORDER BY 1, 2, 3, 4, 5, 6
"""
conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
try:
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    cur.execute(SQL)
    df = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
    cur.execute(FLAGS)
    flags = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
finally:
    conn.rollback()
    conn.close()
df.to_csv(HERE / "counts_are_real.csv", index=False)
flags.to_csv(HERE / "flag_counts.csv", index=False)
print(df.to_string(index=False))
print(flags.to_string(index=False))
