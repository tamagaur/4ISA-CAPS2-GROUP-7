"""
Imports two STORED side results into reports/evidence/ for the Evidence page, read
only from local branches that are not merged. Nothing is recomputed.

1. Card 2 - the direct cut-off test (exp/cutoff-12, C:/Users/kyuan/dsd-cutoff-test):
   reports/evidence/cutoff12_results.csv and RESULT_cutoff12.md at 8515d2b
   (pre-registered at 14657c2). Copied to ch02_cutoff12_results.csv; the verdict line
   of RESULT_cutoff12.md goes into ch02_cutoff12.json with the source commit.
2. Card 5 - the candidate names of the transforms experiment
   (experiment/target-transforms, C:/Users/kyuan/dsd-transforms-experiment @ fce007e):
   results_by_bin.csv of phase 1 and phase 2, harness A, cohort all, controls/sanity/
   references excluded - the populations chart 5 already counts. Written to
   ch05_candidate_names.csv so the card can name examples from stored names only.
Each source must be at its expected commit with no local changes to the files read.
"""
import _common as C
import json
import os
import re
import subprocess

import pandas as pd

CUT = r"C:\Users\kyuan\dsd-cutoff-test"
CUT_COMMIT = "8515d2b"
EXP = r"C:\Users\kyuan\dsd-transforms-experiment"
EXP_COMMIT = "fce007e"


def at_commit(repo, commit, paths):
    head = subprocess.run(["git", "-C", repo, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--", *paths], capture_output=True, text=True).stdout.strip()
    if head != commit or dirty:
        C.fail("import", f"{repo} is at {head} (expected {commit}) or has local changes in {paths}")


def main():
    # 1. cut-off test
    at_commit(CUT, CUT_COMMIT, ["reports/evidence"])
    res = pd.read_csv(os.path.join(CUT, "reports", "evidence", "cutoff12_results.csv"))
    md = open(os.path.join(CUT, "reports", "evidence", "RESULT_cutoff12.md"), encoding="utf-8").read()
    m = re.search(r"\*\*Verdict: (\w[\w -]*)\.\*\*", md)
    if not m or len(res) != 12:
        C.fail("import", "cutoff-12 result file does not have the expected verdict line or 12 result rows")
    status = re.search(r"## Status\s+(.+?)\n", md)
    res.to_csv(os.path.join(C.EVID, "ch02_cutoff12_results.csv"), index=False, lineterminator="\n")
    meta = dict(source=f"C:/Users/kyuan/dsd-cutoff-test (branch exp/cutoff-12) @ {CUT_COMMIT}: reports/evidence/cutoff12_results.csv, RESULT_cutoff12.md",
                prereg_commit="14657c2", verdict=m.group(1), status=status.group(1).strip() if status else "",
                script="scripts/evidence/import_side_results.py",
                code_commit=C.git_sha(["scripts/evidence/import_side_results.py", "scripts/evidence/_common.py"]))
    with open(os.path.join(C.EVID, "ch02_cutoff12.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1); fh.write("\n")
    print("cutoff-12:", meta["verdict"], "|", len(res), "rows")

    # 2. candidate names
    d1 = os.path.join(EXP, "reports", "experiments", "target_transforms_2026-09-26", "results_by_bin.csv")
    d2 = os.path.join(EXP, "reports", "experiments", "differencing_phase2_2026-09-26", "results_by_bin.csv")
    at_commit(EXP, EXP_COMMIT, ["reports/experiments"])
    R1, R2 = pd.read_csv(d1), pd.read_csv(d2)
    a1 = R1[(R1.harness == "A_bakeoff") & (R1.cohort == "all") & ~R1.family.isin(["control", "sanity"])]
    a2 = R2[(R2.harness == "A_bakeoff") & (R2.cohort == "all") & ~R2.group.isin(["control", "reference"])]
    o50 = pd.read_csv(os.path.join(C.EVID, "ch05_original50_cells.csv"))
    names = pd.concat([
        pd.DataFrame({"set": "original 50", "candidate": sorted(o50.candidate.unique()), "base": "", "part": ""}),
        a1[["candidate", "model", "transform"]].drop_duplicates().rename(columns={"model": "base", "transform": "part"}).assign(set="phase 1 (35)"),
        a2[["candidate", "model", "variant", "group"]].drop_duplicates("candidate").assign(part=lambda d: d.group + ":" + d.variant.astype(str))
          .rename(columns={"model": "base"})[["candidate", "base", "part"]].assign(set="phase 2 (77)"),
    ], ignore_index=True)[["set", "candidate", "base", "part"]]
    counts = names.groupby("set").candidate.nunique().to_dict()
    if counts != {"original 50": 50, "phase 1 (35)": 35, "phase 2 (77)": 77}:
        C.fail("import", f"candidate counts {counts} do not match 50 / 35 / 77")
    names.to_csv(os.path.join(C.EVID, "ch05_candidate_names.csv"), index=False, lineterminator="\n")
    print("candidate names:", counts)


if __name__ == "__main__":
    main()
