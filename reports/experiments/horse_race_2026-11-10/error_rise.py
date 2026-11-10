"""
reports/experiments/horse_race_2026-11-10/error_rise.py - what raised the served forecast's MAPE and MASE in
Sep 2025 - Feb 2026 against Mar - Aug 2025 (2026-11-10). Backtest attribution only; throwaway copy only; writes a JSON.

Reads local/horse_race_rows_2026-11-10.csv (run_horse_race.py's per product-month rows: served, served_nocal, actual)
and the demand series from ssm_challenger for the MASE scale.

Metrics (served forecast):
  MAPE        median over products of each product's mean |f - a| / a, months with a > 0
  MASE        median over products of mean |f - a| / scale; ONE scale per product for both windows: its mean
              |y_t - y_t-1| over its history before 2025-03, so a change is a change in error, not in the scale
  pooled WAPE sum |f - a| / sum |a|
Each cause is switched off on its own, then together:
  calendar off   the served value before the calendar factor
  no December    December removed from the window
  level known    each forecast multiplied by that month's sum(actual) / sum(forecast) over all products: the company-wide
                 miss removed, each product's own miss kept. NOT a forecast (it reads the month's actual); attribution only
  same products  only products scored in both windows (composition)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from analytics.forecasting.diagnostic_metrics import mape as mape_fn, naive_scale  # noqa: E402
from analytics.forecasting.global_model import from_first_sale  # noqa: E402
from scripts.run_baseline_forecast import build_series, fetch_demand  # noqa: E402

P1, P2 = ("2025-03", "2025-08"), ("2025-09", "2026-02")
SCALE_BEFORE = pd.Timestamp("2025-03-01")


def main() -> int:
    u = os.environ["SUPABASE_DB_URL"]
    assert "127.0.0.1:55432" in u, "throwaway copy only"
    conn = psycopg2.connect(u)
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    demand = fetch_demand(cur)
    conn.rollback()
    latest = demand.calendar_month.max()
    series = {int(k): build_series(g, latest) for k, g in demand.groupby("product_key")}
    df = pd.read_csv(REPO / "local" / "horse_race_rows_2026-11-10.csv")[["product_key", "month", "actual", "served", "served_nocal"]]
    df = df.dropna(subset=["actual"])
    scale = {}
    for k in df.product_key.unique():
        h = series[k][series[k].index < SCALE_BEFORE].dropna()
        h = from_first_sale(h) if len(from_first_sale(h)) else h
        scale[k] = naive_scale(h.to_numpy(float)) if len(h) >= 2 else np.nan

    def metrics(d: pd.DataFrame, col: str) -> dict:
        g = d.groupby("product_key")
        mp = g.apply(lambda x: mape_fn(x.actual.to_numpy(), x[col].to_numpy()), include_groups=False).dropna()
        ms = g.apply(lambda x: np.abs(x[col] - x.actual).mean() / scale[x.name] if scale.get(x.name, 0) > 0 else np.nan,
                     include_groups=False).dropna()
        return {"MAPE": round(float(mp.median()), 4), "MASE": round(float(ms.median()), 4),
                "pooled_WAPE": round(float(np.abs(d[col] - d.actual).sum() / d.actual.abs().sum()), 4),
                "bias": round(float((d[col] - d.actual).sum() / d.actual.abs().sum()), 4),
                "products": int(d.product_key.nunique()), "product_months": int(len(d))}

    def level_known(d: pd.DataFrame, col: str) -> pd.Series:
        r = d.groupby("month").apply(lambda x: x.actual.sum() / x[col].sum() if x[col].sum() > 0 else 1.0, include_groups=False)
        return d[col] * d.month.map(r)

    w = lambda a, b: df[(df.month >= a) & (df.month <= b)].copy()  # noqa: E731
    d1, d2 = w(*P1), w(*P2)
    both = set(d1.product_key) & set(d2.product_key)
    out = {"scale": "per product, mean |y_t - y_t-1| before 2025-03, same for both windows", "rows": {}}
    for name, d in (("Mar-Aug 2025", d1), ("Sep 2025-Feb 2026", d2)):
        d = d.assign(level=level_known(d, "served"), level_nocal=level_known(d, "served_nocal"))
        nodec = d[~d.month.str.endswith("-12")]
        nodec = nodec.assign(level=level_known(nodec, "served"))
        same = d[d.product_key.isin(both)]
        out["rows"][name] = {
            "served (as live)": metrics(d, "served"),
            "calendar off": metrics(d, "served_nocal"),
            "no December": metrics(nodec, "served"),
            "level known (company-wide miss removed)": metrics(d, "level"),
            "level known, calendar off": metrics(d, "level_nocal"),
            "no December, level known": metrics(nodec, "level"),
            "same products in both windows": metrics(same, "served"),
        }
    # Month by month, served as live, all frame months.
    monthly = {}
    for m, g in df.groupby("month"):
        e = (g.served - g.actual).abs()
        pos = g[g.actual > 0]
        monthly[m] = {"MAPE_month": round(float(((pos.served - pos.actual).abs() / pos.actual).median()), 4),
                      "MASE_month": round(float((e / g.product_key.map(scale)).replace([np.inf], np.nan).dropna().median()), 4),
                      "pooled_WAPE": round(float(e.sum() / g.actual.abs().sum()), 4),
                      "bias": round(float((g.served - g.actual).sum() / g.actual.abs().sum()), 4), "products": int(len(g))}
    out["monthly"] = monthly
    # Volume: product-months by the product's actual-volume quartile in Sep-Feb, share of the APE and of the scaled error.
    d2 = d2.assign(ape=np.where(d2.actual > 0, (d2.served - d2.actual).abs() / d2.actual, np.nan))
    vol = d2.groupby("product_key").actual.mean()
    q = pd.qcut(vol, 4, labels=["Q1 lowest", "Q2", "Q3", "Q4 highest"])
    d2["quartile"] = d2.product_key.map(q)
    out["Sep-Feb by volume quartile"] = {str(k): {"median APE": round(float(g.ape.median()), 4),
                                                  "share of abs miss (pieces)": round(float((g.served - g.actual).abs().sum()
                                                                                            / (d2.served - d2.actual).abs().sum()), 4),
                                                  "bias": round(float((g.served - g.actual).sum() / g.actual.sum()), 4)}
                                         for k, g in d2.groupby("quartile", observed=True)}
    path = Path(__file__).resolve().parent / "results_error_rise.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
