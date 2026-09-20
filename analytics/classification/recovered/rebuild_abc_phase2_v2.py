import os
from dotenv import load_dotenv
load_dotenv(r"C:\Users\kyuan\Capstone-Project\.env")
import psycopg2

conn = psycopg2.connect(os.environ["SUPABASE_DIRECT_URL"])
conn.autocommit = True
cur = conn.cursor()

BUILD_SQL = """
CREATE TABLE {target} AS
WITH periods AS (
    SELECT DISTINCT calendar_month AS period,
           to_date(calendar_month || '-01', 'YYYY-MM-DD') AS period_date
    FROM unilever_sku_demand_fact_real
),
products AS (
    SELECT product_key FROM product_dimension WHERE principal = 'unilever'
),
base AS (
    SELECT p.product_key, pr.period, pr.period_date,
           r.net_amount AS raw_amount,
           (r.product_key IS NOT NULL AND r.net_amount IS NULL) AS excluded_null
    FROM products p
    CROSS JOIN periods pr
    LEFT JOIN unilever_sku_demand_fact_real r
        ON r.product_key = p.product_key AND r.calendar_month = pr.period
),
single AS (
    SELECT product_key, period, period_date,
           CASE WHEN excluded_null THEN NULL
                WHEN raw_amount IS NULL THEN 0.0
                WHEN raw_amount < 0 THEN 0.0
                ELSE raw_amount END AS revenue,
           excluded_null
    FROM base
),
t3m_win AS (
    SELECT product_key, period, period_date,
           COUNT(*) OVER w AS window_rows,
           BOOL_OR(excluded_null) OVER w AS any_excluded_null,
           SUM(revenue) OVER w AS window_sum
    FROM single
    WINDOW w AS (PARTITION BY product_key ORDER BY period_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
),
t3m AS (
    SELECT product_key, period, period_date,
           CASE WHEN window_rows = 3 AND NOT any_excluded_null THEN window_sum ELSE NULL END AS revenue,
           any_excluded_null AS excluded_null,
           (window_rows < 3) AS insufficient_history
    FROM t3m_win
),
combined AS (
    SELECT 'single'::text AS method, product_key, period, revenue, excluded_null, false AS insufficient_history
    FROM single
    UNION ALL
    SELECT 't3m'::text AS method, product_key, period, revenue, excluded_null, insufficient_history
    FROM t3m
),
categorized AS (
    SELECT *, (revenue IS NOT NULL AND revenue = 0) AS inactive
    FROM combined
),
eligible AS (
    SELECT * FROM categorized WHERE revenue IS NOT NULL AND revenue > 0
),
eranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY method, period ORDER BY revenue DESC, product_key ASC) AS rn,
           SUM(revenue) OVER (PARTITION BY method, period) AS period_total
    FROM eligible
),
eshares AS (
    SELECT *,
           revenue / period_total AS revenue_share,
           SUM(revenue) OVER (PARTITION BY method, period ORDER BY rn ROWS UNBOUNDED PRECEDING) / period_total AS cumulative_share
    FROM eranked
    WHERE period_total > 0
)
SELECT
    '{run_id}'::text AS run_id,
    method, period AS classification_period, product_key,
    revenue AS total_revenue, revenue_share, cumulative_share,
    CASE WHEN cumulative_share <= 0.80 THEN 'A'
         WHEN cumulative_share <= 0.95 THEN 'B'
         ELSE 'C' END AS tier,
    CASE WHEN ABS(cumulative_share - 0.80) <= 0.02 THEN true
         WHEN ABS(cumulative_share - 0.95) <= 0.02 THEN true
         ELSE false END AS boundary_flag,
    excluded_null, insufficient_history, inactive
FROM eshares
UNION ALL
SELECT
    '{run_id}'::text, method, period, product_key,
    revenue, NULL, NULL, NULL, NULL,
    excluded_null, insufficient_history, inactive
FROM categorized
WHERE NOT (revenue IS NOT NULL AND revenue > 0);
"""

for target, run_id in [
    ("ssm_abc_phase2.abc_scratch_v2", "phase2_unilever_2026-09-17_v2"),
    ("ssm_abc_phase2.abc_scratch_v2_repeat", "phase2_unilever_2026-09-17_v2"),
]:
    cur.execute(f"DROP TABLE IF EXISTS {target};")
    cur.execute(BUILD_SQL.format(target=target, run_id=run_id))
    cur.execute(f"SELECT method, count(*) FROM {target} GROUP BY method;")
    print(target, "row counts:", cur.fetchall())

cur.close()
conn.close()
