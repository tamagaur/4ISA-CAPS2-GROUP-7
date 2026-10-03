"""
Chart 3 - MA3 window. MA2 / MA6 / MA12 vs MA3, median WAPE per half-year block,
ALL cohort, on the stored bake-off forecasts (candidate_search_tierA_preds.csv.gz).
Nothing is refitted. WAPE only: no MASE gate is used.
"""
import _common as C
import numpy as np
import pandas as pd

WINDOWS = {"ma2": "MA2", "ma3": "MA3", "ma6": "MA6", "ma12": "MA12"}
ALTS = [m for m in WINDOWS if m != "ma3"]


def main():
    A = C.load_preds()
    V = pd.concat([C.block_table(A, m, "ma3", dict(cohort="ALL")) for m in ALTS], ignore_index=True)
    V["model_label"] = V.model.map(WINDOWS)
    lines = []
    for lo, hi in [C.FULL] + C.BLOCKS:
        c = C.cells(C.in_window(A, lo, hi), list(WINDOWS)).dropna(subset=list(WINDOWS))
        for m in WINDOWS:
            lines.append(dict(window="full" if (lo, hi) == C.FULL else f"{lo}..{hi}", start=lo, end=hi, model=m,
                              model_label=WINDOWS[m], n=len(c), median_wape=float(c[m].median()) if len(c) else np.nan))
    Ln = pd.DataFrame(lines)

    tests = {}
    for m in ALTS:
        t = V[V.model == m]
        full_w = t[t.window == "full"].verdict.iloc[0] == "W"
        maj, txt = C.majority(t[t.window != "full"].verdict.tolist(), "W")
        tests[WINDOWS[m]] = (full_w and maj, f"full window {t[t.window == 'full'].verdict.iloc[0]}, W in {txt}")
    flawed = [k for k, (hit, _) in tests.items() if hit]
    verdict = "FLAWED" if flawed else "CONFIRMS"
    detail = "; ".join(f"{k} beats MA3: {'YES' if hit else 'no'} ({txt})" for k, (hit, txt) in tests.items())

    full = Ln[Ln.window == "full"].set_index("model")
    strip = lambda m: "".join(v if v != "NT" else "-" for v in V[(V.model == m) & (V.window != "full")].verdict)  # noqa: E731
    fv = lambda m: V[(V.model == m) & (V.window == "full")].iloc[0]  # noqa: E731
    caption = (
        f"Moving-average window, median WAPE per half-year block, {A.pk.nunique()} Unilever Tier A SKUs (ABC 2026-02, single), "
        f"stored rolling one-step forecasts, real data only. Over {C.FULL[0]}..{C.FULL[1]} on the {int(full.n.iloc[0])} SKUs all "
        f"four windows can score: " + ", ".join(f"{WINDOWS[m]} {full.loc[m, 'median_wape']:.3f}" for m in WINDOWS)
        + f". Against MA3 (two-condition WAPE test, seed {C.SEED}), full window then blocks: "
        + "; ".join(f"{WINDOWS[m]} {fv(m).verdict} [{fv(m).ci_lo:+.3f}, {fv(m).ci_hi:+.3f}], "
                    f"{int(fv(m).n_better)} better / {int(fv(m).n_worse)} worse, blocks {strip(m)}" for m in ALTS)
        + ". " + ("No window beats MA3 on the full window and in a majority of blocks." if not flawed
                  else f"{', '.join(flawed)} beat(s) MA3 on the full window and in a majority of blocks.")
    )
    C.write_result(3, "ma_window", "MA3 window", {"lines": Ln, "verdicts": V}, caption, verdict, detail, [],
                   "ch03_ma_window.py", extra=dict(data_notes=C.null_notes(A.pk.unique()), models=WINDOWS,
                                                     blocks=[f"{a}..{b}" for a, b in C.BLOCKS]))


if __name__ == "__main__":
    main()
