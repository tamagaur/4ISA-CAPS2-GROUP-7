"""
Chart 1 - model comparison. WAPE per half-year block, MA3 vs TSB, XGBoost+MA3
average, SBA (alpha 0.1) and naive, on the stored bake-off forecasts
(reports/experiment_artifacts/candidate_search_tierA_preds.csv.gz: 119 Tier A SKUs
as of 2026-02, every-month rolling-origin one-step). Nothing is refitted.

Checks (pre-registered, stop the build on failure):
  G3  every stored `actual` equals the extracted real series (inputs/, _Real view).
  G1  the block verdicts and n_better / n_worse (and n) reproduce the 25
      experiment_log.csv rows of run block_tests_tierA exactly.
"""
import _common as C
import numpy as np
import pandas as pd

MODELS = {"ma3": "MA3", "tsb": "TSB", "ens_xgb_ma3@A": "XGBoost+MA3 avg", "sba": "SBA (alpha 0.1)", "naive": "Naive"}
CHALLENGERS = [m for m in MODELS if m != "ma3"]
LOGV = {"W": "win", "L": "loss", "T": "tie", "NT": "not_testable"}


def g3(A, mats):
    got = np.array([mats[int(r.pk)][int(r.ti)] for r in A.itertuples()])
    bad = int((got != A.actual.to_numpy()).sum())
    return dict(id="G3", **{"pass": bad == 0}, detail=f"{len(A) - bad} of {len(A)} stored actuals equal the real series exactly "
                                                          f"(NULL quantity counted as 0); {bad} differ")


def g1(A):
    L = pd.read_csv(C.os.path.join(C.REPO, "reports", "experiment_log.csv"))
    L = L[L.run_id == "block_tests_tierA"]
    rows, bad = [], []
    for r in L.itertuples():
        d = C.in_window(A if r.bin == "ALL" else A[A.bin == r.bin], r.window_start, r.window_end)
        c = C.cells(d, [r.model, "ma3"])
        x = C.compare(c[r.model], c["ma3"]) if len(c) else dict(n=0, v="NT")
        got = dict(n=int(x["n"]), verdict=LOGV[x["v"]], nb=x.get("nb"), nw=x.get("nw"))
        want = dict(n=int(r.n_skus), verdict=r.verdict, nb=None if np.isnan(r.n_better) else int(r.n_better),
                    nw=None if np.isnan(r.n_worse) else int(r.n_worse))
        info = dict(model_value=(round(float(x["mv"]), 4) if "mv" in x else None, r.model_value),
                    ci=((round(float(x["lo"]), 4), round(float(x["hi"]), 4)) if "lo" in x else None,
                        (r.diff_ci_lo, r.diff_ci_hi)))
        ok = got == want
        rows.append(dict(bin=r.bin, model=r.model, window=f"{r.window_start}..{r.window_end}", **{"pass": ok},
                         got=str(got), logged=str(want), info=str(info)))
        if not ok:
            bad.append(rows[-1])
    return dict(id="G1", **{"pass": not bad}, detail=f"{len(rows) - len(bad)} of {len(rows)} logged block_tests_tierA rows reproduce "
                                                      f"(verdict, n, n_better, n_worse)" + (f"; first mismatch {bad[0]}" if bad else "")), pd.DataFrame(rows)


def served_sentence(vs):
    """Computed, not typed: does either served challenger WIN a majority of its served-bin blocks?"""
    out = []
    for cohort, m, name in (("medium (served: TSB)", "tsb", "TSB"), ("long (served: XGBoost+MA3 avg)", "ens_xgb_ma3@A", "XGBoost+MA3 avg")):
        w, wt = C.majority(vs(cohort, m), "W")
        l, lt = C.majority(vs(cohort, m), "L")
        out.append(f"{name} wins {wt} and loses {lt.split(' of ')[0]} blocks: "
                   + ("it beats MA3" if w else "it loses to MA3" if l else "a tie with MA3"))
    return "; ".join(out) + ". "


def main():
    A = C.load_preds()
    mats, periods, ix = C.load_series()
    checks = [g3(A, mats)]
    if not checks[0]["pass"]:
        C.fail("G3", checks[0]["detail"])
    c1, g1rows = g1(A)
    checks.append(c1)
    if not c1["pass"]:
        C.fail("G1", c1["detail"])

    # ---- verdict tables: every challenger vs MA3 (ALL cohort) + served bins --
    tabs = [C.block_table(A, m, "ma3", dict(cohort="ALL")) for m in CHALLENGERS]
    tabs += [C.block_table(A[A.bin == "medium"], "tsb", "ma3", dict(cohort="medium (served: TSB)")),
             C.block_table(A[A.bin == "long"], "ens_xgb_ma3@A", "ma3", dict(cohort="long (served: XGBoost+MA3 avg)"))]
    V = pd.concat(tabs, ignore_index=True)
    V["model_label"] = V.model.map(MODELS)

    # ---- lines: median WAPE per window on ONE SKU set per window (all 5 models finite)
    lines = []
    for lo, hi in [C.FULL] + C.BLOCKS:
        c = C.cells(C.in_window(A, lo, hi), list(MODELS))
        c = c.dropna(subset=list(MODELS))
        for m in MODELS:
            mm = c["mase_" + m].dropna()
            lines.append(dict(window="full" if (lo, hi) == C.FULL else f"{lo}..{hi}", start=lo, end=hi, model=m, model_label=MODELS[m],
                              n=len(c), median_wape=float(c[m].median()) if len(c) else np.nan,
                              mase_pass_pct=100 * float((mm < C.MASE_GATE_PIPELINE).mean()) if len(mm) else np.nan))
    Ln = pd.DataFrame(lines)

    # ---- per-SKU actual vs forecasts, for the selector ------------------------
    tier = pd.read_csv(C.os.path.join(C.INPUTS, "unilever_tierA_2026-02.csv"))
    S = A[["pk", "month", "bin", "actual"] + list(MODELS)].merge(
        tier[["pk", "sku_code", "product_name"]], on="pk", how="left")

    # ---- pre-registered criterion ---------------------------------------------
    def vs(cohort, model):
        t = V[(V.cohort == cohort) & (V.model == model) & (V.window != "full")]
        return t.verdict.tolist()
    tests = {
        "TSB in medium loses to MA3": C.majority(vs("medium (served: TSB)", "tsb"), "L"),
        "XGBoost+MA3 in long loses to MA3": C.majority(vs("long (served: XGBoost+MA3 avg)", "ens_xgb_ma3@A"), "L"),
        "SBA beats MA3 (ALL)": C.majority(vs("ALL", "sba"), "W"),
        "Naive beats MA3 (ALL)": C.majority(vs("ALL", "naive"), "W"),
    }
    flawed = [k for k, (hit, _) in tests.items() if hit]
    verdict = "FLAWED" if flawed else "CONFIRMS"
    detail = "; ".join(f"{k}: {'YES' if hit else 'no'} ({txt})" for k, (hit, txt) in tests.items())

    # ---- caption: every number from the tables above ---------------------------
    full = Ln[Ln.window == "full"].set_index("model")
    strip = lambda cohort, m: "".join(v if v != "NT" else "-" for v in vs(cohort, m))  # noqa: E731
    wtl = lambda cohort, m: (lambda v: f"{v.count('W')} win, {v.count('T')} tie, {v.count('L')} loss, "  # noqa: E731
                                       f"{v.count('NT')} not testable")(vs(cohort, m))
    n_carve = int((A.bin == "intermittent").sum())
    n_carve_long = int(((A.bin == "intermittent") & (A.sales >= 24)).sum())
    caption = (
        f"Median WAPE per half-year block, rolling one-step forecasts, {A.pk.nunique()} Unilever Tier A SKUs (ABC 2026-02, "
        f"single), real data only. Over {C.FULL[0]}..{C.FULL[1]} on the {int(full.n.iloc[0])} SKUs every model can score: "
        + ", ".join(f"{MODELS[m]} {full.loc[m, 'median_wape']:.3f}" for m in MODELS)
        + f". Against MA3 by block (two-condition WAPE test, 95% bootstrap over SKUs, seed {C.SEED}): "
        + "; ".join(f"{MODELS[m]} {strip('ALL', m)} ({wtl('ALL', m)})" for m in CHALLENGERS)
        + f". In the bins where they are served: TSB (medium) {strip('medium (served: TSB)', 'tsb')}, "
          f"XGBoost+MA3 avg (long) {strip('long (served: XGBoost+MA3 avg)', 'ens_xgb_ma3@A')}. "
        + served_sentence(vs) +
          f"Share of SKUs with MASE < {C.MASE_GATE_PIPELINE:g} (pipeline gate) over the full window: "
        + ", ".join(f"{MODELS[m]} {full.loc[m, 'mase_pass_pct']:.0f}%" for m in MODELS)
        + f". Bins are the bake-off's stored bins: the length rule plus an ADI >= 1.32 carve-out that moves {n_carve} "
          f"SKU-months to 'intermittent' ({n_carve_long} of them from long)."
    )
    notes = C.null_notes(A.pk.unique())
    C.write_result(1, "models", "Model comparison", {"lines": Ln, "verdicts": V, "sku_series": S, "g1_reproduction": g1rows},
                   caption, verdict, detail, checks, "ch01_models.py",
                   extra=dict(data_notes=notes + [C.THREAD_NOTE], models=MODELS, blocks=[f"{a}..{b}" for a, b in C.BLOCKS]))


if __name__ == "__main__":
    main()
