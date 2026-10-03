"""
Chart 4 - XGBoost+MA3 blend weight. forecast_w = w * xgb_abs@A + (1 - w) * ma3,
w = 0.0..1.0 step 0.1, long bin (where the average is served), on the stored
bake-off forecasts. Arithmetic on stored columns: nothing is refitted.
w = 0.5 is the served average; w = 0 is MA3. The stored artifact applies no
max-history guard (neither does this chart). WAPE only: no MASE gate is used.

Check (pre-registered): G2  w = 0.5 equals ens_xgb_ma3@A and w = 0 equals ma3
(max abs diff < 1e-9).
"""
import _common as C
import numpy as np
import pandas as pd

WEIGHTS = [round(0.1 * i, 1) for i in range(11)]
col = lambda w: f"w{w:.1f}"  # noqa: E731


def main():
    A = C.load_preds()
    L = A[A.bin == "long"].copy()
    for w in WEIGHTS:
        L[col(w)] = w * L["xgb_abs@A"] + (1 - w) * L["ma3"]
    d_half = float(np.nanmax(np.abs(L[col(0.5)] - L["ens_xgb_ma3@A"])))
    d_zero = float(np.nanmax(np.abs(L[col(0.0)] - L["ma3"])))
    nan_mis = int((L[col(0.5)].isna() != L["ens_xgb_ma3@A"].isna()).sum())
    ok = d_half < 1e-9 and d_zero < 1e-9 and nan_mis == 0
    checks = [dict(id="G2", **{"pass": ok}, detail=f"max |w0.5 - ens_xgb_ma3@A| = {d_half:.3g}, max |w0.0 - ma3| = {d_zero:.3g}, "
                                                   f"NaN mismatches {nan_mis} (on {len(L)} long-bin SKU-months)")]
    if not ok:
        C.fail("G2", checks[0]["detail"])

    others = [w for w in WEIGHTS if w != 0.5]
    V = pd.concat([C.block_table(L, col(w), col(0.5), dict(cohort="long", weight=w, against="w=0.5")) for w in others]
                  + [C.block_table(L, col(w), "ma3", dict(cohort="long", weight=w, against="MA3")) for w in WEIGHTS if w != 0.0],
                  ignore_index=True)
    lines = []
    for lo, hi in [C.FULL] + C.BLOCKS:
        c = C.cells(C.in_window(L, lo, hi), [col(w) for w in WEIGHTS])
        c = c.dropna(subset=[col(w) for w in WEIGHTS]) if len(c) else c
        for w in WEIGHTS:
            lines.append(dict(window="full" if (lo, hi) == C.FULL else f"{lo}..{hi}", start=lo, end=hi, weight=w, n=len(c),
                              median_wape=float(c[col(w)].median()) if len(c) else np.nan))
    Ln = pd.DataFrame(lines)

    vs05 = V[V.against == "w=0.5"]
    tests = {w: C.majority(vs05[(vs05.weight == w) & (vs05.window != "full")].verdict.tolist(), "W") for w in others}
    flawed = [w for w, (hit, _) in tests.items() if hit]
    verdict = "FLAWED" if flawed else "CONFIRMS"
    testable = tests[others[0]][1].split(" of ")[1].split(" ")[0]
    detail = (f"weights beating w=0.5 in a majority of testable long-bin blocks: {flawed or 'none'} "
              f"({testable} of {len(C.BLOCKS)} blocks testable)")

    full = Ln[Ln.window == "full"].set_index("weight")
    best = full.median_wape.idxmin()
    strip = lambda w, ag: "".join(v if v != "NT" else "-" for v in V[(V.weight == w) & (V.against == ag) & (V.window != "full")].verdict)  # noqa: E731
    caption = (
        f"Blend weight on XGBoost in the XGBoost+MA3 average (w = 0 is MA3, w = 0.5 is served, w = 1 is XGBoost alone), long bin, "
        f"{L.pk.nunique()} Unilever Tier A SKUs (ABC 2026-02, single), stored rolling one-step forecasts, real data only. "
        f"The long bin exists only from {L.month.min()}, so {testable} of the {len(C.BLOCKS)} half-year blocks are testable. "
        f"Median WAPE over {L.month.min()}..{L.month.max()} ({int(full.n.iloc[0])} SKUs): "
        + ", ".join(f"w={w:.1f} {full.loc[w, 'median_wape']:.3f}" for w in WEIGHTS)
        + f"; lowest at w={best:.1f}. Against w=0.5 by block (two-condition WAPE test, seed {C.SEED}): "
        + ", ".join(f"w={w:.1f} {strip(w, 'w=0.5')}" for w in others)
        + ". " + ("No weight beats w=0.5 in a majority of testable blocks." if not flawed
                  else f"w = {', '.join(f'{w:.1f}' for w in flawed)} beat(s) w=0.5 in a majority of testable blocks.")
    )
    C.write_result(4, "blend", "XGBoost+MA3 blend weight", {"lines": Ln, "verdicts": V}, caption, verdict, detail, checks,
                   "ch04_blend.py", extra=dict(data_notes=C.null_notes(L.pk.unique()) + [C.THREAD_NOTE], weights=WEIGHTS,
                                                 blocks=[f"{a}..{b}" for a, b in C.BLOCKS]))


if __name__ == "__main__":
    main()
