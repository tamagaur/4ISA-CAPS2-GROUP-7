"""
Chart 2 - history truncation. For Tier A SKUs (ABC 2026-02) with >= 30 real sales
months, every forecast month that has >= 24 months of history is re-forecast with
the history cut to its last k months (k = 3..24): MA3, TSB (model_bakeoff.m_tsb,
the column the bake-off stored) and the XGBoost+MA3 average (global XGBoost, the
bake-off's xgb_abs@A recipe: final_models.py:63-109, pool = all 132 Tier A series).

Truncation applies to the forecast SKU AND to every training row of the global
model: each origin sees only its last k months (so lag12 / mean12 are missing
below k = 12, and months_history is capped at k). The MASE denominator is the
stored UNTRUNCATED in-sample naive MAE, so only the forecast changes with k.
MASE gate: 1.0 (pipeline, baseline.py:55).

Check G4, AMENDED 2026-09-30 (reports/evidence/AMENDMENTS.csv; approved by Yuan):
  (a) with no truncation, TSB equals the stored tsb on all 2,711 rows exactly;
  (b) the nthread=1 XGBoost full-history run reproduces itself exactly across two runs.
The original G4 also required the stored xgb_abs@A exactly; that needs nthread=8
(g4_thread_check.py: 176/176 exact at 8 threads, 0/176 at 1). The chart therefore
uses this nthread=1 harness as its own reference for every k, full history
included, and reports the measured gap to the stored xgb_abs@A in its data notes.

Single-threaded maths (XGBoost nthread=1; the bake-off used 8), at most 4 workers.
"""
import _common as C
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

MIN_TRAIN, FULL0 = 3, "2023-10"
KS = list(range(3, 25))
MIN_SALES_MONTHS, MIN_HISTORY = 30, 24
CUTOFFS = {"tsb": 12, "xgb_ma3": 24}
UNIT = list(range(10))
XGB_A = dict(max_depth=4, eta=0.05, subsample=0.8, colsample_bytree=0.8, objective="reg:absoluteerror",
             seed=C.SEED, nthread=1)                        # final_models.py:81, nthread 8 -> 1
XGB_ROUNDS, XGB_MIN_ROWS = 300, 100                         # final_models.py:82,105


def m_tsb(x):  # verbatim scripts/model_bakeoff.py:175-185 (imported below and asserted identical)
    a, b = 0.3, 0.1
    demand = x[x > 0].mean() if (x > 0).any() else 0.0
    prob = (x > 0).mean()
    for v in x:
        if v > 0:
            demand += a * (v - demand)
            prob += b * (1 - prob)
        else:
            prob += b * (0 - prob)
    return demand * prob


def feat(tr, ti):
    """final_models.py:63-69 on a (possibly truncated) history tr; ntr and sales are
    measured on what the model is allowed to see."""
    s = tr[-6:].mean()
    lag = lambda k: tr[-k] if len(tr) >= k else np.nan  # noqa: E731
    return [lag(1), lag(2), lag(3), lag(4), lag(5), lag(6), lag(12), tr[-3:].mean(),
            tr[-12:].mean() if len(tr) >= 12 else np.nan, tr[-6:].std(), float((tr[-6:] <= 0).sum()),
            len(tr), float((tr > 0).sum()) / len(tr), (ti % 12) + 1], s


def cut(tr, k):
    return tr if k is None else tr[-k:]


def origin_rows(series, k):
    """Every origin (pk, t) of every Tier A series, in the bake-off's row order (pk, then t)."""
    F, S, Y, TI = [], [], [], []
    for pk in sorted(series):
        x, fs = series[pk]
        for t in range(MIN_TRAIN, len(x)):
            f, s = feat(cut(x[:t], k), fs + t)
            F.append(f); S.append(s); Y.append(x[t]); TI.append(fs + t)
    return np.array(F, float), np.array(S, float), np.array(Y, float), np.array(TI)


def xgb_for(args):
    """One truncation level: the global model refitted for each requested month.
    Returns {(pk, ti): forecast}."""
    series, k, months, targets = args
    import xgboost as xgb
    F, S, Y, TI = origin_rows(series, k)
    ok = S > 0
    Fs = F.copy(); Fs[:, UNIT] = Fs[:, UNIT] / np.where(ok, S, np.nan)[:, None]; Ys = Y / np.where(ok, S, np.nan)
    out = {}
    for m in months:
        trm = ok & (TI < m)
        tg = [(pk, ti) for pk, ti in targets if ti == m]
        if trm.sum() < XGB_MIN_ROWS or not tg:
            continue
        booster = xgb.train(XGB_A, xgb.DMatrix(Fs[trm], label=Ys[trm]), num_boost_round=XGB_ROUNDS)
        rows, ss, keys = [], [], []
        for pk, ti in tg:
            x, fs = series[pk]
            f, s = feat(cut(x[:ti - fs], k), ti)
            if not s > 0:
                continue
            rows.append(f); ss.append(s); keys.append((pk, ti))
        if not rows:
            continue
        Fte = np.array(rows, float); ss = np.array(ss, float); Fte[:, UNIT] = Fte[:, UNIT] / ss[:, None]
        for key, v in zip(keys, booster.predict(xgb.DMatrix(Fte)) * ss):
            out[key] = max(0.0, float(v))
    return k, out


def main():
    t0 = time.time()
    sys.path.insert(0, C.REPO)
    from scripts.model_bakeoff import m_tsb as bakeoff_tsb
    import inspect
    assert inspect.getsource(bakeoff_tsb).split("\n", 1)[1] == inspect.getsource(m_tsb).split("\n", 1)[1], "m_tsb drifted from model_bakeoff"

    A = C.load_preds()
    mats, periods, ix = C.load_series()
    series = {}
    for pk in sorted(mats):
        nz = np.nonzero(mats[pk] > 0)[0]
        if len(nz):
            series[pk] = (mats[pk][int(nz[0]):], int(nz[0]))

    # ---- G4 (amended): TSB exact vs stored; nthread=1 XGBoost reproduces itself --
    tsb0 = np.array([max(0.0, m_tsb(series[int(r.pk)][0][:int(r.ntr)])) for r in A.itertuples()])
    d_tsb = int((tsb0 != A.tsb.to_numpy()).sum())
    stored = A[np.isfinite(A["xgb_abs@A"])]
    months_all = sorted(stored.ti.unique().tolist())
    tg_all = list(zip(stored.pk.astype(int), stored.ti.astype(int)))
    with ProcessPoolExecutor(max_workers=2) as ex:
        (_, x1), (_, x2) = list(ex.map(xgb_for, [(series, None, months_all, tg_all)] * 2))
    self_bad = sum(x1.get(key) != x2.get(key) for key in set(x1) | set(x2))
    g4 = dict(id="G4", **{"pass": d_tsb == 0 and self_bad == 0 and len(x1) == len(tg_all)},
              detail=f"(a) tsb: {len(A) - d_tsb} of {len(A)} equal the stored values; (b) XGBoost nthread=1 full history, two runs: "
                     f"{len(x1) - self_bad} of {len(x1)} forecasts identical ({len(months_all)} refits each; {len(tg_all)} targets)")
    print(f"G4 {'PASS' if g4['pass'] else 'FAIL'}: {g4['detail']} [{time.time() - t0:.0f}s]", flush=True)
    if not g4["pass"]:
        C.fail("G4", g4["detail"])

    # ---- measured gap to the stored nthread=8 forecasts (data note, not a check)
    import json
    with open(os.path.join(C.EVID, "g4_thread_check.json"), encoding="utf-8") as fh:
        tc = json.load(fh)
    if not tc["confirmed"]:
        C.fail("G4", "g4_thread_check.json: nthread=8 does not reproduce the stored xgb_abs@A - harness difference, not threading")
    own = np.array([x1[key] for key in tg_all]); ref = stored["xgb_abs@A"].to_numpy()
    rel = np.abs(own - ref) / np.maximum(ref, 1.0)
    G = stored.assign(own_avg=pd.DataFrame({"x": own, "m": stored.ma3.to_numpy()}).mean(axis=1, skipna=False).to_numpy())
    G = G[G.bin == "long"]
    v_st = C.block_table(G, "ens_xgb_ma3@A", "ma3"); v_own = C.block_table(G, "own_avg", "ma3")
    strip = lambda t: "".join(v if v != "NT" else "-" for v in t[t.window != "full"].verdict)  # noqa: E731
    gap = dict(rows=len(ref), exact=int((own == ref).sum()), median_rel=float(np.median(rel)),
               p90_rel=float(np.percentile(rel, 90)), worst_rel=float(rel.max()),
               long_blocks_stored=strip(v_st), long_blocks_nthread1=strip(v_own))
    gap_note = (f"Measured gap, this harness (XGBoost nthread=1) vs the stored xgb_abs@A (nthread=8), full history, "
                f"{gap['rows']} forecasts: {gap['exact']} identical; relative |diff| = |ours - stored| / max(stored, 1): median "
                f"{gap['median_rel']:.1%}, p90 {gap['p90_rel']:.1%}, worst {gap['worst_rel']:.0%}. XGBoost+MA3 avg vs MA3 in the "
                f"long bin, by block: stored {gap['long_blocks_stored']}, this harness {gap['long_blocks_nthread1']}"
                + (" (unchanged)." if gap['long_blocks_stored'] == gap['long_blocks_nthread1'] else " (CHANGED).")
                + f" g4_thread_check.py, months {' and '.join(tc['months'])}: at nthread=8 the same harness matches the stored "
                  f"values on {tc['nthread_8']['exact']} of {tc['nthread_8']['rows']} forecasts, at nthread=1 on "
                  f"{tc['nthread_1']['exact']} of {tc['nthread_1']['rows']}"
                + (", so the gap is thread count, not harness." if tc["confirmed"] else "; NOT confirmed."))
    print(gap_note, flush=True)

    # ---- test rows: SKUs with >= 30 sales months, months with >= 24 months of history
    sales_months = {pk: int((mats[pk] > 0).sum()) for pk in mats}
    keep = {pk for pk, n in sales_months.items() if n >= MIN_SALES_MONTHS}
    T = A[A.pk.isin(keep) & (A.ntr >= MIN_HISTORY) & (A.month >= C.FULL[0]) & (A.month <= C.FULL[1])].copy()
    targets = list(zip(T.pk.astype(int), T.ti.astype(int)))
    months = sorted(T.ti.unique().tolist())
    print(f"test rows {len(T)} on {T.pk.nunique()} SKUs (of {len(keep)} with >= {MIN_SALES_MONTHS} sales months), "
          f"months {T.month.min()}..{T.month.max()}; {len(KS)} k x {len(months)} refits on {C.MAX_WORKERS} workers", flush=True)

    with ProcessPoolExecutor(max_workers=C.MAX_WORKERS) as ex:
        res = dict(ex.map(xgb_for, [(series, k, months, targets) for k in KS]))
    print(f"refits done [{time.time() - t0:.0f}s]", flush=True)

    for k in KS:
        T[f"ma3_k{k}"] = [cut(series[int(r.pk)][0][:int(r.ntr)], k)[-3:].mean() for r in T.itertuples()]
        T[f"tsb_k{k}"] = [max(0.0, m_tsb(cut(series[int(r.pk)][0][:int(r.ntr)], k))) for r in T.itertuples()]
        xg = np.array([res[k].get((int(p), int(t)), np.nan) for p, t in zip(T.pk, T.ti)])
        T[f"xgb_ma3_k{k}"] = pd.DataFrame({"x": xg, "m": T.ma3.to_numpy()}).mean(axis=1, skipna=False).to_numpy()
    ma3_flat = all(np.array_equal(T[f"ma3_k{k}"].to_numpy(), T.ma3.to_numpy()) for k in KS)
    T["tsb_kall"] = T.tsb                                    # equals the recomputed TSB exactly (G4a)
    T["xgb_ma3_kall"] = pd.DataFrame({"x": [x1[(int(p), int(t))] for p, t in zip(T.pk, T.ti)],
                                      "m": T.ma3.to_numpy()}).mean(axis=1, skipna=False).to_numpy()  # own nthread=1 reference

    # ---- scoring ---------------------------------------------------------------
    V, lines = [], []
    for k in KS + ["all"]:
        for fam in ("tsb", "xgb_ma3"):
            c = f"{fam}_k{k}"
            bt = C.block_table(T, c, "ma3", dict(family=fam, k=k))
            V.append(bt)
            f = bt[bt.window == "full"].iloc[0]
            lines.append(dict(k=k, family=fam, n=f.n, median_wape=f.model_wape, ma3_median_wape=f.base_wape,
                              mase_pass_pct=f.mase_pass_pct, verdict_full=f.verdict,
                              blocks="".join(v if v != "NT" else "-" for v in bt[bt.window != "full"].verdict)))
        cm = C.cells(T, ["ma3"]); mm = cm["mase_ma3"].dropna()
        lines.append(dict(k=k, family="ma3", n=len(cm), median_wape=float(cm.ma3.median()), ma3_median_wape=float(cm.ma3.median()),
                          mase_pass_pct=100 * float((mm < C.MASE_GATE_PIPELINE).mean()), verdict_full="", blocks=""))
    V = pd.concat(V, ignore_index=True)
    Ln = pd.DataFrame(lines)

    # ---- pre-registered criterion ---------------------------------------------
    findings, testable = [], None
    for fam, cutoff in CUTOFFS.items():
        for k in KS:
            vs = V[(V.family == fam) & (V.k == k) & (V.window != "full")].verdict.tolist()
            w, wt = C.majority(vs, "W"); lo_, lt = C.majority(vs, "L")
            testable = wt.split(" of ")[1].split(" ")[0]
            if k < cutoff and w:
                findings.append(f"{fam} k={k} < cutoff {cutoff} beats MA3 in {wt} blocks (cutoff too high)")
            if k >= cutoff and lo_:
                findings.append(f"{fam} k={k} >= cutoff {cutoff} loses to MA3 in {lt} blocks (cutoff too low)")
    verdict = "FLAWED" if findings else "CONFIRMS"
    detail = "; ".join(findings) if findings else f"no k crosses either cutoff's test ({testable} testable blocks per k)"

    L_ = Ln.set_index(["family", "k"])
    fam_lbl = {"tsb": "TSB", "xgb_ma3": "XGBoost+MA3 avg"}
    wins = {f: [k for k in KS if "W" in L_.loc[(f, k), "blocks"]] for f in CUTOFFS}
    losses = {f: [k for k in KS if "L" in L_.loc[(f, k), "blocks"]] for f in CUTOFFS}
    caption = (
        f"History truncation: {T.pk.nunique()} Unilever Tier A SKUs (ABC 2026-02, single) with >= {MIN_SALES_MONTHS} real sales "
        f"months, {len(T)} forecast months that have >= {MIN_HISTORY} months of history ({T.month.min()}..{T.month.max()}, "
        f"{testable} testable half-year blocks). Each is re-forecast with its history cut to the last k months; the global "
        f"XGBoost model (nthread=1) is refitted for every k and month on equally truncated training rows, and the same harness's "
        f"full-history run is the reference. MA3 is unchanged for every k >= 3 "
        f"({'verified: identical forecasts' if ma3_flat else 'NOT identical - see CSV'}), median WAPE "
        f"{L_.loc[('ma3', 'all'), 'median_wape']:.3f}, MASE < {C.MASE_GATE_PIPELINE:g} (pipeline gate) for "
        f"{L_.loc[('ma3', 'all'), 'mase_pass_pct']:.0f}% of SKUs. Median WAPE at k = 3 / 12 / 24 / full history: "
        + "; ".join(f"{fam_lbl[f]} " + " / ".join(f"{L_.loc[(f, k), 'median_wape']:.3f}" for k in (3, 12, 24, "all"))
                    for f in CUTOFFS)
        + ". MASE < 1 share at the same k: "
        + "; ".join(f"{fam_lbl[f]} " + " / ".join(f"{L_.loc[(f, k), 'mase_pass_pct']:.0f}%" for k in (3, 12, 24, "all"))
                    for f in CUTOFFS)
        + ". Block wins against MA3 at any k: "
        + "; ".join(f"{fam_lbl[f]} {('k = ' + ', '.join(map(str, wins[f]))) if wins[f] else 'none'}" for f in CUTOFFS)
        + "; block losses: "
        + "; ".join(f"{fam_lbl[f]} {('k = ' + ', '.join(map(str, losses[f]))) if losses[f] else 'none'}" for f in CUTOFFS)
        + f". Current cutoffs: MA3 from 3, TSB from 12, XGBoost+MA3 avg from 24 sales months. MASE uses the untruncated "
          f"in-sample naive error, so only the forecast changes with k."
    )
    keep_cols = ["pk", "month", "ntr", "actual", "ma3", "scale"] + [f"{f}_k{k}" for f in ("tsb", "xgb_ma3") for k in KS + ["all"]]
    C.write_result(2, "truncation", "History truncation", {"lines": Ln, "verdicts": V, "forecasts": T[keep_cols]}, caption,
                   verdict, detail, [g4], "ch02_truncation.py",
                   extra=dict(data_notes=C.null_notes(series.keys()) + [gap_note, C.THREAD_NOTE], thread_gap=gap, thread_check=tc, amendment="reports/evidence/AMENDMENTS.csv (G4)", ks=KS, cutoffs={"ma3": 3, **CUTOFFS},
                              ma3_identical_for_all_k=ma3_flat, runtime_s=round(time.time() - t0),
                              xgb_nthread=1, blocks=[f"{a}..{b}" for a, b in C.BLOCKS]))


if __name__ == "__main__":
    main()
