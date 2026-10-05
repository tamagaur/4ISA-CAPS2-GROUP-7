"""Safety-stock source comparison (read-only): the current method against a forecast-error one.

    python reports/diagnostics/safety_stock_source_2026-10-05/run_comparison.py [--env .env]

Both methods use the plan's own formula (scripts/run_lp.py safety_stock_for):

    safety stock = Z x sigma_monthly / sqrt(average weekdays per month) x sqrt(review + lead days)

and differ only in what sigma_monthly is the spread of:

    current         the product's monthly sales (pieces), all its months on file
                    (scripts/run_lp.py _sigma_d_for_product) - the default, unchanged
    forecast error  forecast minus actual (pieces) in the default backtest
                    (mart.accuracy_mart, backend/marts.DEFAULT_BACKTEST_LABEL)
    same months     monthly sales again, but only over the months the backtest scored,
                    to separate the method from the window

Pesos are at last purchase price per piece (backend/stock_units.last_purchase_price_sql),
pending SSM confirmation. Classes are the stored ABC run for CLASS_PERIOD (method 'single').

One read-only transaction (BEGIN; SET TRANSACTION READ ONLY; ROLLBACK); the work is one SQL
statement. Writes summary_by_class.csv, checks.csv and figures.json here (class totals only)
and the per-product table to the git-ignored local/ folder (per-product prices are never
committed). Nothing is written to the database and no plan, forecast or class is re-run.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))

from analytics.params import PLACEHOLDERS, SERVICE_LEVEL_PCT, SERVICE_Z  # noqa: E402
from backend.marts import DEFAULT_BACKTEST_LABEL  # noqa: E402
from backend.stock_units import last_purchase_price_sql  # noqa: E402

CLASS_PERIOD = "2026-02"
CLASS_METHOD = "single"
CYCLE = "2026-03-01"      # the stored plan whose ss_i the current method must reproduce
WINDOW_DAYS = PLACEHOLDERS["review_days"] + PLACEHOLDERS["lead_days"]
MIN_MONTHS = 2            # run_lp._sigma_d_for_product: "need >= 2" periods for a spread

PRICE_EXPR, PRICE_JOIN = last_purchase_price_sql("pd")

SQL = f"""
WITH cls AS (
    SELECT product_key, tier
    FROM abc_classification
    WHERE principal = 'unilever' AND method = %(method)s AND classification_period = %(period)s
),
weekdays AS (
    SELECT to_char(d, 'YYYY-MM') AS month, COUNT(*) FILTER (WHERE EXTRACT(isodow FROM d) < 6) AS weekdays
    FROM generate_series(DATE '2022-01-01', DATE '2027-12-31', INTERVAL '1 day') d
    GROUP BY 1
),
sales AS (   -- run_lp DEMAND_QUERY + fetch_demand_history: a blank quantity counts as 0
    SELECT product_key, calendar_month AS month, COALESCE(SUM(quantity_sold), 0) AS pieces
    FROM unilever_sku_demand_fact_real
    GROUP BY 1, 2
),
cur AS (
    SELECT s.product_key, COUNT(*) AS sales_months, stddev_samp(s.pieces) AS sd_sales, AVG(w.weekdays) AS weekdays
    FROM sales s JOIN weekdays w ON w.month = s.month
    GROUP BY 1
),
err AS (
    SELECT a.product_key, COUNT(*) AS error_months, MIN(a.month) AS first_error_month, MAX(a.month) AS last_error_month,
           stddev_samp(a.forecast_pieces - a.actual_pieces) AS sd_error,
           sqrt(AVG(power(a.forecast_pieces - a.actual_pieces, 2))) AS rmse_error,
           AVG(a.forecast_pieces - a.actual_pieces) AS mean_error,
           stddev_samp(a.actual_pieces) AS sd_sales_same_months,
           AVG(w.weekdays) AS weekdays_error
    FROM mart.accuracy_mart a
    JOIN mart.forecast_run r ON r.run_id = a.run_id AND r.label = %(label)s
    JOIN weekdays w ON w.month = a.month
    WHERE a.actual_pieces IS NOT NULL AND a.forecast_pieces IS NOT NULL
    GROUP BY 1
)
SELECT pd.product_key, pd.sku_code, pd.product_name, cls.tier,
       cur.sales_months, cur.sd_sales, cur.weekdays,
       err.error_months, err.first_error_month, err.last_error_month, err.sd_error, err.rmse_error,
       err.mean_error, err.sd_sales_same_months, err.weekdays_error,
       {PRICE_EXPR} AS price_per_piece,
       lr.ss_i AS stored_ss
FROM cls
JOIN product_dimension pd ON pd.product_key = cls.product_key
LEFT JOIN cur ON cur.product_key = cls.product_key
LEFT JOIN err ON err.product_key = cls.product_key
LEFT JOIN lp_recommendation lr ON lr.product_key = cls.product_key
     AND lr.planning_cycle_date = %(cycle)s AND lr.status = 'pending'
{PRICE_JOIN}
ORDER BY cls.tier, pd.product_key
"""


def safety_stock(sd_monthly, weekdays) -> float | None:
    """The plan's formula on a monthly spread; None when there is no spread to use."""
    if sd_monthly is None or weekdays is None or float(weekdays) <= 0:
        return None
    return SERVICE_Z * float(sd_monthly) / math.sqrt(float(weekdays)) * math.sqrt(WINDOW_DAYS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=ROOT / ".env", type=Path)
    args = ap.parse_args()
    load_dotenv(dotenv_path=args.env, override=False)
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    conn.autocommit = True  # so BEGIN/ROLLBACK below are the only transaction
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(SQL, {"method": CLASS_METHOD, "period": CLASS_PERIOD, "label": DEFAULT_BACKTEST_LABEL,
                              "cycle": CYCLE})
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.execute("ROLLBACK")
    finally:
        conn.close()

    products = []
    for r in rows:
        enough_sales = (r["sales_months"] or 0) >= MIN_MONTHS
        enough_errors = (r["error_months"] or 0) >= MIN_MONTHS
        price = float(r["price_per_piece"]) if r["price_per_piece"] is not None else None
        ss_cur = safety_stock(r["sd_sales"], r["weekdays"]) if enough_sales else None
        ss_err = safety_stock(r["sd_error"], r["weekdays_error"]) if enough_errors else None
        ss_rmse = safety_stock(r["rmse_error"], r["weekdays_error"]) if enough_errors else None
        ss_same = safety_stock(r["sd_sales_same_months"], r["weekdays_error"]) if enough_errors else None
        products.append({
            "product_key": r["product_key"], "sku_code": r["sku_code"], "product_name": r["product_name"],
            "class": r["tier"], "sales_months": r["sales_months"] or 0, "error_months": r["error_months"] or 0,
            "first_error_month": r["first_error_month"], "last_error_month": r["last_error_month"],
            "mean_error_pieces": float(r["mean_error"]) if r["mean_error"] is not None else None,
            "ss_current": ss_cur, "ss_forecast_error": ss_err, "ss_forecast_error_rmse": ss_rmse,
            "ss_sales_same_months": ss_same, "price_per_piece": price,
            "stored_ss": float(r["stored_ss"]) if r["stored_ss"] is not None else None,
        })

    # ---- checks ---------------------------------------------------------------------------
    stored = [p for p in products if p["stored_ss"] is not None]
    worst = max((abs(p["ss_current"] - p["stored_ss"]) for p in stored if p["ss_current"] is not None), default=None)
    checks = [
        {"check": f"classified Unilever products, {CLASS_METHOD} run for {CLASS_PERIOD}", "value": len(products)},
        {"check": f"pending plan rows for cycle {CYCLE} among them", "value": len(stored)},
        {"check": "of those, current-method safety stock recomputed here", "value": sum(p["ss_current"] is not None for p in stored)},
        {"check": "largest |recomputed - stored ss_i|, pieces (stored is rounded to 2 places)",
         "value": round(worst, 4) if worst is not None else None},
        {"check": "check passes (largest difference <= 0.01 piece)", "value": bool(worst is not None and worst <= 0.01)},
    ]

    # ---- per-class summary ----------------------------------------------------------------
    def pesos(items, field):
        return sum(p[field] * p["price_per_piece"] for p in items)

    summary = []
    for tier in ("A", "B", "C", "all"):
        members = [p for p in products if tier == "all" or p["class"] == tier]
        with_cur = [p for p in members if p["ss_current"] is not None]
        priced_cur = [p for p in with_cur if p["price_per_piece"] is not None]
        both = [p for p in with_cur if p["ss_forecast_error"] is not None]
        comp = [p for p in both if p["price_per_piece"] is not None]
        row = {
            "class": tier, "class_period": CLASS_PERIOD,
            "products": len(members),
            "with_current_safety_stock": len(with_cur),
            "with_current_and_price": len(priced_cur),
            "current_pesos_all_priced": round(pesos(priced_cur, "ss_current"), 2),
            "with_forecast_errors": len(both),
            "comparable_products": len(comp),
            "comparable_without_price": len(both) - len(comp),
        }
        if comp:
            cur_php, err_php = pesos(comp, "ss_current"), pesos(comp, "ss_forecast_error")
            rmse_php, same_php = pesos(comp, "ss_forecast_error_rmse"), pesos(comp, "ss_sales_same_months")
            months = sorted(p["error_months"] for p in comp)
            row.update({
                "median_error_months": months[len(months) // 2] if len(months) % 2 else
                                       (months[len(months) // 2 - 1] + months[len(months) // 2]) / 2,
                "current_pieces": round(sum(p["ss_current"] for p in comp), 2),
                "forecast_error_pieces": round(sum(p["ss_forecast_error"] for p in comp), 2),
                "current_pesos": round(cur_php, 2),
                "forecast_error_pesos": round(err_php, 2),
                "difference_pesos": round(err_php - cur_php, 2),
                "difference_pct": round((err_php - cur_php) / cur_php * 100, 1) if cur_php > 0 else None,
                "products_forecast_error_lower": sum(p["ss_forecast_error"] < p["ss_current"] for p in comp),
                "products_forecast_error_higher": sum(p["ss_forecast_error"] > p["ss_current"] for p in comp),
                "forecast_error_rmse_pesos": round(rmse_php, 2),
                "sales_same_months_pesos": round(same_php, 2),
                "forecast_error_vs_sales_same_months_pct": (round((err_php - same_php) / same_php * 100, 1)
                                                            if same_php > 0 else None),
            })
        summary.append(row)

    fields = list(dict.fromkeys(k for r in summary for k in r))
    with open(OUT / "summary_by_class.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(summary)
    with open(OUT / "checks.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["check", "value"])
        w.writeheader()
        w.writerows(checks)
    local = OUT / "local"
    local.mkdir(exist_ok=True)
    with open(local / "per_product.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(products[0]))
        w.writeheader()
        w.writerows(products)
    (OUT / "figures.json").write_text(json.dumps({
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "class_period": CLASS_PERIOD, "class_method": CLASS_METHOD, "backtest": DEFAULT_BACKTEST_LABEL,
        "z": SERVICE_Z, "service_level_pct": SERVICE_LEVEL_PCT, "window_business_days": WINDOW_DAYS,
        "min_months": MIN_MONTHS, "checks": checks, "summary": summary,
    }, indent=1), encoding="utf-8")

    for c in checks:
        print(f"{c['check']}: {c['value']}")
    for r in summary:
        print(r)
    return 0 if checks[-1]["value"] else 1


if __name__ == "__main__":
    sys.exit(main())
