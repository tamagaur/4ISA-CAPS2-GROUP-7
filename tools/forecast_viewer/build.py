"""
tools/forecast_viewer/build.py — regenerate the Tier A Forecast Viewer.

Read-only against the DB. Produces two files next to this script:
  viz_data.json        — the data payload (actuals + recomputed forecasts + metrics)
  forecast_viewer.html — template.html with viz_data.json inlined; self-contained,
                         open it by double-clicking, no server needed.

Data sources:
  - actuals:  Unilever_SKU_Demand_Fact_Real (the _Real view; demo rows excluded)
  - forecasts + metrics: recomputed here with a ROLLING-ORIGIN, 1-step-ahead
    backtest over the last 6 real months (model refit at every origin), the
    same method as scripts/model_bakeoff.py. This matches how the forecast is
    actually run in production, so the numbers here == the bake-off Excel.
    (The old single 80/20 split held one forecast flat for 6 months and
    penalised MA3 for going stale — not how it's deployed.)
  - reports/baseline_forecast_per_sku.csv is still read for the demand class,
    span and first/last-sale month (not for the accuracy metrics anymore).

Usage (from the repo root, with .env holding SUPABASE_DB_URL):
    python tools/forecast_viewer/build.py
"""
from __future__ import annotations

import json
import os
import sys
import warnings

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv

warnings.simplefilter("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)

from analytics.forecasting.baseline import (
    naive_forecast, moving_average_forecast, sba_forecast,
    MA_WINDOW, SBA_ALPHA, MIN_MONTHS_WITH_SALES,
)
from statsmodels.tsa.forecasting.theta import ThetaModel
from statsmodels.tsa.statespace.sarimax import SARIMAX

# naive/ma3/sba use the last 1-3 months only (deliberately - see
# reports/MODEL_BAKEOFF_UNILEVER.md). theta and sarima use the FULL
# training history at every origin - added so the demo can show both
# approaches head to head on real numbers, not just assert one is better.
METHODS = ("naive", "ma3", "sba", "theta", "sarima")

CSV_PATH = os.path.join(REPO, "reports", "baseline_forecast_per_sku.csv")
ABC_PERIOD = "2026-02"  # the real ABC period run_baseline_forecast.py resolves to

TEST_H = 6        # rolling-origin test months (the last 6 real months)
MIN_TRAIN = 12    # months of history required before the first test origin

# A SKU whose first REAL sale is on/before this month is treated as an
# established product whose history is merely cut off by where the real
# data window opens (2023-01) - eligible for the "+ Synthetic" what-if.
# A SKU whose first real sale is later is treated as a genuine new launch -
# synthetic pre-launch "sales" would be fabricated, so it's not offered.
NEW_PRODUCT_CUTOFF = "2023-02"


def _theta_path(x, horizon):
    """Theta method, full-history, h-step-ahead. Falls back to naive if the
    fit fails (e.g. a flat or too-short series)."""
    try:
        y = pd.Series(x, index=pd.date_range("2000-01-01", periods=len(x), freq="MS"))
        period = 12 if len(x) >= 14 else 1
        return [float(v) for v in ThetaModel(y, period=period).fit().forecast(horizon)]
    except Exception:  # noqa: BLE001
        return [float(x[-1])] * horizon


def _sarima_path(x, horizon):
    """SARIMA(1,1,1), full-history, h-step-ahead - same fixed spec as
    scripts/model_bakeoff.py's sarima_plain. Falls back to naive if the
    fit fails."""
    try:
        y = pd.Series(x, index=pd.date_range("2000-01-01", periods=len(x), freq="MS"))
        res = SARIMAX(y, order=(1, 1, 1), enforce_stationarity=False,
                      enforce_invertibility=False).fit(disp=0)
        return [float(v) for v in res.forecast(horizon)]
    except Exception:  # noqa: BLE001
        return [float(x[-1])] * horizon


def _one_step(method, x):
    """1-step-ahead point forecast on the array x (all history so far)."""
    xs = pd.Series(x)
    if method == "naive":
        return float(naive_forecast(xs, 1)[0])
    if method == "ma3":
        return float(moving_average_forecast(xs, 1, MA_WINDOW)[0])
    if method == "sba":
        return float(sba_forecast(xs, 1, SBA_ALPHA)[0])
    if method == "theta":
        return _theta_path(x, 1)[0]
    return _sarima_path(x, 1)[0]


def rolling_backtest(s, prefix=None):
    """Rolling-origin, 1-step-ahead over the last TEST_H real months —
    the model is refit at every origin. This is how the forecast is
    actually run in production (re-run before each order cycle), so these
    metrics are the realistic ones. `prefix` (a Series of synthetic months)
    is prepended to TRAINING only; the test origins stay real.

    Returns None if there isn't enough history.
    """
    real = s.to_numpy(float)
    n = len(real)
    if n < MIN_TRAIN + 3:
        return None
    first = max(MIN_TRAIN, n - TEST_H)
    origins = list(range(first, n))
    if len(origins) < 3:
        return None
    combined = (np.concatenate([prefix.to_numpy(float), real])
                if prefix is not None and len(prefix) else real)
    off = len(combined) - n            # index shift into `combined`
    months = [s.index[t].strftime("%Y-%m") for t in origins]
    actual = [round(float(real[t]), 2) for t in origins]
    out = {"months": months, "actual": actual, "origin_index": [t for t in origins]}
    for m in METHODS:
        preds = [round(max(0.0, _one_step(m, combined[:off + t])), 2) for t in origins]
        out[m] = preds
    # MASE scale: mean |lag-1 diff| of the training window before the first
    # origin (constant across origins), same convention as scripts/model_bakeoff.py
    base = combined[:off + first]
    scale = float(np.mean(np.abs(np.diff(base)))) if len(base) > 1 else 0.0
    a = np.array([real[t] for t in origins], float)
    out["metrics"] = {}
    for m in METHODS:
        p = np.array(out[m], float)
        err = a - p
        ae = np.abs(err)
        nz = a > 0
        out["metrics"][m] = {
            "mae": round(float(ae.mean()), 4),
            "rmse": round(float(np.sqrt((err ** 2).mean())), 4),
            "mape": round(float((ae[nz] / a[nz]).mean()), 4) if nz.any() else None,
            "mase": round(float(ae.mean() / scale), 4) if scale > 0 else None,
        }
    out["train_months_at_first_origin"] = int(off + first)
    return out


def f4(v):
    v = pd.to_numeric(pd.Series([v]), errors="coerce").iloc[0]
    return None if pd.isna(v) else round(float(v), 4)


def series_of(pk, raw):
    d = raw.get(pk, {})
    s = pd.Series({pd.Timestamp(m + "-01"): d[m] for m in d}, dtype="object").sort_index()
    s = pd.to_numeric(s, errors="coerce").fillna(0.0)
    return s.resample("MS").asfreq().fillna(0.0)


def nextmonth(ts, k=1):
    return (ts + pd.offsets.MonthBegin(k)).strftime("%Y-%m")


def future_path(s, horizon):
    """h-step-ahead point forecasts for all METHODS. naive/MA3/SBA are
    level forecasters, so their path is flat (the same value repeated) —
    that flatness is the point of showing it. Theta and SARIMA use the
    full history and produce a shaped (non-flat) path. Returns
    {months: [...], naive: [...], ma3: [...], sba: [...], theta: [...], sarima: [...]}."""
    last = s.index.max()
    x = s.to_numpy(float)
    return {
        "months": [nextmonth(last, k) for k in range(1, horizon + 1)],
        "naive": [round(float(v), 2) for v in naive_forecast(s, horizon)],
        "ma3": [round(float(v), 2) for v in moving_average_forecast(s, horizon, MA_WINDOW)],
        "sba": [round(float(v), 2) for v in sba_forecast(s, horizon, SBA_ALPHA)],
        "theta": [round(max(0.0, v), 2) for v in _theta_path(x, horizon)],
        "sarima": [round(max(0.0, v), 2) for v in _sarima_path(x, horizon)],
    }


def _score(pred, actual, train):
    """MASE (lag-1) / MAPE / MAE / RMSE on the holdout — same conventions
    as analytics.forecasting.baseline.evaluate_baseline. Used only for the
    synthetic-data variant (the real variant reads the frozen CSV)."""
    pred = np.asarray(pred, float)
    actual = np.asarray(actual, float)
    err = actual - pred
    ae = np.abs(err)
    mae = float(ae.mean())
    rmse = float(np.sqrt((err ** 2).mean()))
    nz = actual != 0
    mape = float((ae[nz] / np.abs(actual[nz])).mean()) if nz.any() else None
    lag1 = np.abs(np.diff(np.asarray(train, float)))
    scale = float(lag1.mean()) if lag1.size else 0.0
    mase = float(mae / scale) if scale > 0 else None
    return {"mase": None if mase is None else round(mase, 4),
            "mape": None if mape is None else round(mape, 4),
            "mae": round(mae, 4), "rmse": round(rmse, 4)}


def _inline():
    """Re-inline the existing viz_data.json into the template (no DB)."""
    data_str = open(os.path.join(HERE, "viz_data.json"), encoding="utf-8").read()
    template = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    if "__VIZ_DATA__" not in template:
        sys.exit("template.html is missing the __VIZ_DATA__ placeholder")
    with open(os.path.join(HERE, "forecast_viewer.html"), "w", encoding="utf-8") as fh:
        fh.write(template.replace("__VIZ_DATA__", data_str))
    print("re-inlined viz_data.json into forecast_viewer.html (no DB)")


def main():
    if "--html-only" in sys.argv:
        _inline()
        return
    load_dotenv(os.path.join(REPO, ".env"))
    db_url = os.environ.get("SUPABASE_DIRECT_URL") or os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        sys.exit("SUPABASE_DB_URL not set (.env at repo root)")
    if not os.path.exists(CSV_PATH):
        sys.exit(f"{CSV_PATH} not found — run scripts/run_baseline_forecast.py first")

    csv = pd.read_csv(CSV_PATH, dtype={"sku_code": str})
    cur = psycopg2.connect(db_url).cursor()

    cur.execute(
        """
        SELECT abc.product_key, pd.sku_code, pd.product_name
        FROM ABC_Classification abc JOIN Product_Dimension pd ON pd.product_key = abc.product_key
        WHERE abc.principal = 'unilever' AND abc.classification_period = %s AND abc.tier = 'A'
        ORDER BY abc.product_key
        """,
        (ABC_PERIOD,),
    )
    tier_a = cur.fetchall()

    cur.execute("SELECT product_key, calendar_month, SUM(quantity_sold) "
                "FROM Unilever_SKU_Demand_Fact_Real GROUP BY product_key, calendar_month")
    raw = {}
    for pk, m, qty in cur.fetchall():
        raw.setdefault(pk, {})[m] = qty

    # Combined series for the "+ synthetic" toggle: real + is_demo rows,
    # capped at the last real month so the holdout stays real. Synthetic
    # is training context only - see reports/MODEL_BAKEOFF_UNILEVER.md.
    cur.execute("""
        SELECT product_key, calendar_month, SUM(COALESCE(quantity_sold, 0))
        FROM unilever_sku_demand_fact
        WHERE calendar_month <= (SELECT MAX(calendar_month) FROM unilever_sku_demand_fact_real)
        GROUP BY product_key, calendar_month
    """)
    raw_all = {}
    for pk, m, qty in cur.fetchall():
        raw_all.setdefault(pk, {})[m] = qty

    skus = []
    for pk, sc, name in tier_a:
        row = csv[csv.sku_code == sc]
        if row.empty:
            continue
        r = row.iloc[0]
        s = series_of(pk, raw)
        actuals = [{"m": ts.strftime("%Y-%m"), "q": round(float(v), 2)} for ts, v in s.items()]
        rec = {
            "sku": sc, "name": name or "Unknown product",
            "status": r["status"],
            "class_full": r["demand_class_full"],
            "class_train": None if pd.isna(r["demand_class_train"]) else r["demand_class_train"],
            "months_span": int(r["months_span"]),
            "months_with_sales": int(r["months_with_sales"]),
            "first_sale": None if pd.isna(r["first_sale_month"]) else r["first_sale_month"],
            "last_sale": None if pd.isna(r["last_sale_month"]) else r["last_sale_month"],
            "actuals": actuals,
            "split": None, "holdout": None, "future": None, "metrics": None,
        }
        bt = rolling_backtest(s) if r["status"] == "ok" else None
        if bt is not None:
            first_origin = bt["months"][0]
            rec["split"] = {
                "train_end": nextmonth(pd.Timestamp(first_origin + "-01"), -1),
                "holdout_start": first_origin,
                "train_months": bt["train_months_at_first_origin"],
                "holdout_months": len(bt["months"]),
                "mode": "rolling",
            }
            rec["holdout"] = {k: bt[k] for k in ("months", "actual", *METHODS)}
            f3 = future_path(s, 3)                      # one fit covers both future and future3
            rec["future"] = {"month": f3["months"][0], **{m: f3[m][0] for m in METHODS}}
            rec["future3"] = f3
            rec["metrics"] = bt["metrics"]

            # ---- "+ synthetic" variant: same rolling backtest, but each
            # origin's TRAINING gets the synthetic 2021-22 months prepended.
            # Test origins stay real. Diagnostic only.
            #
            # Only offered for SKUs whose REAL sales already started at (or
            # right at the open of) the real data window, 2023-01 -
            # NEW_PRODUCT_CUTOFF. For those, the product plausibly existed
            # before 2023 and its real history is simply cut off by where
            # the dataset starts, so prepending synthetic pre-2023 months
            # is a defensible "what if we had more real history" question.
            # For a SKU whose first real sale is well AFTER the window
            # opened (a genuine 2024/2025 launch), prepending 2021-22
            # "sales" would fabricate demand before the product existed -
            # nonsensical, so synthetic is not computed for it at all.
            is_new_product = bool(rec["first_sale"]) and rec["first_sale"] > NEW_PRODUCT_CUTOFF
            s_all = series_of(pk, raw_all)
            prefix = s_all[s_all.index < s.index.min()]
            bts = rolling_backtest(s, prefix=prefix) if (len(prefix) and not is_new_product) else None
            if is_new_product:
                rec["synthetic_blocked_reason"] = (
                    f"first real sale {rec['first_sale']} — a real launch well after the "
                    f"2023-01 data window opened. Prepending 2021-22 history would fabricate "
                    f"sales before the product existed."
                )
            if bts is not None:
                nz_all = s_all[s_all > 0]
                rec["synthetic"] = {
                    "first_sale": nz_all.index.min().strftime("%Y-%m") if len(nz_all) else None,
                    "last_sale": nz_all.index.max().strftime("%Y-%m") if len(nz_all) else None,
                    "months_span": int(len(s_all)),
                    "months_with_sales": int(len(nz_all)),
                    "actuals": [{"m": ts.strftime("%Y-%m"), "q": round(float(v), 2)}
                                for ts, v in s_all.items()],
                    "split": {
                        "train_end": nextmonth(pd.Timestamp(bts["months"][0] + "-01"), -1),
                        "holdout_start": bts["months"][0],
                        "train_months": bts["train_months_at_first_origin"],
                        "holdout_months": len(bts["months"]),
                        "synthetic_months": int(len(prefix)),
                        "mode": "rolling",
                    },
                    "holdout": {k: bts[k] for k in ("months", "actual", *METHODS)},
                    "metrics": bts["metrics"],
                }
                sf3 = future_path(s_all, 3)
                rec["synthetic"]["future3"] = sf3
                rec["synthetic"]["future"] = {"month": sf3["months"][0], **{m: sf3[m][0] for m in METHODS}}
        else:
            # insufficient_data, OR status='ok' but too few months (< 15)
            # for a 6-origin rolling backtest — shown as insufficient
            # (actuals + a provisional trailing average, no scored forecast).
            rec["status"] = "insufficient_data"
            obs = [a["q"] for a in actuals if a["q"] > 0]
            rec["future"] = {
                "month": nextmonth(s.index.max()) if len(s) else None,
                "provisional": round(float(np.mean(obs)), 2) if obs else 0.0,
            }
        skus.append(rec)

    payload = {
        "generated": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "abc_period": ABC_PERIOD, "verdict": "ma3",
        "params": {"backtest": "rolling-origin, 1-step-ahead, last 6 real months, refit each origin",
                   "test_months": TEST_H, "min_train": MIN_TRAIN,
                   "ma_window": MA_WINDOW, "sba_alpha": SBA_ALPHA, "min_months": MIN_MONTHS_WITH_SALES},
        "summary": {"total": len(skus),
                    "ok": sum(1 for r in skus if r["status"] == "ok"),
                    "insufficient_data": sum(1 for r in skus if r["status"] == "insufficient_data"),
                    "with_synthetic": sum(1 for r in skus if r.get("synthetic")),
                    "new_products_synthetic_blocked": sum(1 for r in skus if r.get("synthetic_blocked_reason"))},
        "skus": skus,
    }
    data_str = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    if "</script" in data_str.lower():
        sys.exit("payload contains a </script> sequence — cannot inline safely")

    with open(os.path.join(HERE, "viz_data.json"), "w", encoding="utf-8") as fh:
        fh.write(data_str)

    template = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    if "__VIZ_DATA__" not in template:
        sys.exit("template.html is missing the __VIZ_DATA__ placeholder")
    with open(os.path.join(HERE, "forecast_viewer.html"), "w", encoding="utf-8") as fh:
        fh.write(template.replace("__VIZ_DATA__", data_str))

    print(f"wrote viz_data.json + forecast_viewer.html — {len(skus)} SKUs "
          f"({payload['summary']['ok']} ok, {payload['summary']['insufficient_data']} insufficient)")


if __name__ == "__main__":
    main()
