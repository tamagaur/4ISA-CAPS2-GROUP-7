"""Step 3: assemble preds_plus (REAL) + preds_synth (SYNTH what-if), comb_inv_err, score every model x bin x arm
with the cells_all.py harness (two-condition test, seed 20260921, 1,000 resamples, bias rule, FIT/WEAK/OUT)."""
import json, time, warnings, importlib.util
import numpy as np, pandas as pd
warnings.simplefilter("ignore")
OFF = 24
spec = importlib.util.spec_from_file_location("r7", "run7.py"); r7 = importlib.util.module_from_spec(spec); spec.loader.exec_module(r7)
src = open("cells_all.py").read().split("rows = []")[0]
ns = {}; exec(src.replace('print(', '(lambda *a, **k: None)('), ns)        # cells / compare / bias / BLOCKS, verbatim
cells, compare, bias, BLOCKS = ns["cells"], ns["compare"], ns["bias"], ns["BLOCKS"]
RT = {}


def comb_inv_err(D, comps):
    """Weights = 1 / MAE of each component over this SKU's earlier scored months (all components present);
    none yet: equal weights. Any component missing now: no forecast."""
    out = np.full(len(D), np.nan)
    for pk, g in D.sort_values("g").groupby("pk"):
        P = g[comps].to_numpy(); a = g.actual.to_numpy(); fin = np.isfinite(P).all(axis=1); err = np.abs(P - a[:, None])
        for j, ix in enumerate(g.index):
            if not fin[j]: continue
            past = fin[:j]
            w = 1.0 / np.maximum(err[:j][past].mean(axis=0), 1e-9) if past.any() else np.ones(len(comps))
            out[D.index.get_loc(ix)] = float(P[j] @ w / w.sum())
    return out


# ---- REAL: corrected adida/imapa/otm/lgbm@A (clean series) + 7 new; chronos_bolt not run ----
A = pd.read_csv("preds_plus.csv.gz"); A["g"] = A.ti + OFF; S = pd.read_pickle("series_tierA.pkl"); n0, c0 = A.shape
for name in ("adida", "imapa", "otm"):
    A[name] = [max(0.0, v) if np.isfinite(v := r7.FN[name](S[r.pk][1][:r.ti - S[r.pk][0]])) else np.nan for r in A.itertuples()]
Lr, Vr = pd.read_csv("local_real.csv"), pd.read_csv("venv_real.csv")
A = A.drop(columns=["lgbm@A", "median3", "shrink_cat", "topdown_cat", "knn_analog", "lgbm_q50@A", "lgbm_tweedie@A", "comb_inv_err"],
           errors="ignore").merge(Lr[["pk", "g", "median3", "shrink_cat", "topdown_cat", "knn_analog"]], on=["pk", "g"]).merge(Vr, on=["pk", "g"])
t0 = time.time(); A["comb_inv_err"] = comb_inv_err(A, ["ma3", "ses", "xgb_abs@A", "lgbm@A"]); RT["real:comb_inv_err"] = time.time() - t0
A = A.drop(columns=["g"]); A.to_csv("preds_plus.csv.gz", index=False)
print(f"REAL preds_plus rows {n0}->{len(A)} cols {c0}->{A.shape[1]}")

# ---- SYNTH what-if ----
L = pd.read_csv("local_synth.csv").merge(pd.read_csv("venv_synth.csv"), on=["pk", "g"]).merge(pd.read_csv("ridge_synth.csv"), on=["pk", "g"])
SS = pd.read_pickle("series_synth.pkl")
def bin_of(tr):
    sales = int((tr > 0).sum())
    if sales < 3: return "insufficient"
    return "intermittent" if len(tr) / sales >= 1.32 else "short" if sales < 12 else "medium" if sales < 24 else "long"
L["bin_real"] = L.bin; L["bin"] = [bin_of(SS[r.pk][1][:r.g - SS[r.pk][0]]) for r in L.itertuples()]
L["ens_xgb_ma3@A"] = L[["xgb_abs@A", "ma3"]].mean(axis=1, skipna=False)
L["comb_simple"] = L[["ma4", "ma12", "ses"]].mean(axis=1, skipna=False)
t0 = time.time(); L["comb_inv_err"] = comb_inv_err(L, ["ma3", "ses", "xgb_abs@A", "lgbm@A"]); RT["synth:comb_inv_err"] = time.time() - t0
NEW = ["median3", "shrink_cat", "topdown_cat", "knn_analog", "lgbm_q50@A", "lgbm_tweedie@A", "comb_inv_err"]
RERUN = ["tsb", "ens_xgb_ma3@A", "comb_simple", "ma12", "lgbm@A", "xgb_abs@A", "ridge@A", "xgb_raw@A", "sba"]
L.to_csv("preds_synth.csv.gz", index=False)
print(f"SYNTH preds_synth rows {len(L)} | model cols {len(NEW) + len(RERUN) + 1} (+ helper ses, ma4) | month range {L.month.min()}..{L.month.max()}")
json.dump(RT, open("rt_comb.json", "w"))


def score(D, models, arm):
    rows = []; W = D[(D.month >= "2023-10") & (D.month <= "2026-02")]
    for bn in ("short", "medium", "long"):
        full = cells(W[W.bin == bn], ["ma3"] + models)
        blk = [cells(d, ["ma3"] + models) if len(d := D[(D.month >= lo) & (D.month <= hi) & (D.bin == bn)]) else None for lo, hi in BLOCKS]
        mm3 = full["mase_ma3"].dropna()
        rows.append(dict(arm=arm, bin=bn, model="MA3", med_mase=float(mm3.median()), n=len(full),
                         testable=sum(c is not None and len(c) >= 5 for c in blk)))
        for m in models:
            f = compare(full[m], full["ma3"]) if len(full) else dict(n=0, v="NT")
            vs = [compare(c[m], c["ma3"])["v"] if c is not None and len(c) else "NT" for c in blk]
            bf, bm = bias(full["bias_" + m]) if len(full) else ("NT", np.nan)
            mm = full["mase_" + m].dropna() if len(full) else pd.Series(dtype=float)
            r = dict(arm=arm, bin=bn, model=m, n=f["n"], W=vs.count("W"), T=vs.count("T"), L=vs.count("L"), testable=5 - vs.count("NT"),
                     nb=f.get("nb"), nw=f.get("nw"), med_mase=float(mm.median()) if len(mm) else np.nan, bias=bf)
            r["tag"] = "OUT" if r["L"] > 0 else "WEAK" if (r["testable"] < 3 or not r["med_mase"] < 1) else "FIT"
            rows.append(r)
    return rows


REAL_M = NEW + ["adida", "imapa", "otm"] + RERUN
out = pd.DataFrame(score(A, REAL_M, "REAL") + score(L, NEW + RERUN, "SYNTH"))
out.to_csv("cells_arms.csv", index=False)
pd.set_option("display.width", 250, "display.max_rows", 300)
print(out.round(3).to_string())
# same-cohort check: SYNTH forecasts scored on the REAL bins (isolates the prefix from the re-binning)
Lc = L.copy(); Lc["bin"] = Lc.bin_real
same = pd.DataFrame(score(Lc, NEW + RERUN, "SYNTH_on_REAL_bins")); same.to_csv("cells_synth_realbins.csv", index=False)
