"""Build reports/experiment_log.csv from session artifacts. Every value is computed from an artifact file;
nothing is typed in. No DB access. Run once from the session scratchpad (2026-09-21)."""
import datetime, glob, os, pickle, shutil
import numpy as np, pandas as pd

S = os.path.dirname(os.path.abspath(__file__))
TASKS = os.path.join(os.path.dirname(S), "tasks")
REPO = r"C:\Users\kyuan\Capstone-Project"
ART = os.path.join(REPO, "reports", "experiment_artifacts")
REL = "reports/experiment_artifacts/"
SEED, NBOOT, MIN_ORIG, MIN_N = 20260921, 1000, 3, 5
COLS = ["run_id", "run_date", "source_script", "git_commit", "cohort", "abc_period", "abc_method", "n_skus", "data_arm",
        "train_pool", "split_protocol", "window_start", "window_end", "bin", "model", "baseline_model", "metric",
        "model_value", "baseline_value", "diff_ci_lo", "diff_ci_hi", "ci_level", "n_better", "n_worse", "mase_pass_pct",
        "n_boot", "seed", "verdict", "reportable", "status", "notes", "artifact_path"]
rows, copied = [], []
os.makedirs(os.path.join(ART, "scripts"), exist_ok=True)


def mtime(p):
    return datetime.date.fromtimestamp(os.path.getmtime(p)).isoformat()


def export(src, name):
    """Lossless CSV export of a session pickle (DataFrame) into the repo artifact folder."""
    dst = os.path.join(ART, name)
    pd.read_pickle(os.path.join(S, src)).to_csv(dst, index=False, compression="gzip" if name.endswith(".gz") else None)
    copied.append(name); return REL + name


def copy(src_path, name):
    shutil.copyfile(src_path, os.path.join(ART, name)); copied.append(name); return REL + name


def compare(m, b, mase=None):
    """Paired comparison of per-SKU values. Fresh rng(SEED) per call, so every row reproduces on its own."""
    m, b = np.asarray(m, float), np.asarray(b, float)
    ok = np.isfinite(m) & np.isfinite(b); m, b = m[ok], b[ok]
    out = dict(n_skus=len(m))
    if len(m) < MIN_N:
        return dict(out, verdict="not_testable")
    i = np.random.default_rng(SEED).integers(0, len(m), (NBOOT, len(m)))
    d = np.median(m[i], axis=1) - np.median(b[i], axis=1); lo, hi = np.percentile(d, [2.5, 97.5])
    out.update(model_value=round(float(np.median(m)), 4), baseline_value=round(float(np.median(b)), 4),
               diff_ci_lo=round(float(lo), 4), diff_ci_hi=round(float(hi), 4), n_better=int((m < b - 1e-12).sum()),
               n_worse=int((m > b + 1e-12).sum()), verdict="win" if hi < 0 else "loss" if lo > 0 else "tie")
    if mase is not None:
        ms = np.asarray(mase, float)[ok]; ms = ms[np.isfinite(ms)]
        if len(ms): out["mase_pass_pct"] = round(100 * float((ms < 1).mean()), 1)
    return out


def add(base, **kw):
    r = dict(ci_level=0.95, n_boot=NBOOT, seed=SEED, baseline_model="ma3", metric="median_wape", reportable="yes", status="diagnostic")
    r.update(base); r.update(kw)
    if r.get("verdict") in ("not_testable", "crashed") or r.get("status") == "artifact_missing":
        for k in ("ci_level", "n_boot", "seed"):
            if r.get("model_value") is None: r[k] = None
    rows.append(r)


SESSION = dict(run_date="2026-09-21", git_commit="uncommitted scratch script on fd4dded", cohort="Unilever Tier A",
               abc_period="2026-02", abc_method="single")

# ---- R1-R4: single-split per-bin bake-offs (combined_v1 bins) -----------------------------------------------------
ORDER = ["insufficient", "short", "medium", "long_down", "long_flat", "long_up"]


def split_run(df, run_id, script, art, split, arm="real", reportable="yes", extras=False, extra_art=None):
    base = dict(SESSION, run_id=run_id, source_script=script, data_arm=arm, train_pool="per-SKU", split_protocol=split,
                window_end="2026-02", reportable=reportable, artifact_path=art)
    W, M = df.pivot(index="pk", columns="model", values="wape"), df.pivot(index="pk", columns="model", values="mase")
    fit = df.pivot(index="pk", columns="model", values="fittable")
    binof = df.drop_duplicates("pk").set_index("pk").bin; models = [m for m in df.model.unique() if m != "ma3"]
    keep = {}
    for b in ORDER:
        pks = binof[binof == b].index
        if not np.isfinite(W.loc[pks, "ma3"]).any():
            add(base, bin=b, model="ALL", verdict="not_testable", n_skus=len(pks), notes="no SKU has enough real history to fit and test any model"); continue
        keep[b] = [m for m in W.columns if fit.loc[pks, m].sum() * 2 >= len(pks)]
        for m in models:
            k = int(fit.loc[pks, m].sum())
            if m not in keep[b]:
                add(base, bin=b, model=m, verdict="not_testable", n_skus=k, notes=f"fittable on {k} of {len(pks)} SKUs, under half the bin"); continue
            c = compare(W.loc[pks, m], W.loc[pks, "ma3"], M.loc[pks, m])
            if b == "long_up" and c["verdict"] != "not_testable": c["verdict"] = "underpowered"
            add(base, bin=b, model=m, notes=f"bin size {len(pks)}", **c)
    if extras:
        ev = W.index[np.isfinite(W.ma3)]; named = [b for b in keep if b != "long_up"]
        win = {b: W.loc[binof[binof == b].index, keep[b]].median().idxmin() for b in named}

        def route(pick):
            out = W.loc[ev, "ma3"].copy()
            for pk in ev:
                m = pick(pk)
                if m and np.isfinite(W.loc[pk, m]): out[pk] = W.loc[pk, m]
            return out

        def loo(pk):
            b = binof[pk]
            return W.loc[binof[(binof == b) & (binof.index != pk)].index, keep[b]].median().idxmin() if b in named else None
        for name, s, note in (("route:per_bin_winner", route(lambda pk: win.get(binof[pk])), f"winners {win}; long_up and unscored SKUs stay on ma3"),
                              ("route:per_bin_winner_leave_one_out", route(loo), "winner chosen without the SKU being scored"),
                              ("route:per_sku_oracle", W.loc[ev].min(axis=1), "best of all models per SKU after the fact; a ceiling, not a strategy")):
            add(base, bin="ALL", model=name, notes=note, **compare(s, W.loc[ev, "ma3"]))
        lp = binof[binof.str.startswith("long_")].index
        for m in models:
            if fit.loc[lp, m].sum() * 2 >= len(lp):
                add(base, bin="long_merged", model=m, notes=f"long_down+long_flat+long_up, {len(lp)} SKUs", artifact_path=extra_art or art,
                    **compare(W.loc[lp, m], W.loc[lp, "ma3"], M.loc[lp, m]))
            if fit.loc[ev, m].sum() * 2 >= len(ev):
                add(base, bin="ALL", model=m, notes="one model for every evaluable SKU", **compare(W.loc[ev, m], W.loc[ev, "ma3"], M.loc[ev, m]))


copy(os.path.join(S, "per_bin_full.csv"), "routing_8020_per_bin_as_printed.csv")
copy(os.path.join(S, "per_bin_full70.csv"), "routing_7030_per_bin_as_printed.csv")
SPLIT = "{}: train=floor({}n) months from first sale, rolling-origin 1-step, refit each origin, train floor 3"
split_run(pd.read_pickle(os.path.join(S, "b.pkl")), "routing_8020", "scratch b_bakeoff.py + c_report.py + e_merge.py",
          export("b.pkl", "routing_8020_per_sku_model.csv"), SPLIT.format("80/20", 0.8), extras=True)
split_run(pd.read_pickle(os.path.join(S, "b70.pkl")), "routing_7030", "scratch b70_bakeoff.py + c70_report.py",
          export("b70.pkl", "routing_7030_per_sku_model.csv"), SPLIT.format("70/30", 0.7), extras=True)
g = pd.read_pickle(os.path.join(S, "g.pkl")); gart = export("g.pkl", "synthetic_arms_8020_per_sku_model.csv")
for arm, desc in (("A", "synthetic_A (2021-22 is_demo prefix, calendar-true, gap zero-filled)"), ("B", "synthetic_B (2021-22 is_demo prefix, spliced)")):
    split_run(g[g.arm == arm], f"synthetic_arm_{arm}_8020", "scratch g_synth_bakeoff.py + h_synth_report.py", gart,
              SPLIT.format("80/20", 0.8) + "; synthetic months are TRAINING context only, test months/actuals/MASE scale/bins real", arm=desc, reportable="no")

# ---- rolling-origin helpers -----------------------------------------------------------------------------------------
def cells(df, keys, models):
    out = []
    for key, grp in df.groupby(keys):
        a = grp.actual.to_numpy(); den = np.abs(a).sum()
        if len(grp) < MIN_ORIG or den <= 0: continue
        key = key if isinstance(key, tuple) else (key,)
        r = dict(zip(keys, key)); sc = grp.scale.to_numpy(); ok = sc > 0
        for m in models:
            p = grp[m].to_numpy(); fin = np.isfinite(p).all()
            r[m] = np.abs(a - p).sum() / den if fin else np.nan
            r["mase_" + m] = float(np.mean(np.abs(a - p)[ok] / sc[ok])) if fin and ok.any() else np.nan
        out.append(r)
    return pd.DataFrame(out) if out else pd.DataFrame(columns=keys + models + ["mase_" + m for m in models])


META = ["pk", "ti", "ntr", "sales", "adi", "bin", "scale", "actual", "month", "tier", "ma_k"]
ROLL = "every-month rolling-origin 1-step from first sale + 3 months; bin computed at each origin from history known then; SKU needs >= 3 origins in the window"
WIN = {"select": ("2023-10", "2025-08"), "confirm_unseen": ("2025-09", "2026-02"), "all29": ("2023-10", "2026-02")}
BLOCKS = [("2023-10", "2024-02"), ("2024-03", "2024-08"), ("2024-09", "2025-02"), ("2025-03", "2025-08"), ("2025-09", "2026-02")]


def window_rows(df, base, models, lo, hi, bins, wname):
    d = df[(df.month >= lo) & (df.month <= hi)]
    for b in bins:
        c = cells(d if b == "ALL" else d[d.bin == b], ["pk"], ["ma3"] + models)
        for m in models:
            add(base, window_start=lo, window_end=hi, bin=b, model=m, notes=wname,
                **(compare(c[m], c["ma3"], c["mase_" + m]) if len(c) else dict(n_skus=0, verdict="not_testable")))


# ---- R5: candidate search on Tier A ----------------------------------------------------------------------------------
A = pd.read_pickle(os.path.join(S, "final_models_A.pkl")); aart = export("final_models_A.pkl", "candidate_search_tierA_preds.csv.gz")
cand = [c for c in A.columns if c not in META and c != "ma3"]
b5 = dict(SESSION, run_id="candidate_search_tierA", source_script="scratch final_fit.py + final_models.py", data_arm="real",
          train_pool="per-SKU; '@A' = one global model trained on Tier A origins, '@ABC' = trained on Tier A+B+C origins, retrained monthly on strictly earlier origins",
          split_protocol=ROLL, artifact_path=aart)
for w, (lo, hi) in WIN.items():
    window_rows(A, b5, cand, lo, hi, ["ALL"] + (["short", "medium", "long"] if w == "all29" else []), w)
for i, f in enumerate(sorted(glob.glob(os.path.join(TASKS, "*.output")))):
    txt = open(f, encoding="utf-8", errors="replace").read()
    if "lightgbm" in txt and "access violation" in txt:
        api = "scikit-learn wrapper (LGBMRegressor)" if "LGBMRegressor" in txt or "lightgbm\\sklearn.py" in txt else "native lgb.train"
        add(b5, bin="ALL", model="lgbm", verdict="crashed", n_skus=None, artifact_path=copy(f, f"lightgbm_crash_{os.path.basename(f)}.txt"),
            notes=f"{api}: OSError access violation in LGBM_DatasetSetField with xgboost loaded in the same process; no forecasts produced")

# ---- R6: block tests + monthly scoreboard ----------------------------------------------------------------------------
b6 = dict(b5, run_id="block_tests_tierA", source_script="inline analysis of final_models_A (gate report 2026-09-21)")
ENS = "ens_xgb_ma3@A"
for model, bn in ((ENS, "ALL"), (ENS, "long"), ("xgb_abs@A", "long"), ("tsb", "medium"), ("tsb", "ALL")):
    for lo, hi in BLOCKS:
        d = A[(A.month >= lo) & (A.month <= hi)]; d = d if bn == "ALL" else d[d.bin == bn]
        c = cells(d, ["pk"], ["ma3", model])
        add(b6, window_start=lo, window_end=hi, bin=bn, model=model, train_pool=f"{int((A.month < lo).sum())} Tier A training origins before the block",
            notes=f"half-year block; {len(d)} test origins", **(compare(c[model], c["ma3"], c["mase_" + model]) if len(c) else dict(n_skus=0, verdict="not_testable")))
b6m = dict(b6, run_id="monthly_scoreboard_tierA", metric="pooled_wape", ci_level=None, n_boot=None, seed=None)
for bn, model in (("long", ENS), ("medium", "tsb")):
    streak = 0
    for mth, grp in A[A.bin == bn].groupby("month"):
        a = grp.actual.to_numpy(); den = np.abs(a).sum(); em, e3 = np.abs(a - grp[model]), np.abs(a - grp.ma3)
        wm, w3 = float(em.sum() / den), float(e3.sum() / den); lose = wm > w3; streak = streak + 1 if lose else 0
        add(b6m, window_start=mth, window_end=mth, bin=bn, model=model, n_skus=len(grp), model_value=round(wm, 4), baseline_value=round(w3, 4),
            n_better=int((em < e3).sum()), n_worse=int((em > e3).sum()), verdict="loss" if lose else "win",
            notes=f"one month, sum|err|/sum|actual| across the bin's SKUs, no interval; consecutive losing months so far = {streak}")

# ---- R7: global model evaluated across Tier A+B+C --------------------------------------------------------------------
G = pd.read_pickle(os.path.join(S, "final_preds_all.pkl")); gl = export("final_preds_all.pkl", "rolling_origin_preds_tierABC_xgbTrainedOnTierA.csv.gz")
export("final_preds.pkl", "rolling_origin_preds_tierABC_base_models.csv.gz")
gm = [c for c in G.columns if c not in META and c != "ma3"]
for coh, sub in (("Unilever Tier A", G[G.tier == "A"]), ("Unilever Tier A+B+C", G)):
    b7 = dict(SESSION, run_id="global_model_trainA_evalABC", cohort=coh, source_script="scratch final_fit.py + final_eval.py (TRAIN_TIER=A)", data_arm="real",
              train_pool="per-SKU; xgb_global = one model trained on Tier A origins only (last run to write this file)", split_protocol=ROLL, artifact_path=gl)
    window_rows(sub, b7, gm, *WIN["all29"], ["intermittent", "short", "medium", "long"], "all29")
    window_rows(sub, b7, gm, *WIN["confirm_unseen"], ["ALL", "intermittent", "short", "medium", "long"], "confirm_unseen")
for tag in ("default seed 20260921", "XGB_SEED=1", "XGB_SEED=2"):
    add(dict(SESSION, run_id="global_model_trainABC_evalABC", cohort="Unilever Tier A+B+C", source_script="scratch final_eval.py", data_arm="real",
             train_pool="xgb_global trained on Tier A+B+C origins", split_protocol=ROLL), bin="ALL", model="xgb_global", status="artifact_missing",
        notes=f"{tag}: final_preds_all.pkl was overwritten by the later TRAIN_TIER=A run; results exist only as session printouts and are not entered. "
              "The Tier-A evaluation of an A+B+C-trained model survives as xgb_abs@ABC in candidate_search_tierA.")

# ---- R8: synthetic prefix check on the chosen models -----------------------------------------------------------------
Sx = pd.read_pickle(os.path.join(S, "synth_check.pkl")); sart = export("synth_check.pkl", "synth_check_tierA_preds.csv.gz")
b8 = dict(SESSION, run_id="synthetic_prefix_check_tierA", source_script="scratch synth_check.py", reportable="no", split_protocol=ROLL, artifact_path=sart,
          data_arm="synthetic_A (calendar-true); xgb_synA = lags may reach synthetic months, xgb_synB = also trains on synthetic-target rows",
          train_pool="Tier A origins (+2,282 synthetic-target rows for xgb_synB)")
window_rows(Sx, b8, ["tsb_syn", "xgb_synA", "xgb_synB", "ens_xgb_synA", "ens_xgb_synB"], *WIN["all29"], ["short", "medium", "long"], "all29")

# ---- R9 / R10: earlier runs already under reports/ --------------------------------------------------------------------
add(dict(run_id="gate_d_bakeoff"), bin=None, model=None, baseline_model=None, metric=None, status="artifact_missing", reportable=None,
    notes="No file readable in this session is labelled 'Gate D' (reports/*.md searched; PROJECT_STATE not read by instruction). Candidate artifacts, NOT entered: "
          "reports/bakeoff_8020_per_sku_119_2026-09.csv, bakeoff_8020_per_sku_89_2026-09.csv, model_decision_per_sku_2026-09.csv, model_bakeoff_recheck_2026-09.csv. Yuan to map.")
for fn, arm, rep in (("xgboost_bakeoff_unilever_tierA.csv", "real", "yes"), ("xgboost_bakeoff_unilever_tierA_withsynth.csv", "synthetic 2021-22 in TRAINING only (per script docstring)", "no")):
    p = os.path.join(REPO, "reports", fn); d = pd.read_csv(p); d = d[d.evaluable.astype(str).str.lower().isin(["true", "1"])]
    for metric in ("smape", "mase"):
        for m in ("xgboost", "naive", "sba_a3", "theta"):
            add(dict(run_id="xgboost_bakeoff_old", run_date=mtime(p), source_script="scripts/xgboost_bakeoff.py", cohort="Unilever Tier A", abc_period="2026-02",
                     data_arm=arm, train_pool="one global XGBoost across Tier A SKUs (per script docstring)", reportable=rep,
                     split_protocol="rolling-origin 1-step over the last 6 real months (TEST_H=6 in the script)", artifact_path="reports/" + fn),
                bin="ALL", model=m, metric="median_" + metric, notes="file has no WAPE column; run date = file modified date",
                **compare(d[f"{m}_{metric}"], d[f"ma3_{metric}"], d[f"{m}_mase"]))

for f in sorted(glob.glob(os.path.join(S, "*.py"))):
    copy(f, "scripts/" + os.path.basename(f))
bins = pickle.load(open(os.path.join(S, "a.pkl"), "rb"))
pd.DataFrame([{"product_key": pk, **{k + "_2026_02": v for k, v in bins["b26"][pk].items()}, "bin_2025_08": bins["b25"][pk]["bin"]} for pk in bins["cohort"]]
             ).to_csv(os.path.join(ART, "cohort_bins_combined_v1.csv"), index=False); copied.append("cohort_bins_combined_v1.csv")

L = pd.DataFrame(rows).reindex(columns=COLS)
blank_ok = L.verdict.isin(["not_testable", "crashed"]) | (L.status == "artifact_missing")
assert not L.loc[~blank_ok, ["model_value", "baseline_value"]].isna().any().any(), "NaN in a scored row"
assert not np.isinf(L[["model_value", "baseline_value", "diff_ci_lo", "diff_ci_hi"]].astype(float)).any().any()
L.to_csv(os.path.join(REPO, "reports", "experiment_log.csv"), index=False)
print("rows", len(L), "| artifact_missing", int((L.status == "artifact_missing").sum()), "| artifacts", len(copied))
print(L.groupby("run_id").size().to_string()); print(L.verdict.value_counts(dropna=False).to_dict())
print("NaN model_value outside blank-allowed rows:", int(L.loc[~blank_ok, "model_value"].isna().sum()))
bt = L[L.run_id == "block_tests_tierA"]; print("block rows", len(bt), "not_testable", int((bt.verdict == "not_testable").sum()), "| monthly", int((L.run_id == "monthly_scoreboard_tierA").sum()))
show = ["bin", "model", "window_start", "model_value", "baseline_value", "n_better", "n_worse", "diff_ci_lo", "diff_ci_hi", "verdict"]
print(bt[(bt.model == ENS) & (bt.bin == "ALL") & (bt.window_start == "2025-09")][show].to_string(index=False))
c5 = L[(L.run_id == "candidate_search_tierA") & (L.notes == "all29") & (L.bin == "ALL")]; print(c5[c5.model == "tsb"][show].to_string(index=False))
r1 = L[(L.run_id == "routing_8020") & (L.bin == "long_flat") & (L.model == "sba")]; print(r1[show].to_string(index=False))
g7 = L[(L.run_id == "global_model_trainA_evalABC") & (L.cohort == "Unilever Tier A") & (L.bin == "ALL") & (L.model == "xgb_global")]; print(g7[show].to_string(index=False))
print("artifact bytes:", sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(ART) for f in fs))
