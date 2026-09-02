"""
tools/forecast_viewer/build.py — regenerate the Tier A Forecast Viewer.

Read-only against the DB. Produces two files next to this script:
  viz_data.json        — the data payload (actuals + recomputed forecasts + metrics)
  forecast_viewer.html — template.html with viz_data.json inlined; self-contained,
                         open it by double-clicking, no server needed.

Data sources:
  - actuals:  Unilever_SKU_Demand_Fact_Real (the _Real view; demo rows excluded)
  - forecasts: recomputed here exactly as analytics/forecasting/baseline.py does
               (same 80/20 split, same MA3/Naive/SBA, same one-step-ahead)
  - metrics:  reports/baseline_forecast_per_sku.csv (produced by
              scripts/run_baseline_forecast.py — run that first)

Usage (from the repo root, with .env holding SUPABASE_DB_URL):
    python tools/forecast_viewer/build.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)

from analytics.forecasting.sarima import train_holdout_split, HOLDOUT_FRACTION
from analytics.forecasting.baseline import (
    naive_forecast, moving_average_forecast, sba_forecast,
    MA_WINDOW, SBA_ALPHA, MIN_MONTHS_WITH_SALES,
)

CSV_PATH = os.path.join(REPO, "reports", "baseline_forecast_per_sku.csv")
ABC_PERIOD = "2026-02"  # the real ABC period run_baseline_forecast.py resolves to


def f4(v):
    v = pd.to_numeric(pd.Series([v]), errors="coerce").iloc[0]
    return None if pd.isna(v) else round(float(v), 4)


def series_of(pk, raw):
    d = raw.get(pk, {})
    s = pd.Series({pd.Timestamp(m + "-01"): d[m] for m in d}, dtype="object").sort_index()
    s = pd.to_numeric(s, errors="coerce").fillna(0.0)
    return s.resample("MS").asfreq().fillna(0.0)


def nextmonth(ts):
    return (ts + pd.offsets.MonthBegin(1)).strftime("%Y-%m")


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
        if r["status"] == "ok":
            train, holdout = train_holdout_split(s, holdout_fraction=HOLDOUT_FRACTION)
            rec["split"] = {
                "train_end": train.index.max().strftime("%Y-%m"),
                "holdout_start": holdout.index.min().strftime("%Y-%m"),
                "train_months": int(len(train)), "holdout_months": int(len(holdout)),
            }
            fc = {
                "naive": naive_forecast(train, len(holdout)),
                "ma3": moving_average_forecast(train, len(holdout), MA_WINDOW),
                "sba": sba_forecast(train, len(holdout), SBA_ALPHA),
            }
            rec["holdout"] = {
                "months": [ts.strftime("%Y-%m") for ts in holdout.index],
                "actual": [round(float(v), 2) for v in holdout.values],
                **{k: [round(float(x), 2) for x in v] for k, v in fc.items()},
            }
            rec["future"] = {
                "month": nextmonth(s.index.max()),
                "naive": round(float(naive_forecast(s, 1)[0]), 2),
                "ma3": round(float(moving_average_forecast(s, 1, MA_WINDOW)[0]), 2),
                "sba": round(float(sba_forecast(s, 1, SBA_ALPHA)[0]), 2),
            }
            rec["metrics"] = {
                m: {"mase": f4(r[f"{m}_mase"]), "mape": f4(r[f"{m}_mape"]),
                    "mae": f4(r[f"{m}_mae"]), "rmse": f4(r[f"{m}_rmse"])}
                for m in ("naive", "ma3", "sba")
            }

            # ---- "+ synthetic" variant: synthetic 2021-22 prepended to
            # training, SAME holdout months so the two views are directly
            # comparable. Diagnostic only.
            s_all = series_of(pk, raw_all)
            ho_months = rec["holdout"]["months"]
            ho_start_ts = pd.Timestamp(ho_months[0] + "-01")
            train_all = s_all[s_all.index < ho_start_ts]
            ho_all = s_all[s_all.index.isin([pd.Timestamp(m + "-01") for m in ho_months])]
            has_synth = len(train_all) > len(train) and len(ho_all) == len(ho_months)
            if has_synth:
                fca = {
                    "naive": naive_forecast(train_all, len(ho_all)),
                    "ma3": moving_average_forecast(train_all, len(ho_all), MA_WINDOW),
                    "sba": sba_forecast(train_all, len(ho_all), SBA_ALPHA),
                }
                nz_all = s_all[s_all > 0]
                rec["synthetic"] = {
                    "first_sale": nz_all.index.min().strftime("%Y-%m") if len(nz_all) else None,
                    "last_sale": nz_all.index.max().strftime("%Y-%m") if len(nz_all) else None,
                    "months_span": int(len(s_all)),
                    "months_with_sales": int(len(nz_all)),
                    "actuals": [{"m": ts.strftime("%Y-%m"), "q": round(float(v), 2)}
                                for ts, v in s_all.items()],
                    "split": {
                        "train_end": train_all.index.max().strftime("%Y-%m"),
                        "holdout_start": ho_months[0],
                        "train_months": int(len(train_all)),
                        "holdout_months": int(len(ho_all)),
                        "synthetic_months": int(len(train_all) - len(train)),
                    },
                    "holdout": {
                        "months": ho_months,
                        "actual": [round(float(v), 2) for v in ho_all.values],
                        **{k: [round(float(x), 2) for x in v] for k, v in fca.items()},
                    },
                    "future": {
                        "month": nextmonth(s_all.index.max()),
                        "naive": round(float(naive_forecast(s_all, 1)[0]), 2),
                        "ma3": round(float(moving_average_forecast(s_all, 1, MA_WINDOW)[0]), 2),
                        "sba": round(float(sba_forecast(s_all, 1, SBA_ALPHA)[0]), 2),
                    },
                    "metrics": {
                        m: _score(fca[m], ho_all.values, train_all.values)
                        for m in ("naive", "ma3", "sba")
                    },
                }
        elif r["status"] == "insufficient_data":
            obs = [a["q"] for a in actuals if a["q"] > 0]
            rec["future"] = {
                "month": nextmonth(s.index.max()) if len(s) else None,
                "provisional": round(float(np.mean(obs)), 2) if obs else 0.0,
            }
        skus.append(rec)

    payload = {
        "generated": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "abc_period": ABC_PERIOD, "verdict": "ma3",
        "params": {"holdout_fraction": HOLDOUT_FRACTION, "ma_window": MA_WINDOW,
                   "sba_alpha": SBA_ALPHA, "min_months": MIN_MONTHS_WITH_SALES},
        "summary": {"total": len(skus),
                    "ok": sum(1 for r in skus if r["status"] == "ok"),
                    "insufficient_data": sum(1 for r in skus if r["status"] == "insufficient_data"),
                    "with_synthetic": sum(1 for r in skus if r.get("synthetic"))},
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
