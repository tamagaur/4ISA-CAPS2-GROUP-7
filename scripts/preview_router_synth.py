"""
scripts/preview_router_synth.py - WHAT-IF preview of the live router on a
series file that may carry placeholder (is_demo) months. Files only: no DB
access, nothing written anywhere but --out.

This is the one caller allowed to pass allow_placeholder=True (see
analytics.forecasting.global_model.assert_real_history). Its output is a
preview for the TA walkthrough, never a forecast: it does not feed
Forecast_Result, and a placeholder month is not demand.

Mirrors scripts/run_baseline_forecast.py's --write path per SKU:
  - series = the SKU's rows zero-filled from its first to its last month (build_series);
  - status: < MIN_MONTHS_WITH_SALES months with a sale -> insufficient_data (trailing average
    of the observed positive months, not routed); 6+ months and the last 6 sum <= 0 -> dead_sku (0);
    otherwise ok -> router.route() for --target, with the training pool = every SKU in the file;
  - holdout = train_holdout_split's months, scored rolling one-step with the served bin held fixed;
    holdout MASE is scaled by the naive error of the REAL training months only (placeholder months
    never set the scale; the rule the preview comparisons use).
With --real-only the placeholder rows are dropped first, which reproduces the live runner.

Input CSV columns: product_key, month (YYYY-MM), quantity, is_placeholder.

    python scripts/preview_router_synth.py --series series_synth.csv --target 2026-03 --out router_preview_synth.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics.forecasting.baseline import MIN_MONTHS_WITH_SALES
from analytics.forecasting.diagnostic_metrics import mape, mase, naive_scale, rmse, wape
from analytics.forecasting.global_model import GlobalForecaster, with_placeholder
from analytics.forecasting.router import rolling_one_step, route
from analytics.forecasting.split import train_holdout_split
from analytics.params import HOLDOUT_FRACTION

FIRST_REAL_ATTR = "first_real_month"   # series.attrs key: the SKU's first non-placeholder row


def load_series(path: str, real_only: bool) -> dict:
    rows = pd.read_csv(path, dtype={"month": str})
    rows["is_placeholder"] = rows["is_placeholder"].astype(str).str.lower().eq("true")
    if real_only:
        rows = rows[~rows["is_placeholder"]]
    out = {}
    for pk, g in rows.groupby("product_key"):
        s = pd.Series(g["quantity"].to_numpy(dtype=float), index=pd.to_datetime(g["month"] + "-01")).sort_index()
        s = s.resample("MS").asfreq().fillna(0.0)                       # same zero-fill as build_series
        s = with_placeholder(s, pd.to_datetime(g.loc[g["is_placeholder"], "month"] + "-01"))
        real_months = g.loc[~g["is_placeholder"], "month"]
        s.attrs[FIRST_REAL_ATTR] = pd.Timestamp(real_months.min() + "-01") if len(real_months) else None
        out[int(pk)] = s
    return out


def real_scale(train: pd.Series, series: pd.Series) -> float:
    """MASE's naive scale from the REAL training months only: a placeholder month
    never sets the yardstick a preview error is measured against. Same rule as
    tools/dsd_dev_viewer's preview. With no placeholder rows this is the whole
    training window, i.e. exactly what the live runner uses."""
    first_real = series.attrs.get(FIRST_REAL_ATTR)
    real_train = train if first_real is None else train[train.index >= first_real]
    return naive_scale(real_train.to_numpy(dtype=float))


def preview(series_by_key: dict, target: pd.Timestamp) -> pd.DataFrame:
    forecaster = GlobalForecaster(series_by_key, allow_placeholder=True)
    rows = []
    for pk, series in series_by_key.items():
        n_placeholder = int(series.index.isin(list(series.attrs.get("placeholder_months", ()))).sum())
        base = {"product_key": pk, "placeholder_months": n_placeholder, "bin": None, "served_model": None,
                "forecast": None, "ma3_forecast": None, "holdout_mase": None, "holdout_wape": None, "backup_fired": None,
                "ma3_holdout_mase": None, "ma3_holdout_wape": None,
                # Added 2026-09-24 for the app's preview mode (scripts/build_preview_outputs.py): the rest of
                # what the live runner stores per SKU, from the same route() result and holdout arrays.
                "holdout_mape": None, "holdout_rmse": None, "holdout_months": None, "sales_months": None,
                "backup_reason": None, "xgb_component": None, "tsb_component": None}
        if int((series > 0).sum()) < MIN_MONTHS_WITH_SALES:
            observed = series[series > 0]
            rows.append({**base, "status": "insufficient_data", "bin": "insufficient", "served_model": "trailing_average",
                         "forecast": max(0.0, float(observed.mean()) if len(observed) else 0.0)})
            continue
        if len(series) >= 6 and series.tail(6).sum() <= 0:
            rows.append({**base, "status": "dead_sku", "served_model": "zero_no_order", "forecast": 0.0})
            continue
        r = route(series, target, forecaster, allow_placeholder=True)
        train, holdout = train_holdout_split(series, holdout_fraction=HOLDOUT_FRACTION)
        scored = rolling_one_step(series, list(holdout.index), forecaster, force_bin=r["bin"], allow_placeholder=True)
        a, p, p3 = scored["actual"].to_numpy(), scored["value"].to_numpy(), scored["ma3"].to_numpy()
        scale = real_scale(train, series)
        rows.append({**base, "status": "ok", "bin": r["bin"], "served_model": r["method"], "forecast": r["value"],
                     "ma3_forecast": max(0.0, r["ma3_value"]), "holdout_mase": mase(a, p, scale),
                     "holdout_wape": wape(a, p), "backup_fired": r["backup_fired"],
                     # MA3, the benchmark, on the same holdout months and the same real-month scale
                     "ma3_holdout_mase": mase(a, p3, scale), "ma3_holdout_wape": wape(a, p3),
                     "holdout_mape": mape(a, p), "holdout_rmse": rmse(a, p), "holdout_months": len(a),
                     "sales_months": r["sales_months"], "backup_reason": r["backup_reason"],
                     "xgb_component": r["components"].get("xgb"), "tsb_component": r["components"].get("tsb")})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", required=True)
    ap.add_argument("--target", required=True, help="forecast month, YYYY-MM")
    ap.add_argument("--out", required=True)
    ap.add_argument("--real-only", action="store_true", help="drop placeholder rows first (reproduces the live runner)")
    args = ap.parse_args()
    df = preview(load_series(args.series, args.real_only), pd.Timestamp(args.target + "-01"))
    df.to_csv(args.out, index=False)
    print(f"{len(df)} SKUs -> {args.out} | status {df['status'].value_counts().to_dict()} | bin {df['bin'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
