"""Append the 2026-09-22 candidate follow-up scored cells to reports/experiment_log.csv.

One log row per scored cell (bin x model x arm) in the five artifacts written by
scripts/candidate_followup_2026-09-22/ (cells_all.py, score_7_and_lgbm.py, score_arms.py).
Every number is read from those CSVs; nothing is typed.

Dedupe: cells_arms REAL reproduces 36 cells already contributed by cells_all / cells_7 /
cells_lgbm (same harness, same preds, max |diff| 1.1e-16). Those 36 are appended once.
"""
import pandas as pd, numpy as np

REPO = "."
LOG = f"{REPO}/reports/experiment_log.csv"
ART = f"{REPO}/reports/experiment_artifacts"
PROTO = ("every-month rolling-origin 1-step from first sale + 3 months; bin computed at each "
         "origin from history known then; SKU needs >= 3 origins in the window")
COMMIT = "075c11f"
SCRIPTS = "scratch candidate_followup_2026-09-22/"


def pool(m):
    if m.endswith("@A"):
        return "Tier A pool (global)"
    if m.endswith("@ABC"):
        return "Tier A+B+C pool (global)"
    return {"comb_inv_err": "per-SKU + Tier A pool (mixed components)",
            "shrink_cat": "per-SKU + category peers (Tier A)",
            "topdown_cat": "category total (Tier A)",
            "knn_analog": "Tier A pool (cross-SKU analogs)"}.get(m, "per-SKU")


def base(model, bin_, src, arm, srcfile, reportable):
    return dict(run_id="", run_date="2026-09-22", source_script=SCRIPTS + src, git_commit=COMMIT,
                cohort="Unilever Tier A", abc_period="2026-02", abc_method="single", n_skus="",
                data_arm=arm, train_pool=pool(model), split_protocol=PROTO, window_start="2023-10",
                window_end="2026-02", bin=bin_, model=model, baseline_model="ma3", metric="",
                model_value="", baseline_value="", diff_ci_lo="", diff_ci_hi="", ci_level=0.95,
                n_better="", n_worse="", mase_pass_pct="", n_boot=1000, seed=20260921, verdict="",
                reportable=reportable, status="diagnostic", notes="",
                artifact_path=f"reports/experiment_artifacts/{srcfile}")


def num(v, nd=4):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return ""
    return int(round(float(v))) if nd == 0 else round(float(v), nd)


VMAP = {"W": "win", "L": "loss", "T": "tie", "NT": "not_testable"}
rows = []

# ---- WAPE cells: cells_all / cells_7 / cells_lgbm (REAL arm) ----
for f, src in (("cells_all", "cells_all.py"), ("cells_7", "score_7_and_lgbm.py"),
               ("cells_lgbm", "score_7_and_lgbm.py + run_lgbm.py")):
    for r in pd.read_csv(f"{ART}/{f}.csv").itertuples():
        d = base(r.model, r.bin, src, "real", f"{f}.csv", "yes")
        d.update(run_id="candidate_followup_2026-09-22", n_skus=int(r.n), metric="median_wape",
                 model_value=num(r.wape), baseline_value=num(r.ma3), n_better=num(r.nb, 0),
                 n_worse=num(r.nw, 0), mase_pass_pct=num(r.mase_pass, 1), verdict=VMAP[r.whole],
                 notes=(f"blocks {r.blocks} (W{r.W}/T{r.T}/L{r.L}, testable {r.testable}/5); "
                        f"tag={r.tag}; median MASE {num(r.med_mase)}; bias {r.bias} "
                        f"(mean scaled signed error {num(r.bias_mean)}); interval not retained by the "
                        f"harness - verdict is the two-condition test (interval clear of 0 AND more "
                        f"SKUs better), cells_all.py:20-28"))
        rows.append(d)

seen = {(r["bin"], r["model"]) for r in rows}

# ---- MASE cells: cells_arms (REAL + SYNTH) and cells_synth_realbins ----
ARMS = {"REAL": ("candidate_followup_2026-09-22", "real", "yes"),
        "SYNTH": ("candidate_followup_synth_2026-09-22",
                  "synthetic 2021-22 prefix; bins recomputed on the synthetic history", "no"),
        "SYNTH_on_REAL_bins": ("candidate_followup_synth_realbins_2026-09-22",
                               "synthetic 2021-22 prefix; scored on the real bins", "no")}
for f in ("cells_arms", "cells_synth_realbins"):
    for r in pd.read_csv(f"{ART}/{f}.csv").itertuples():
        if r.arm == "REAL" and (r.bin, r.model) in seen:
            continue                      # already appended above from cells_all / cells_7 / cells_lgbm
        run_id, arm, rep = ARMS[r.arm]
        d = base(r.model, r.bin, "score_arms.py", arm, f"{f}.csv", rep)
        d.update(run_id=run_id, metric="median_mase", model_value=num(r.med_mase),
                 n_skus="" if not np.isfinite(r.n) else int(r.n))
        if r.model == "MA3":
            d.update(baseline_model="", notes=("baseline reference row: MA3's own median MASE on this "
                                               "arm/bin; no comparison (score_arms.py:63-65)"))
        elif not np.isfinite(r.med_mase):
            d.update(verdict="not_run", notes=str(r.tag))
        else:
            d.update(n_better=num(r.nb, 0), n_worse=num(r.nw, 0),
                     notes=(f"blocks W{num(r.W,0)}/T{num(r.T,0)}/L{num(r.L,0)} (testable "
                            f"{num(r.testable,0)}/5); tag={r.tag}; bias {r.bias}; n_better/n_worse and "
                            f"the block verdicts are the WAPE two-condition test, the value column is "
                            f"median MASE - the harness (score_arms.py:69-71) does not retain a "
                            f"whole-window WAPE verdict, so `verdict` is blank"))
        rows.append(d)

log = pd.read_csv(LOG, dtype=str)
new = pd.DataFrame(rows)[list(log.columns)].astype(str).replace("nan", "")
print(f"existing {len(log)} + new {len(new)} = {len(log) + len(new)}")
pd.concat([log, new], ignore_index=True).to_csv(LOG, index=False, lineterminator="\n")
