"""
scripts/build_preview_outputs.py — the forecasts and LP results the app's PREVIEW
mode shows (backend/data_mode.py), built from real data plus Unilever's 2021-22
placeholder months. FILES ONLY: the database session is read-only, nothing is
written to Forecast_Result or LP_Recommendation.

Why files: the forecast router refuses placeholder rows everywhere except
scripts/preview_router_synth.py (DEC-27, tests/forecasting/test_router.py), and
the API must not fit a model per request. So this script runs that sanctioned
preview once, applies run_lp.py's own safety stock / ROP / LP steps to it, and
writes the result where the API reads it. Every formula is imported, not copied:
  forecasts   scripts/preview_router_synth.load_series + preview (router, holdout
              metrics, the preview's real-month MASE scale)
  band, MAPE  scripts/run_baseline_forecast._confidence_band / _clean_metric
  LP          scripts/run_lp._sigma_d_for_product + safety_stock_for,
              analytics/optimization/lp.compute_rop / build_lp_model / solve_lp

Before writing anything it reruns the same pipeline on the REAL months only and
checks the result against the live Forecast_Result (forecast, status, MASE): the
preview is only worth showing if its pipeline reproduces the live one. A mismatch
stops the build.

Pool and inputs mirror the live scripts: Unilever Tier A at the latest 'single'
ABC run, target month = latest real month + 1, LP pool = status ok and holdout
MASE < MASE_GATE, protection_days 1 (run_lp's default). The LP's warehouse
capacity and supplier ceiling have no data source (run_lp.py's docstring); they
are set far above total ROP so they never bind. With every product on the same
fallback unit cost, lp.py's normalized objective puts each Q_i at ROP_i whatever
those limits are, as long as they are feasible.

    python scripts/build_preview_outputs.py            # writes reports/preview/app_*.{csv,json}
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
import tempfile

import pandas as pd
import psycopg2
from dotenv import load_dotenv

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

from analytics.forecasting.baseline import MIN_MONTHS_WITH_SALES  # noqa: E402
from analytics.optimization.lp import SKUInput, build_lp_model, compute_rop, solve_lp  # noqa: E402
from backend.data_mode import PREVIEW_UNILEVER_DEMAND  # noqa: E402
from scripts.preview_router_synth import load_series, preview  # noqa: E402
from scripts.run_baseline_forecast import _clean_metric, _confidence_band  # noqa: E402
from scripts.run_lp import MASE_GATE, _sigma_d_for_product, safety_stock_for  # noqa: E402

OUT_DIR = os.path.join(REPO, "reports", "preview")
FORECAST_FILE, LP_FILE, META_FILE = "app_forecast.csv", "app_lp.csv", "app_meta.json"

TIER_A = """
    SELECT product_key FROM ABC_Classification
    WHERE principal = 'unilever' AND method = 'single' AND tier = 'A' AND classification_period = %(abc)s
"""


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


def build_series(conn, abc_period: str) -> pd.DataFrame:
    """run_baseline_forecast.fetch_demand's SUM(quantity_sold) per product and month, from the
    preview demand relation (real rows + the placeholder months before the first real month)."""
    df = pd.read_sql(f"""
        SELECT d.product_key, d.calendar_month AS month, SUM(d.quantity_sold)::float8 AS quantity,
               BOOL_OR(d.is_demo) AS is_placeholder
        FROM {PREVIEW_UNILEVER_DEMAND} d
        WHERE d.product_key IN ({TIER_A})
        GROUP BY d.product_key, d.calendar_month ORDER BY d.product_key, d.calendar_month
    """, conn, params={"abc": abc_period})
    df["quantity"] = df["quantity"].fillna(0.0)
    return df


def run_preview(series_df: pd.DataFrame, target: str, real_only: bool) -> pd.DataFrame:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "series.csv")
        series_df.to_csv(path, index=False)
        return preview(load_series(path, real_only), pd.Timestamp(target + "-01"))


def verify_against_live(conn, real_only: pd.DataFrame) -> dict:
    live = pd.read_sql("""
        SELECT product_key, forecast_value::float8 AS live_forecast, status AS live_status, mase::float8 AS live_mase
        FROM Forecast_Result WHERE forecast_date = (SELECT MAX(forecast_date) FROM Forecast_Result)""", conn)
    m = live.merge(real_only, on="product_key", how="outer", indicator=True)
    both = m[m["_merge"] == "both"]
    forecast_ok = (both["live_forecast"] - both["forecast"]).abs() < 0.01
    ok_rows = both[both["status"] == "ok"]
    mase_ok = (ok_rows["live_mase"] - ok_rows["holdout_mase"]).abs() < 0.001
    report = {
        "skus_live": int(len(live)), "skus_rebuilt": int(len(real_only)), "skus_matched": int(len(both)),
        "forecast_equal": int(forecast_ok.sum()), "status_equal": int((both["live_status"] == both["status"]).sum()),
        "mase_equal": int(mase_ok.sum()), "mase_compared": int(len(ok_rows)),
    }
    report["passed"] = (report["skus_matched"] == report["skus_live"] == report["skus_rebuilt"]
                        and report["forecast_equal"] == report["status_equal"] == report["skus_matched"]
                        and report["mase_equal"] == report["mase_compared"])
    return report


def forecast_rows(pv: pd.DataFrame, forecast_date: str, built_at: str) -> pd.DataFrame:
    """One row per SKU in Forecast_Result's shape; model_params carries the keys the UI reads
    (reports/PROJECT_DIAGNOSIS_2026-09-21.md §4.2) plus a `preview` block."""
    rows = []
    for r in pv.itertuples():
        f_val = float(r.forecast)
        preview_note = {"placeholder_months": int(r.placeholder_months), "built_at": built_at}
        if r.status == "ok":
            components = {"ma3": round(float(r.ma3_forecast), 3)}
            for key, val in (("xgb", r.xgb_component), ("tsb", r.tsb_component)):
                if val is not None and not pd.isna(val):
                    components[key] = round(float(val), 3)
            lower, upper = _confidence_band(f_val, r.holdout_rmse)
            params = {
                "method": r.served_model, "bin": r.bin, "sales_months": int(r.sales_months),
                "months_with_sales": int(r.sales_months), "ma3_value": round(float(r.ma3_forecast), 3),
                "components": components, "backup_fired": bool(r.backup_fired), "backup_reason": r.backup_reason
                if isinstance(r.backup_reason, str) else None,
                "wape": _num(r.holdout_wape), "provisional": False, "min_months_threshold": MIN_MONTHS_WITH_SALES,
                "holdout_protocol": "rolling one-step over the 20% holdout months, served model held fixed",
                "holdout_months": int(r.holdout_months),
                "holdout_metrics_served": {"mape": _num(r.holdout_mape), "mase": _num(r.holdout_mase),
                                           "rmse": _num(r.holdout_rmse), "wape": _num(r.holdout_wape),
                                           "months": int(r.holdout_months), "ma3_wape": _num(r.ma3_holdout_wape)},
                "lp_input_method": f"{r.served_model}_one_step", "preview": preview_note,
            }
            mape_pct, mase_v = _clean_metric(r.holdout_mape, 100.0), _clean_metric(r.holdout_mase)
        else:
            lower = upper = mape_pct = mase_v = None
            params = {"method": r.served_model, "bin": r.bin if isinstance(r.bin, str) else None,
                      "provisional": r.status == "insufficient_data", "min_months_threshold": MIN_MONTHS_WITH_SALES,
                      "preview": preview_note}
        rows.append({"product_key": int(r.product_key), "forecast_date": forecast_date, "forecast_value": round(f_val, 3),
                     "confidence_lower": lower, "confidence_upper": upper, "mape": mape_pct, "mase": mase_v,
                     "status": r.status, "model_params": json.dumps(params)})
    return pd.DataFrame(rows)


def lp_rows(conn, forecasts: pd.DataFrame, abc_period: str) -> pd.DataFrame:
    pool = forecasts[(forecasts["status"] == "ok") & (forecasts["mase"] < MASE_GATE)]
    dims = pd.read_sql(f"""
        SELECT product_key, COALESCE(sku_code, category_path) AS sku_id, principal, unit_price
        FROM Product_Dimension WHERE product_key IN ({TIER_A})""", conn, params={"abc": abc_period})
    cand = dims.merge(pool[["product_key", "forecast_value", "forecast_date"]], on="product_key")
    demand = pd.read_sql(f"""
        SELECT pd.product_key, pd.sku_code, pd.principal, d.calendar_month AS period, SUM(d.quantity_sold) AS total_quantity
        FROM {PREVIEW_UNILEVER_DEMAND} d JOIN Product_Dimension pd ON pd.product_key = d.product_key
        WHERE pd.product_key = ANY(%(keys)s)
        GROUP BY pd.product_key, pd.sku_code, pd.principal, d.calendar_month
        ORDER BY pd.product_key, d.calendar_month""", conn, params={"keys": [int(k) for k in cand["product_key"]]})
    demand["total_quantity"] = pd.to_numeric(demand["total_quantity"], errors="coerce").fillna(0)
    skus, rows = [], []
    for r in cand.itertuples():
        sigma_d, reason = _sigma_d_for_product(demand[demand["product_key"] == r.product_key], r.principal)
        if sigma_d is None:
            logging.warning("LP: %s gated out — %s", r.sku_id, reason)
            continue
        ss = safety_stock_for(sigma_d, 1.0)
        rop = compute_rop(forecast=float(r.forecast_value), safety_stock=ss)
        cost = float(r.unit_price) if r.unit_price is not None and not pd.isna(r.unit_price) else 1.0
        skus.append(SKUInput(sku_id=str(r.sku_id), principal=r.principal, rop=rop,
                             procurement_cost_per_unit=cost, storage_cost_per_unit=1.0))
        rows.append({"product_key": int(r.product_key), "sku_id": str(r.sku_id), "planning_cycle_date": r.forecast_date,
                     "rop_i": round(rop, 2), "ss_i": round(ss, 2)})
    if not skus:
        return pd.DataFrame(columns=["product_key", "planning_cycle_date", "q_i", "rop_i", "ss_i"])
    total_rop = sum(s.rop for s in skus)
    limits = {"warehouse_capacity": total_rop * 10, "supplier_ceilings": {"unilever": total_rop * 10}}
    result = solve_lp(build_lp_model(skus, **limits))
    if result is None:
        raise SystemExit("LP infeasible with non-binding limits — unexpected; nothing written.")
    df = pd.DataFrame(rows)
    df["q_i"] = df["sku_id"].map(result).round(2)
    return df[["product_key", "planning_cycle_date", "q_i", "rop_i", "ss_i"]]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s", force=True)
    load_dotenv(os.path.join(REPO, ".env"))
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    conn.set_session(readonly=True)  # files only — see the module docstring
    cur = conn.cursor()
    cur.execute("SELECT MAX(calendar_month), MIN(calendar_month) FROM Unilever_SKU_Demand_Fact_Real")
    last_real, first_real = cur.fetchone()
    # The placeholder these files are built on, measured exactly as
    # backend/data_mode.placeholder_window() does, so the app can tell when
    # the database's placeholder has since changed (data_mode._outputs_stale).
    cur.execute("""SELECT COUNT(*), SUM(quantity_sold) FROM Unilever_SKU_Demand_Fact
                   WHERE is_demo = true AND calendar_month < %s""", (first_real,))
    pw_rows, pw_qty = cur.fetchone()
    target = str(pd.Period(last_real, freq="M") + 1)
    cur.execute("""SELECT MAX(classification_period) FROM ABC_Classification
                   WHERE principal = 'unilever' AND method = 'single' AND classification_period <= %s""", (last_real,))
    abc_period = cur.fetchone()[0]

    series_df = build_series(conn, abc_period)
    check = verify_against_live(conn, run_preview(series_df, target, real_only=True))
    print(f"real-only rebuild vs live Forecast_Result: {check}")
    if not check["passed"]:
        raise SystemExit("The preview pipeline no longer reproduces the live forecasts — nothing written.")

    built_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    pv = run_preview(series_df, target, real_only=False)
    forecasts = forecast_rows(pv, f"{target}-01", built_at)
    lp = lp_rows(conn, forecasts, abc_period)
    meta = {
        "built_at": built_at, "target_month": target, "abc_period": abc_period, "first_real_month": first_real,
        "last_real_month": last_real, "series_rows": int(len(series_df)),
        "placeholder_rows": int(series_df["is_placeholder"].sum()),
        "placeholder_start": series_df.loc[series_df["is_placeholder"], "month"].min(),
        "placeholder_end": series_df.loc[series_df["is_placeholder"], "month"].max(),
        "placeholder_window": {"rows": int(pw_rows), "quantity_total": float(pw_qty or 0)},
        "forecast_status": forecasts["status"].value_counts().to_dict(),
        "lp_skus": int(len(lp)), "live_reproduction_check": check,
        "lp_limits": "non-binding (10 x total ROP); uniform unit cost 1.0 where unit_price is null",
        "protection_days": 1.0,
    }
    os.makedirs(args.out_dir, exist_ok=True)
    forecasts.to_csv(os.path.join(args.out_dir, FORECAST_FILE), index=False)
    lp.to_csv(os.path.join(args.out_dir, LP_FILE), index=False)
    with open(os.path.join(args.out_dir, META_FILE), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)
    print(f"wrote {len(forecasts)} forecasts ({meta['forecast_status']}) and {len(lp)} LP rows to {args.out_dir}")


if __name__ == "__main__":
    main()
