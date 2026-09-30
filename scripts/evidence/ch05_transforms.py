"""
Chart 5 - target transforms: exploratory win rate across the 162 candidates vs chance.

Sources (read only; the experiment branch is local-only and is NOT merged):
  C:/Users/kyuan/dsd-transforms-experiment @ fce007e (experiment/target-transforms)
    reports/experiments/target_transforms_2026-09-26/results_by_bin.csv    phase 1 (35)
    reports/experiments/differencing_phase2_2026-09-26/results_by_bin.csv  phase 2 (77)
    reports/experiments/differencing_phase2_2026-09-26/SUMMARY.md          the rate table
  reports/experiment_artifacts/preds_plus.csv.gz (tracked here; same bytes as the
    experiment's copy) for the original 50, scored with the experiment's own code:
    run_experiment.py:1038-1053 (the existing-50 loop), label() :707-722, cells() /
    compare() :672-705 - copied verbatim below.

Harness A (bake-off, 5 half-year blocks), all SKUs, both baselines (MA3 and served),
testable cells only - the SUMMARY table's population.

Check G8, AMENDED 2026-09-30 (pre-approved by Yuan; source only, not criterion):
162 = 50 + 35 + 77 reconstructs - the original 50 from preds_plus.csv.gz, the 35 and
77 from results_by_bin.csv - and every count matches the SUMMARY table (testable cells,
exploratory, real, block wins / testable blocks). Any count that does not reconcile
stops the build.
Chance level: 2.5% per testable block, the one tail of a 95% interval.
"""
import _common as C
import os
import re
import subprocess

import numpy as np
import pandas as pd
from scipy.stats import beta

EXP = r"C:\Users\kyuan\dsd-transforms-experiment"
EXP_COMMIT = "fce007e"
D1 = os.path.join(EXP, "reports", "experiments", "target_transforms_2026-09-26")
D2 = os.path.join(EXP, "reports", "experiments", "differencing_phase2_2026-09-26")
PREDS_PLUS = os.path.join(C.REPO, "reports", "experiment_artifacts", "preds_plus.csv.gz")
CHANCE = 0.025

# ---- verbatim from run_experiment.py (fce007e) ---------------------------------
SEED, NBOOT, MIN_ORIG, MIN_N = 20260921, 1000, 3, 5
START, END, FULL0 = "2023-01", "2026-02", "2023-10"
BLOCKS = [("2023-10", "2024-02"), ("2024-03", "2024-08"), ("2024-09", "2025-02"),
          ("2025-03", "2025-08"), ("2025-09", "2026-02")]
SERVED_COL = {"short": "ma3", "medium": "tsb", "long": "ens_xgb_ma3@A"}
BINS = ("short", "medium", "long")


def cells(df, models):
    out = []
    for pk, grp in df.groupby("pk"):
        a = grp.actual.to_numpy()
        den = np.abs(a).sum()
        if len(grp) < MIN_ORIG or den <= 0:
            continue
        r = dict(pk=pk, n=len(grp))
        sc = grp.scale.to_numpy()
        ok = sc > 0
        for m in models:
            p = grp[m].to_numpy(dtype=float)
            fin = np.isfinite(p).all()
            r[m] = np.abs(a - p).sum() / den if fin else np.nan
            r["mase_" + m] = float(np.mean(np.abs(a - p)[ok] / sc[ok])) if fin and ok.any() else np.nan
        out.append(r)
    return pd.DataFrame(out) if out else pd.DataFrame(columns=["pk", "n"] + models + ["mase_" + m for m in models])


def compare(m, b):
    m, b = np.asarray(m, float), np.asarray(b, float)
    ok = np.isfinite(m) & np.isfinite(b)
    m, b = m[ok], b[ok]
    if len(m) < MIN_N:
        return dict(n=len(m), v="NT")
    i = np.random.default_rng(SEED).integers(0, len(m), (NBOOT, len(m)))
    d = np.median(m[i], axis=1) - np.median(b[i], axis=1)
    lo, hi = np.percentile(d, [2.5, 97.5])
    nb, nw = int((m < b - 1e-12).sum()), int((m > b + 1e-12).sum())
    v = "W" if (hi < 0 and nb > nw) else "L" if (lo > 0 and nw > nb) else "T"
    return dict(n=len(m), lo=lo, hi=hi, nb=nb, nw=nw, v=v, mv=np.median(m), bv=np.median(b))


def label(fam, verdict, blocks):
    if fam == "control":
        return "CONTROL"
    w = blocks.count("W") if blocks else 0
    testable = len(blocks) - blocks.count("N") if blocks else 0
    if verdict == "NT":
        lab = "NOT_TESTABLE"
    elif verdict == "W" and blocks and w * 2 > testable:
        lab = "REAL_WIN"                    # (a) full window, (b) majority of testable blocks, (c) all-SKU selection
    elif verdict == "W" or w > 0:
        lab = "EXPLORATORY_WIN"
    elif verdict == "L":
        lab = "LOSS"
    else:
        lab = "TIE"
    return f"SANITY_{lab}" if fam == "sanity" else lab


def existing50(P):  # run_experiment.py:1038-1053
    META = ["pk", "ti", "ntr", "sales", "adi", "bin", "scale", "actual", "month", "tier"]
    C50 = [c for c in P.columns if c not in META and c != "ma3"]
    ref = []
    for c in C50:
        for b in BINS:
            Db = P[P.bin == b]
            for base in ("ma3", "served"):
                bc = "ma3" if base == "ma3" else SERVED_COL[b]
                if bc == c:
                    continue
                full = cells(Db[(Db.month >= FULL0) & (Db.month <= END)], [c, bc])
                v = compare(full[c], full[bc])["v"] if len(full) else "NT"
                vs = "".join((compare(cb[c], cb[bc])["v"] if len(cb) else "NT")[0]
                             for cb in (cells(Db[(Db.month >= lo) & (Db.month <= hi)], [c, bc]) for lo, hi in BLOCKS))
                ref.append(dict(candidate=c, bin=b, baseline=base, verdict_full=v, blocks=vs, label=label("squeeze", v, vs)))
    return C50, pd.DataFrame(ref)
# ---- end verbatim ---------------------------------------------------------------


def summarise(df, name, n_candidates):
    t = df[~df.label.str.contains("NOT_TESTABLE|CONTROL|REFERENCE", regex=True)]
    blocks = t.blocks.fillna("")
    return dict(candidate_set=name, candidates=n_candidates, testable_cells=len(t),
                exploratory=int((t.label == "EXPLORATORY_WIN").sum()), real=int((t.label == "REAL_WIN").sum()),
                block_wins=int(blocks.str.count("W").sum()),
                testable_blocks=int((blocks.str.len() - blocks.str.count("N") - blocks.str.count("-")).sum()))


def summary_table():
    """The 'Exploratory rate' table in phase 2's SUMMARY.md, parsed (not typed)."""
    txt = open(os.path.join(D2, "SUMMARY.md"), encoding="utf-8").read()
    out = {}
    for key, pat in (("original 50", r"\| original 50 \|"), ("phase 1 (35)", r"\| phase 1 \(35\) \|"),
                     ("phase 2 (77)", r"\| \*\*phase 2 \(77\)\*\* \|")):
        line = next(ln for ln in txt.splitlines() if re.match(pat, ln))
        cols = [c.strip().replace("*", "") for c in line.strip("|").split("|")]
        bw = re.match(r"([\d,]+) / ([\d,]+)", cols[4])
        out[key] = dict(testable_cells=int(cols[1].replace(",", "")), exploratory=int(cols[2].split()[0]),
                        real=int(cols[3]), block_wins=int(bw.group(1).replace(",", "")),
                        testable_blocks=int(bw.group(2).replace(",", "")))
    n_total = int(re.search(r"= \*\*(\d+)\*\*", next(ln for ln in txt.splitlines() if "Candidates in all" in ln)).group(1))
    return out, n_total


def main():
    head = subprocess.run(["git", "-C", EXP, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", EXP, "status", "--porcelain", "--", "reports/experiments"], capture_output=True, text=True).stdout.strip()
    if head != EXP_COMMIT or dirty:
        C.fail("G8", f"experiment worktree is at {head} (expected {EXP_COMMIT}) or has local changes: {dirty[:200]}")

    P = pd.read_csv(PREDS_PLUS)                      # default parser, as run_experiment.py:935
    P["month"] = P.month.astype(str).str[:7]
    C50, ref = existing50(P)
    R1 = pd.read_csv(os.path.join(D1, "results_by_bin.csv"))
    R2 = pd.read_csv(os.path.join(D2, "results_by_bin.csv"))
    a1 = R1[(R1.harness == "A_bakeoff") & (R1.cohort == "all") & ~R1.family.isin(["control", "sanity"])]
    a2 = R2[(R2.harness == "A_bakeoff") & (R2.cohort == "all") & ~R2.group.isin(["control", "reference"])]
    n1, n2 = a1.candidate.nunique(), a2.candidate.nunique()
    in_csv = set(R1.candidate) | set(R2.candidate) | set(R1.model) | set(R2.model)
    fifty_in_csv = sorted(set(C50) & in_csv)

    got = {"original 50": summarise(ref, "original 50", len(C50)),
           "phase 1 (35)": summarise(a1, "phase 1 (35)", n1),
           "phase 2 (77)": summarise(a2, "phase 2 (77)", n2)}
    want, n_total = summary_table()
    diffs = [(k, f, got[k][f], want[k][f]) for k in want for f in want[k] if got[k][f] != want[k][f]]
    counts_ok = (len(C50), n1, n2) == (50, 35, 77) and len(C50) + n1 + n2 == n_total == 162
    ok = counts_ok and not diffs
    checks = [dict(id="G8", **{"pass": ok},
                   detail=f"candidates {len(C50)} + {n1} + {n2} = {len(C50) + n1 + n2} (SUMMARY: {n_total}); the original 50 are "
                          f"not in results_by_bin.csv ({len(fifty_in_csv)} of their names appear there) and are scored from "
                          f"preds_plus.csv.gz with run_experiment.py's own loop; SUMMARY table counts "
                          + ("all match" if not diffs else f"DIFFER: {diffs}"))]
    if not ok:
        C.fail("G8", checks[0]["detail"])

    S = pd.DataFrame(got.values())
    tot = dict(candidate_set="all 162", candidates=int(S.candidates.sum()), testable_cells=int(S.testable_cells.sum()),
               exploratory=int(S.exploratory.sum()), real=int(S.real.sum()), block_wins=int(S.block_wins.sum()),
               testable_blocks=int(S.testable_blocks.sum()))
    S = pd.concat([S, pd.DataFrame([tot])], ignore_index=True)
    S["block_win_rate"] = S.block_wins / S.testable_blocks
    S["cp_lo"] = [beta.ppf(0.025, x, n - x + 1) if x > 0 else 0.0 for x, n in zip(S.block_wins, S.testable_blocks)]
    S["cp_hi"] = [beta.ppf(0.975, x + 1, n - x) if x < n else 1.0 for x, n in zip(S.block_wins, S.testable_blocks)]
    S["exploratory_rate"] = S.exploratory / S.testable_cells
    S["chance_per_block"] = CHANCE

    T = S[S.candidate_set == "all 162"].iloc[0]
    flawed = T.real > 0 or T.cp_lo > CHANCE
    verdict = "FLAWED" if flawed else "CONFIRMS"
    detail = (f"real wins {int(T.real)}; pooled block-win rate {T.block_win_rate:.2%} "
              f"(95% CI {T.cp_lo:.2%}-{T.cp_hi:.2%}) vs chance {CHANCE:.1%}: lower bound "
              + ("ABOVE" if T.cp_lo > CHANCE else "not above") + " chance")
    caption = (
        f"Target transforms and the earlier candidates, bake-off harness (5 half-year blocks), all SKUs, against MA3 and against "
        f"the served model, testable cells only. {int(T.candidates)} candidates: "
        + "; ".join(f"{r.candidate_set} - {r.block_wins} block wins in {r.testable_blocks:,} testable blocks "
                    f"({r.block_win_rate:.1%}, 95% CI {r.cp_lo:.1%}-{r.cp_hi:.1%}), {r.exploratory} exploratory and {r.real} real "
                    f"wins in {r.testable_cells} cells" for r in S.itertuples() if r.candidate_set != "all 162")
        + f". Pooled: {int(T.block_wins)} of {int(T.testable_blocks):,} blocks ({T.block_win_rate:.1%}, 95% CI "
          f"{T.cp_lo:.1%}-{T.cp_hi:.1%}) against a chance level of {CHANCE:.1%} per block (the one tail of a 95% interval). "
          f"A real win needs the full window and a majority of testable blocks; there are {int(T.real)}. "
          f"Source: local-only experiment branch at {EXP_COMMIT} (not merged); the original 50 re-scored here from "
          f"preds_plus.csv.gz with that experiment's own code."
    )
    C.write_result(5, "transforms", "Target transforms", {"rates": S, "original50_cells": ref}, caption, verdict, detail, checks,
                   "ch05_transforms.py",
                   extra=dict(data_notes=C.null_notes(P.pk.unique()), chance_per_block=CHANCE, experiment_commit=EXP_COMMIT,
                              amendment="reports/evidence/AMENDMENTS.csv (G8)"))


if __name__ == "__main__":
    main()
