"""
tools/bakeoff_viewer/build.py — regenerate the Model Bake-off Viewer.

A self-contained HTML page that visualises the forecasting model bake-off
(scripts/model_bakeoff.py, arima_bakeoff.py, xgboost_bakeoff.py), with a
toggle between REAL data only and REAL + SYNTHETIC.

No DB access — reads the frozen bake-off CSVs in reports/. Run the three
bake-off scripts first (both with and without --with-synthetic) so all
six CSVs exist.

Usage (from the repo root):
    python tools/bakeoff_viewer/build.py
"""
from __future__ import annotations

import json
import os
import sys


import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
R = os.path.join(REPO, "reports")

# model key -> display name, in the order to show
MODELS = [
    ("naive", "Naive"), ("snaive12", "Seasonal naive"), ("mean", "Mean"), ("drift", "Drift"),
    ("ma3", "MA3"), ("ma6", "MA6"),
    ("croston", "Croston"), ("sba", "SBA α=.1"), ("sba_a3", "SBA α=.3"), ("tsb", "TSB"),
    ("ses", "SES"), ("holt", "Holt"), ("holt_damped", "Holt damped"),
    ("hw_add12", "Holt-Winters"), ("theta", "Theta"),
    ("sarima_plain", "ARIMA(1,1,1)"), ("sarima_seasonal", "SARIMA seasonal"),
    ("arima_auto", "Auto-ARIMA"), ("xgboost", "XGBoost"),
]
THRESHOLDS = {"mape": 0.20, "mase": 1.00, "smape": None}


def _num(v):
    v = pd.to_numeric(pd.Series([v]), errors="coerce").iloc[0]
    return None if pd.isna(v) else round(float(v), 4)


def _load(path):
    return pd.read_csv(path) if os.path.exists(path) else None


def build_dataset(mb_csv, mb_query, arima_csv, xgb_csv):
    """Merge the three bake-off CSVs for one variant (real or synth) into
    a per-SKU record list."""
    mb = _load(os.path.join(R, mb_csv))
    if mb is None:
        sys.exit(f"missing {mb_csv} — run scripts/model_bakeoff.py first")
    if mb_query:
        mb = mb.query(mb_query).copy()
    ar = _load(os.path.join(R, arima_csv))
    xg = _load(os.path.join(R, xgb_csv))

    key = "product_key" if "product_key" in mb.columns else "pk"
    names = {}
    for df, k in ((mb, key), (ar, "pk"), (xg, "pk")):
        if df is None:
            continue
        for _, r in df.iterrows():
            pk = r.get(k)
            sc = r.get("sku_code") if "sku_code" in df.columns else r.get("sku")
            nm = r.get("product_name") if "product_name" in df.columns else r.get("name")
            if pk is None or (pd.isna(sc) and pd.isna(nm)):
                continue
            have = names.get(pk)
            if have is None or (have[1] in (None, "") and nm not in (None, "")):
                names[pk] = (None if pd.isna(sc) else sc, None if pd.isna(nm) else nm)

    ar_by = {r["pk"]: r for _, r in ar.iterrows()} if ar is not None else {}
    xg_by = {r["pk"]: r for _, r in xg.iterrows()} if xg is not None else {}

    skus = []
    for _, r in mb.iterrows():
        pk = r[key]
        rec = {"pk": int(pk),
               "sku": (names.get(pk, (None, None))[0] or str(pk)),
               "name": (names.get(pk, (None, None))[1] or ""),
               "months": int(r["months"]), "nz": int(r["nonzero"]), "m": {}}
        for mk, _lbl in MODELS:
            src = r
            if mk == "arima_auto":
                src = ar_by.get(pk)
                mk_cols = "arima_auto"
            elif mk == "xgboost":
                src = xg_by.get(pk)
                mk_cols = "xgboost"
            else:
                mk_cols = mk
            if src is None:
                continue
            trip = {met: _num(src.get(f"{mk_cols}_{met}")) for met in ("mape", "mase", "smape")}
            if any(v is not None for v in trip.values()):
                rec["m"][mk] = trip
        skus.append(rec)
    return {"n": len(skus), "n_scored": sum(1 for s in skus if s["m"]), "skus": skus}


def main():
    real = build_dataset(
        "model_bakeoff_unilever.csv", "cohort == 'tierA_2026_02'",
        "arima_bakeoff_unilever_tierA.csv", "xgboost_bakeoff_unilever_tierA.csv")
    synth = build_dataset(
        "model_bakeoff_unilever_tierA_withsynth.csv", None,
        "arima_bakeoff_unilever_tierA_withsynth.csv", "xgboost_bakeoff_unilever_tierA_withsynth.csv")

    payload = {
        "generated": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "cohort": "Unilever Tier A — ABC 2026-02",
        "backtest": "rolling-origin, 1-step-ahead, last 6 real months (2025-09 .. 2026-02)",
        "models": [{"key": k, "label": v} for k, v in MODELS],
        "thresholds": THRESHOLDS,
        "datasets": {
            "real": {"label": "Real data only (2023-01 .. 2026-02)", **real},
            "synth": {"label": "Real + synthetic 2021-22 prepended (diagnostic)", **synth},
        },
    }
    data_str = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    if "</script" in data_str.lower():
        sys.exit("payload contains </script> — cannot inline safely")

    with open(os.path.join(HERE, "viz_data.json"), "w", encoding="utf-8") as fh:
        fh.write(data_str)
    tmpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    if "__VIZ_DATA__" not in tmpl:
        sys.exit("template.html missing __VIZ_DATA__ placeholder")
    with open(os.path.join(HERE, "bakeoff_viewer.html"), "w", encoding="utf-8") as fh:
        fh.write(tmpl.replace("__VIZ_DATA__", data_str))

    print(f"wrote viz_data.json + bakeoff_viewer.html  "
          f"(real: {real['n_scored']} scored SKUs, synth: {synth['n_scored']})")


if __name__ == "__main__":
    main()
