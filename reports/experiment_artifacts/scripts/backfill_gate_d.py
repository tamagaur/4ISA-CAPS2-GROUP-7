"""Backfill the gate_d_bakeoff rows of reports/experiment_log.csv from the Gate D session artifacts
(session f63476c9 scratchpad, 2026-09-20). Values computed from the CSVs; nothing typed in. No DB access."""
import datetime, os, re, shutil, sys
import numpy as np, pandas as pd

G, REPO = sys.argv[1], r"C:\Users\kyuan\Capstone-Project"
ART, REL = os.path.join(REPO, "reports", "experiment_artifacts"), "reports/experiment_artifacts/"
LOG = os.path.join(REPO, "reports", "experiment_log.csv")
SEED, NBOOT, MIN_N = 20260921, 1000, 5


def compare(m, b, mase):
    m, b, mase = (np.asarray(v, float) for v in (m, b, mase)); ok = np.isfinite(m) & np.isfinite(b); m, b, ms = m[ok], b[ok], mase[ok]
    if len(m) < MIN_N: return dict(n_skus=len(m), verdict="not_testable")
    i = np.random.default_rng(SEED).integers(0, len(m), (NBOOT, len(m))); d = np.median(m[i], axis=1) - np.median(b[i], axis=1); lo, hi = np.percentile(d, [2.5, 97.5])
    ms = ms[np.isfinite(ms)]
    return dict(n_skus=len(m), model_value=round(float(np.median(m)), 4), baseline_value=round(float(np.median(b)), 4), diff_ci_lo=round(float(lo), 4),
                diff_ci_hi=round(float(hi), 4), n_better=int((m < b - 1e-12).sum()), n_worse=int((m > b + 1e-12).sum()),
                mase_pass_pct=round(100 * float((ms < 1).mean()), 1) if len(ms) else None, verdict="win" if hi < 0 else "loss" if lo > 0 else "tie",
                ci_level=0.95, n_boot=NBOOT, seed=SEED)


SRC = {"mb": ("scripts/model_bakeoff.py", "17-model bake-off"), "ar": ("scripts/arima_bakeoff.py", "auto-ARIMA bake-off"), "xg": ("scripts/xgboost_bakeoff.py", "global XGBoost bake-off (trained across Tier A)")}
rows = []
for key, (script, what) in SRC.items():
    for arm in ("real", "syn"):
        fn = f"{key}_{arm}.csv"; src = os.path.join(G, fn); dst = f"gate_d_{fn}"; shutil.copyfile(src, os.path.join(ART, dst)); d = pd.read_csv(src)
        models = sorted({re.sub(r"_wape$", "", c) for c in d.columns if c.endswith("_wape")} - {"ma3"})
        for m in models:
            rows.append(dict(run_id="gate_d_bakeoff", run_date=datetime.date.fromtimestamp(os.path.getmtime(src)).isoformat(), source_script=script,
                             cohort="Unilever Tier A", abc_period="2026-02", data_arm="real" if arm == "real" else "synthetic 2021-22 months prepended as TRAINING context only",
                             train_pool="global across Tier A SKUs" if m == "xgboost" else "per-SKU",
                             split_protocol="rolling-origin 1-step over the last real months (script defaults: 6 test months, 12 min train); the run's flags are not recorded in the artifact",
                             window_end="2026-02", bin="ALL", model=m, baseline_model="ma3", metric="median_wape", reportable="yes" if arm == "real" else "no", status="diagnostic",
                             notes=f"Gate D {what}; artifact predates the months_train label fix (per Yuan); workbook view: {REL}gate_d_model_bakeoff_unilever_tierA.xlsx",
                             artifact_path=REL + dst, **compare(d[f"{m}_wape"], d["ma3_wape"], d[f"{m}_mase"])))
shutil.copyfile(os.path.join(G, "xlsx", "model_bakeoff_unilever_tierA.xlsx"), os.path.join(ART, "gate_d_model_bakeoff_unilever_tierA.xlsx"))
L = pd.read_csv(LOG); before = len(L); L = L[L.run_id != "gate_d_bakeoff"]
N = pd.DataFrame(rows).reindex(columns=L.columns); out = pd.concat([L, N], ignore_index=True)
scored = ~N.verdict.isin(["not_testable"]); assert not N.loc[scored, ["model_value", "baseline_value", "diff_ci_lo", "diff_ci_hi"]].isna().any().any()
assert not np.isinf(N[["model_value", "baseline_value"]].astype(float)).any().any()
out.to_csv(LOG, index=False)
print(f"log rows {before} -> {len(out)} | gate_d rows {len(N)} | artifact_missing now {int((out.status == 'artifact_missing').sum())} | NaN mase_pass in gate_d: {int(N.mase_pass_pct.isna().sum())}")
print(N.verdict.value_counts().to_dict()); print(N.groupby(["data_arm"]).size().to_dict())
show = ["artifact_path", "model", "n_skus", "model_value", "baseline_value", "n_better", "n_worse", "diff_ci_lo", "diff_ci_hi", "verdict"]
print(N[N.verdict.isin(["win"]) | N.model.isin(["xgboost", "arima_auto", "tsb", "sba_a3"])].assign(artifact_path=lambda x: x.artifact_path.str.replace(REL + "gate_d_", "")).loc[:, show].to_string(index=False))
