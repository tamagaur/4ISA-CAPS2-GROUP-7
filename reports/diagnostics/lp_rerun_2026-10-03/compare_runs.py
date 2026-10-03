"""Cycle 2026-03: the 30 Sep 105% run (before_30sep_105pct.csv, latest-count stock) vs the 2026-10-03 103% run
(lp_run row + plan CSV, opening-count stock). Read-only (BEGIN; SET TRANSACTION READ ONLY; ...; ROLLBACK).
Writes comparison_per_product.csv and comparison_totals.json next to the inputs."""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

REPO = str(__import__("pathlib").Path(__file__).resolve().parents[3]).replace("\\", "/")
sys.path.insert(0, REPO)
load_dotenv(f"{REPO}/.env")
from backend.stock_units import STOCK_AT_PERIOD_SQL  # noqa: E402

OUT = Path(REPO) / "reports/diagnostics/lp_rerun_2026-10-03"
CYCLE = "2026-03-01"
before = pd.read_csv(OUT / "before_30sep_105pct.csv")
plan = pd.read_csv(OUT / "plan_2026-03_103pct.csv")

conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
cur = conn.cursor()
cur.execute("SET TRANSACTION READ ONLY")


def frame(sql, params=None):
    cur.execute(sql, params)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


stock_sql = STOCK_AT_PERIOD_SQL.replace(":inv_period", "%(p)s")
stock_latest = frame(stock_sql, {"p": "2026-03"})[["product_key", "stock_pieces"]].rename(columns={"stock_pieces": "stock_latest_2026_04_06"})
stock_open = frame(stock_sql, {"p": "2026-02"})[["product_key", "stock_pieces"]].rename(columns={"stock_pieces": "stock_opening_2026_03_02"})
after = frame("""SELECT lr.product_key, lr.q_i, lr.rop_i, lr.ss_i, lr.status, lr.lp_run_key, lr.generated_at
                 FROM lp_recommendation lr WHERE lr.planning_cycle_date = %s""", (CYCLE,))
run = frame("SELECT * FROM lp_run ORDER BY run_key")
fc = frame("SELECT product_key, forecast_value, generated_at AS forecast_generated_at FROM forecast_result WHERE forecast_date = %s", (CYCLE,))
tier_a = frame("""SELECT product_key FROM abc_classification
                  WHERE method = 'single' AND principal = 'unilever' AND tier = 'A'
                    AND classification_period = (SELECT MAX(classification_period) FROM abc_classification
                                                 WHERE method = 'single' AND principal = 'unilever')""")
cur.execute("SELECT MAX(classification_period) FROM abc_classification WHERE method = 'single' AND principal = 'unilever'")
abc_period = cur.fetchone()[0]
cur.execute("SELECT MAX(generated_at) FROM forecast_result")
fc_max = cur.fetchone()[0]
cur.execute("ROLLBACK")
conn.close()

num = lambda s: pd.to_numeric(s, errors="coerce")  # noqa: E731
for df in (stock_latest, stock_open, after, fc):
    for c in df.columns:
        if c not in ("status", "generated_at", "forecast_generated_at"):
            df[c] = num(df[c])

old = before[before["status"] == "pending"][["product_name", "sku_code", "product_key", "q_i", "rop_i", "ss_i"]].rename(
    columns={"q_i": "q_old_105", "rop_i": "rop_old", "ss_i": "ss_old"})
new = after[after["status"] == "pending"].rename(columns={"q_i": "q_new_103", "rop_i": "rop_new", "ss_i": "ss_new"})
cost = plan[["product_key", "cost_per_piece", "stock_on_hand", "short", "need"]].rename(
    columns={"stock_on_hand": "stock_used_new", "short": "short_new_csv", "need": "need_new_csv"})
m = (old.merge(new[["product_key", "q_new_103", "rop_new", "ss_new", "lp_run_key"]], on="product_key", how="outer", indicator=True)
        .merge(fc[["product_key", "forecast_value"]], on="product_key", how="left")
        .merge(stock_latest, on="product_key", how="left").merge(stock_open, on="product_key", how="left")
        .merge(cost, on="product_key", how="left"))
assert (m["_merge"] == "both").all(), m[m["_merge"] != "both"]
# Unilever's count lists no zero-stock rows: a product missing from a count is 0 on hand, as run_lp reads it.
m["stock_used_old"] = m["stock_latest_2026_04_06"].fillna(0.0)
m["need_old"] = (m["forecast_value"] + m["rop_old"] - m["stock_used_old"]).clip(lower=0)
m["short_old"] = (m["need_old"] - m["q_old_105"]).clip(lower=0)
m["need_new"] = (m["forecast_value"] + m["rop_new"] - m["stock_used_new"]).clip(lower=0)
m["short_new"] = (m["need_new"] - m["q_new_103"]).clip(lower=0)
assert (m["need_new"] - m["need_new_csv"]).abs().max() < 0.01

# Dashboard rule (dashboard.py safety_stock_rate): Tier A as of abc_period; comparable = a stock row and an ss_i in
# the cycle; below = stock < ss_i. A product with no stock row is excluded, not counted as 0.
ta = tier_a.merge(stock_latest, on="product_key", how="left").merge(stock_open, on="product_key", how="left")
ta = ta.merge(old[["product_key", "ss_old"]], on="product_key", how="left").merge(new[["product_key", "ss_new"]], on="product_key", how="left")


def below(stock_col, ss_col):
    comp = ta.dropna(subset=[stock_col, ss_col])
    return int((comp[stock_col] < comp[ss_col]).sum()), len(comp)


totals = {}
for name, q, short, stock_col, run_desc in (
    ("30 Sep 105% (latest count)", "q_old_105", "short_old", "stock_used_old", None),
    ("3 Oct 103% (opening count)", "q_new_103", "short_new", "stock_used_new", None),
):
    totals[name] = {
        "products_planned": int(m[q].notna().sum()),
        "short_products": int((m[short] > 0.5).sum()),
        "short_pieces": round(float(m.loc[m[short] > 0.5, short].sum()), 0),
        "order_pieces": round(float(m[q].sum()), 0),
        "order_pesos_at_cost": round(float((m[q] * m["cost_per_piece"]).sum()), 2),
        "need_pieces": round(float(m["need_old" if "old" in q else "need_new"].sum()), 0),
        "stock_on_hand_pieces": round(float(m[stock_col].sum()), 0),
        "products_ordering_0": int((m[q] < 0.5).sum()),
    }
totals["30 Sep 105% (latest count)"]["tier_a_below_ss_latest_count"] = below("stock_latest_2026_04_06", "ss_old")
totals["30 Sep 105% (latest count)"]["tier_a_below_ss_opening_count"] = below("stock_opening_2026_03_02", "ss_old")
totals["3 Oct 103% (opening count)"]["tier_a_below_ss_latest_count"] = below("stock_latest_2026_04_06", "ss_new")
totals["3 Oct 103% (opening count)"]["tier_a_below_ss_opening_count"] = below("stock_opening_2026_03_02", "ss_new")
totals["context"] = {
    "abc_period": abc_period, "tier_a_count": len(tier_a), "forecast_result_max_generated_at": str(fc_max),
    "accepted_row_before": before[before["status"] == "accepted"][["product_name", "sku_code", "q_i", "decided_at"]].to_dict("records"),
    "accepted_row_after": after[after["status"] != "pending"][["product_key", "q_i", "status", "lp_run_key", "generated_at"]].astype(str).to_dict("records"),
    "pending_rows_after": int((after["status"] == "pending").sum()),
    "pending_rows_linked_to_run": after.loc[after["status"] == "pending", "lp_run_key"].dropna().astype(int).unique().tolist(),
    "lp_run_rows": run.astype(str).to_dict("records"),
    "nan_check": {c: int(m[c].isna().sum()) for c in ("q_old_105", "q_new_103", "forecast_value", "cost_per_piece", "ss_old", "ss_new")},
}
cols = ["product_name", "sku_code", "product_key", "forecast_value", "stock_latest_2026_04_06", "stock_opening_2026_03_02",
        "ss_old", "ss_new", "rop_old", "rop_new", "q_old_105", "q_new_103", "short_old", "short_new", "cost_per_piece"]
m.sort_values("product_name")[cols].round(2).to_csv(OUT / "comparison_per_product.csv", index=False)
(OUT / "comparison_totals.json").write_text(json.dumps(totals, indent=2, default=str), encoding="utf-8")
print(json.dumps(totals, indent=2, default=str))
