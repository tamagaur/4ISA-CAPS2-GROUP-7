"""
Fit diagnosis 2026-10-07 - Unilever Tier A on the current basis (analytics.params.abc_method('unilever'),
't12m_new', ABC period 2026-02), REAL data only. Read-only: one READ ONLY transaction, rolled back.

Reuses the 2026-10 harness (reproduces the live router and checks it against public.forecast_result at
2026-03-01 before scoring; any mismatch stops the run). Only the Tier A query differs: it reads the basis
through abc_method() instead of the literal 'single'.

    .venv/Scripts/python.exe reports/diagnostics/fit_diagnosis_2026-10-07/run_fit_diagnosis_2026-10-07.py
"""
from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)

from analytics.params import abc_method  # noqa: E402
from scripts.run_baseline_forecast import fetch_demand  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "fd", os.path.join(REPO, "reports", "diagnostics", "fit_diagnosis_2026-10", "run_fit_diagnosis.py"))
fd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fd)

BASIS = abc_method("unilever")

# The 2026-10 harness predates the blank-quantity rule (DEC-31, 2026-10-05). Two live behaviours are mirrored
# here so the live reproduction check can pass (scripts/run_baseline_forecast.py:205, :412-417, :950):
#  1. a missing (blank-quantity) month never makes a product dead_sku;
#  2. the MASE scale is the lag-1 naive error of the training months with missing months dropped.
from scripts.run_baseline_forecast import _missing_in_last_months  # noqa: E402
from analytics.forecasting.global_model import missing_months  # noqa: E402
from analytics.classification.fsn import no_sale_in_last_months  # noqa: E402
from analytics.params import DEAD_SKU_MONTHS  # noqa: E402

_orig_naive_scale = fd.naive_scale
fd.naive_scale = lambda x: _orig_naive_scale(np.asarray(x, dtype=float)[~np.isnan(np.asarray(x, dtype=float))])


def load(cur):
    inp = fd.load_inputs(cur)   # live rows; tier_a and demand replaced below with the current code paths
    inp["demand"] = fetch_demand(cur)   # live loader: blank quantity = missing month (DEC-31), not 0
    cur.execute("""
        SELECT abc.product_key, pd.sku_code, pd.product_name
        FROM abc_classification abc JOIN product_dimension pd ON pd.product_key = abc.product_key
        WHERE abc.principal = 'unilever' AND abc.method = %s
          AND abc.classification_period = %s AND abc.tier = 'A'
        ORDER BY abc.product_key""", (BASIS, fd.ABC_PERIOD))
    inp["tier_a"] = pd.DataFrame(cur.fetchall(), columns=["product_key", "sku_code", "product_name"])
    return inp


def lean(r):
    if not r.bias_tested:
        return "not testable (<6 holdout months)"
    if r.t_stat >= fd.BIAS_T:
        return "high"
    if r.t_stat <= -fd.BIAS_T:
        return "low"
    return "neutral"


def main():
    inp = fd.cached_inputs(None, load)
    keys = [int(k) for k in inp["tier_a"]["product_key"]]
    print(f"basis {BASIS}, ABC {fd.ABC_PERIOD}: {len(keys)} Tier A SKUs; live rows {len(inp['live'])}")
    recs, series, fc = fd.run_cohort(inp["demand"], keys)
    latest = inp["demand"]["calendar_month"].max()
    for k, r in recs.items():      # live dead rule (run_baseline_forecast.py:412-417), blank months included
        s_ = series.get(k)
        if (s_ is not None and r["status"] == "ok" and len(s_) >= DEAD_SKU_MONTHS
                and no_sale_in_last_months(s_.index.strftime("%Y-%m"), s_.to_numpy(), latest)
                and not _missing_in_last_months(missing_months(s_), latest)):
            recs[k] = {**r, "status": "dead_sku", "bin": None, "method": "zero_no_order", "forecast": 0.0,
                       "mase_pipeline": None}
    bad = fd.check_against_live(recs, inp["live"])
    if bad:
        for b in bad[:20]:
            print("MISMATCH", b)
        sys.exit("STOP: does not reproduce live forecast_result")
    print("reproduction vs live forecast_result: all rows match")
    hold = fd.verdict_holdouts(recs, series)
    scored = fd.score_holdouts(recs, series, fc, hold)
    df = fd.diagnose(recs, series, fc, hold, scored, inp["tier_a"])
    df["bias_lean"] = df.apply(lean, axis=1)
    df["mean_error_sign"] = np.sign(df["mean_error"]).map({1.0: "high", -1.0: "low", 0.0: "zero"})
    cls = fd.classify(df)
    cls["bias_lean"] = df["bias_lean"].values
    cls["mean_error"] = df["mean_error"].values
    cls["pooled_bias_pct"] = (df["sum_forecast_minus_actual"] / df["sum_actual"].replace(0, np.nan)).values
    df.to_csv(os.path.join(HERE, "per_sku.csv"), index=False)
    cls.to_csv(os.path.join(HERE, "classified.csv"), index=False)

    def agg(by):
        rows = []
        for key, g in df.groupby(by):
            key = key if isinstance(key, tuple) else (key,)
            t = g[g.bias_tested]
            rows.append({**dict(zip(by, key)), "n_skus": len(g), "n_bias_tested": len(t),
                         "lean_high": int((t.bias_lean == "high").sum()),
                         "lean_low": int((t.bias_lean == "low").sum()),
                         "neutral": int((t.bias_lean == "neutral").sum()),
                         "not_testable": int((~g.bias_tested).sum()),
                         "mean_error_positive": int((g.mean_error > 0).sum()),
                         "mean_error_negative": int((g.mean_error < 0).sum()),
                         "pooled_bias_pct": g.sum_forecast_minus_actual.sum() / g.sum_actual.sum(),
                         "overfit": int((g.overfit_status == "overfit").sum()),
                         "underfit": int(g.underfit.sum())})
        return pd.DataFrame(rows)
    a_bin, a_model, a_both = agg(["bin"]), agg(["served_model"]), agg(["bin", "served_model"])
    a_bin.to_csv(os.path.join(HERE, "aggregate_by_bin.csv"), index=False)
    a_model.to_csv(os.path.join(HERE, "aggregate_by_model.csv"), index=False)
    a_both.to_csv(os.path.join(HERE, "aggregate_by_bin_and_model.csv"), index=False)
    pd.set_option("display.width", 250)
    print(f"scored {len(df)}; verdict_source {df.verdict_source.value_counts().to_dict()}; "
          f"overfit_status {df.overfit_status.value_counts().to_dict()}; ma3 p95 {df.ma3_p95_ratio.iloc[0]:.3f}")
    print(f"underfit {int(df.underfit.sum())}; bias lean {df.bias_lean.value_counts().to_dict()}")
    for a in (a_bin, a_model, a_both):
        print(a.to_string(index=False, float_format=lambda v: f"{v:.4f}"))


if __name__ == "__main__":
    main()
