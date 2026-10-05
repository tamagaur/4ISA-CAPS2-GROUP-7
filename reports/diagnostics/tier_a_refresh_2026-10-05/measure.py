"""Tier A refresh 2026-10-05 — read-only measurements for the README.

    python reports/diagnostics/tier_a_refresh_2026-10-05/measure.py tiers     # Tier A old vs new
    python reports/diagnostics/tier_a_refresh_2026-10-05/measure.py snapshot  # cycle 2026-03 rows -> local/
    python reports/diagnostics/tier_a_refresh_2026-10-05/measure.py state     # forecast / LP / flag counts

One read-only transaction per call (BEGIN; SET TRANSACTION READ ONLY; ... ROLLBACK).
Revenue covered uses the tier rules' revenue: real sales (unilever_sku_demand_fact_real),
a negative month counted as 0 (kelvin/tier-a-basis f753f4e, 'revenue left out').
Aggregates only are printed or committed; per-product rows go to local/ (git-ignored).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
load_dotenv(REPO / ".env")

COVER_SQL = """
WITH lists AS (
    SELECT method, product_key FROM abc_classification
    WHERE principal = 'unilever' AND classification_period = '2026-02' AND tier = 'A'
      AND method IN ('single', 't12m_new')
), rev AS (
    SELECT product_key, calendar_month, GREATEST(net_amount, 0) AS pesos
    FROM unilever_sku_demand_fact_real WHERE net_amount IS NOT NULL
), windows(label, first_m, last_m) AS (
    VALUES ('Feb 2026', '2026-02', '2026-02'), ('Mar 2025 - Feb 2026', '2025-03', '2026-02')
)
SELECT w.label, m.method, COUNT(DISTINCT l.product_key) AS products,
       SUM(r.pesos) FILTER (WHERE l.product_key IS NOT NULL) AS list_pesos,
       SUM(r.pesos) AS total_pesos
FROM windows w
CROSS JOIN (VALUES ('single'), ('t12m_new')) m(method)
JOIN rev r ON r.calendar_month BETWEEN w.first_m AND w.last_m
LEFT JOIN lists l ON l.method = m.method AND l.product_key = r.product_key
GROUP BY w.label, m.method ORDER BY w.label, m.method
"""


def connect():
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor()
    cur.execute("BEGIN; SET TRANSACTION READ ONLY;")
    return conn, cur


def tiers(cur) -> dict:
    cur.execute("""
        SELECT method, COUNT(*) FILTER (WHERE tier = 'A'), COUNT(*) FILTER (WHERE tier = 'A' AND added_as_new),
               COUNT(*)
        FROM abc_classification WHERE principal = 'unilever' AND classification_period = '2026-02'
          AND method IN ('single', 't12m_new') GROUP BY method ORDER BY method""")
    out = {"lists_2026_02": [dict(zip(["method", "tier_a", "added_as_new", "classified"], r)) for r in cur.fetchall()]}
    cur.execute("""
        SELECT COUNT(*) FILTER (WHERE s.product_key IS NOT NULL AND n.product_key IS NOT NULL),
               COUNT(*) FILTER (WHERE s.product_key IS NOT NULL AND n.product_key IS NULL),
               COUNT(*) FILTER (WHERE s.product_key IS NULL AND n.product_key IS NOT NULL)
        FROM (SELECT product_key FROM abc_classification WHERE principal = 'unilever' AND method = 'single'
              AND classification_period = '2026-02' AND tier = 'A') s
        FULL JOIN (SELECT product_key FROM abc_classification WHERE principal = 'unilever' AND method = 't12m_new'
              AND classification_period = '2026-02' AND tier = 'A') n USING (product_key)""")
    out["overlap"] = dict(zip(["in_both", "old_only", "new_only"], cur.fetchone()))
    cur.execute(COVER_SQL)
    out["revenue_covered"] = [
        {"window": w, "method": m, "products": int(n), "list_pesos": float(lp), "total_pesos": float(tp),
         "covered_pct": round(100 * float(lp) / float(tp), 1)}
        for w, m, n, lp, tp in cur.fetchall()]
    cur.execute("""
        SELECT classification_period, COUNT(*) FILTER (WHERE tier = 'A'), COUNT(*) FILTER (WHERE added_as_new), COUNT(*)
        FROM abc_classification WHERE principal = 'unilever' AND method = 't12m_new'
        GROUP BY 1 ORDER BY 1""")
    out["t12m_new_runs"] = [dict(zip(["period", "tier_a", "added_as_new", "classified"], r)) for r in cur.fetchall()]
    return out


def snapshot(cur) -> dict:
    cur.execute("SELECT * FROM lp_recommendation WHERE planning_cycle_date = '2026-03-01' ORDER BY product_key")
    cols = [d[0] for d in cur.description]
    df = pd.DataFrame(cur.fetchall(), columns=cols)
    (HERE / "local").mkdir(exist_ok=True)
    path = HERE / "local" / "lp_recommendation_2026-03_before_run2.csv"
    df.to_csv(path, index=False)
    return {"rows": len(df), "by_status": {str(k): int(v) for k, v in df.status.value_counts().items()},
            "by_lp_run_key": {str(k): int(v) for k, v in df.lp_run_key.value_counts(dropna=False).items()},
            "saved": str(path)}


def state(cur) -> dict:
    out = {}
    cur.execute("SELECT status, COUNT(*), MIN(generated_at)::text FROM forecast_result GROUP BY 1 ORDER BY 1")
    out["forecast_result"] = [list(r) for r in cur.fetchall()]
    cur.execute("SELECT run_id, kind, label FROM mart.forecast_run ORDER BY run_id")
    out["forecast_runs"] = [list(r) for r in cur.fetchall()]
    cur.execute("SELECT run_key, created_at::text, code_version FROM lp_run ORDER BY run_key")
    out["lp_runs"] = [list(r) for r in cur.fetchall()]
    cur.execute("""SELECT status, lp_run_key, COUNT(*), SUM(q_i)::float FROM lp_recommendation
                   WHERE planning_cycle_date = '2026-03-01' GROUP BY 1, 2 ORDER BY 1, 2""")
    out["cycle_2026_03"] = [list(r) for r in cur.fetchall()]
    cur.execute("""SELECT planning_cycle_date::text, needs_review, COUNT(*) FROM review_flag
                   GROUP BY 1, 2 ORDER BY 1, 2""")
    out["review_flag"] = [list(r) for r in cur.fetchall()]
    cur.execute("SELECT abc_method, cohort_period, COUNT(*) FROM sku_traits GROUP BY 1, 2 ORDER BY 1, 2")
    out["sku_traits"] = [list(r) for r in cur.fetchall()]
    cur.execute("SELECT trigger, refreshed_at::text FROM mart.refresh_log ORDER BY refreshed_at DESC LIMIT 3")
    out["mart_refresh_log"] = [list(r) for r in cur.fetchall()]
    return out


if __name__ == "__main__":
    what = sys.argv[1]
    conn, cur = connect()
    try:
        result = {"tiers": tiers, "snapshot": snapshot, "state": state}[what](cur)
    finally:
        cur.execute("ROLLBACK")
        conn.close()
    print(json.dumps(result, indent=1, default=str))
