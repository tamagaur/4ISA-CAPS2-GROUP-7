"""
Chart 6 panel "What we tried for these products" - a TALLY of stored per-product
results, nothing refitted or rescored.

Source (read only; local-only experiment branch, not merged):
  C:/Users/kyuan/dsd-transforms-experiment @ fce007e
    reports/experiments/target_transforms_2026-09-26/unfit_subset.csv    (phase 1)
    reports/experiments/differencing_phase2_2026-09-26/unfit_subset.csv  (phase 2)
Both hold, per unfit product and per method, the MASE on the common test window
2025-09..2026-02 (harness B_common_window) - the same window the not-fit verdict
(MASE >= 1.1, fit-review gate) is measured on. They cover the 25 products whose
verdict comes from that window; the 3 products scored on their own 20% holdout are
not comparable here and are left out.

"Rescued" = that method's MASE for the product is below 1.1 on that window (phase 2
stores the flag itself: below_1_1_common_window). Phase 2 also stores whether a rescue
held on the earlier half-year periods (holds_on_earlier_blocks); phase 1 did not check.

Models whose per-product results on these products are NOT stored (ETS, XGBoost
alone, Ridge, 12-month average, SBA) get a row saying so: they were scored only as a
group (reports/diagnostics/WHY_SOME_SKUS_ARE_UNFIT.md section 5: 0 of 50 passed).

Check: the served model's own MASE (mase_served) rescues 0 of the 25, and MA3
rescues 0 (it also fails on all 25) - otherwise the source is not what we think.
"""
import _common as C
import json
import os
import re
import subprocess

import pandas as pd

EXP = r"C:\Users\kyuan\dsd-transforms-experiment"
EXP_COMMIT = "fce007e"
P1 = os.path.join(EXP, "reports", "experiments", "target_transforms_2026-09-26", "unfit_subset.csv")
P2 = os.path.join(EXP, "reports", "experiments", "differencing_phase2_2026-09-26", "unfit_subset.csv")
GATE = C.MASE_GATE_FIT_REVIEW
ORDER = ["Ours: the served model", "TSB", "XGBoost + 3-month average", "Average of 3 simple methods", "Auto-ARIMA",
         "Auto-ARIMA on log sales", "Fixed SARIMA", "Spike capping (winsorize)", "Differencing",
         "Transforms (log, square root, ...)", "Transform + differencing"]
NOT_STORED = ["ETS", "XGBoost alone", "Ridge regression", "12-month average", "SBA"]


def group1(cand):
    m, t = cand.split("|")
    if t == "identity":
        return {"tsb": "TSB", "xgb_ma3_avg": "XGBoost + 3-month average", "comb_simple": "Average of 3 simple methods"}.get(m)
    if t == "winsor":
        return "Spike capping (winsorize)"
    if t == "diff1":
        return "Differencing"
    return "Transforms (log, square root, ...)"


def group2(cand):
    if cand in ("E1", "E2", "E3"):
        return {"E1": "Auto-ARIMA", "E2": "Auto-ARIMA on log sales", "E3": "Fixed SARIMA"}[cand]
    t = cand.split("|")[1]
    if t == "identity":
        return None                                   # phase 2 controls repeat phase 1's identity rows
    if re.match(r"^(D\d|S12|S12D1|AUTOd)$", t):
        return "Differencing"
    if "+D1" in t or "+S12" in t:
        return "Transform + differencing"
    if "winsor" in t:
        return "Spike capping (winsorize)"
    return "Transforms (log, square root, ...)"


def main():
    head = subprocess.run(["git", "-C", EXP, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", EXP, "status", "--porcelain", "--", "reports/experiments"], capture_output=True, text=True).stdout.strip()
    if head != EXP_COMMIT or dirty:
        C.fail("rescue", f"experiment worktree at {head} (expected {EXP_COMMIT}) or has local changes")
    a, b = pd.read_csv(P1), pd.read_csv(P2)
    A = a[(a.harness == "B_common_window") & (a.unfit_group == "common_window_unfit")].copy()
    B = b[(b.harness == "B_common_window") & (b.unfit_group == "common_window_unfit")].copy()
    n = A.product_key.nunique()
    first = A.drop_duplicates("product_key")
    served0, ma30 = int((first.mase_served < GATE).sum()), int((first.mase_ma3 < GATE).sum())
    ok = n == 25 and B.product_key.nunique() == 25 and served0 == 0 and ma30 == 0
    check = dict(id="R", **{"pass": ok}, detail=f"{n} products (expected 25); served model below {GATE:g} on {served0} (expected 0); "
                                                  f"MA3 below {GATE:g} on {ma30} (expected 0)")
    if not ok:
        C.fail("rescue", check["detail"])

    A["g"], A["rescued"], A["held"] = A.candidate.map(group1), A.mase < GATE, None
    B["g"], B["rescued"], B["held"] = B.candidate.map(group2), B.below_1_1_common_window == 1, B.holds_on_earlier_blocks == "yes"
    rows = [dict(approach=ORDER[0], methods=1, best_single_method=served0, any_method=served0, held_earlier="",
                 products=n, status="stored")]
    both = pd.concat([A[["g", "candidate", "product_key", "rescued", "held"]].assign(phase=1),
                      B[["g", "candidate", "product_key", "rescued", "held"]].assign(phase=2)])
    both = both[both.g.notna()]
    for g in ORDER[1:]:
        d = both[both.g == g]
        per = d[d.rescued].groupby(["phase", "candidate"]).product_key.nunique()
        p2 = d[(d.phase == 2) & d.rescued & (d.held == True)]  # noqa: E712
        rows.append(dict(approach=g, methods=int(d[["phase", "candidate"]].drop_duplicates().shape[0]),
                         best_single_method=int(per.max()) if len(per) else 0,
                         any_method=int(d[d.rescued].product_key.nunique()),
                         held_earlier=(str(int(p2.product_key.nunique())) if (d.phase == 2).any() else "not checked"),
                         products=n, status="stored"))
    for g in NOT_STORED:
        rows.append(dict(approach=g, methods="", best_single_method="", any_method="", held_earlier="", products=n,
                         status="not available from stored results (scored only as a group: 0 of 50 passed)"))
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(C.EVID, "ch06_rescue.csv"), index=False, lineterminator="\n")
    meta = dict(script="scripts/evidence/ch06_rescue.py",
                code_commit=C.git_sha(["scripts/evidence/ch06_rescue.py", "scripts/evidence/_common.py"]),
                source=f"dsd-transforms-experiment @ {EXP_COMMIT}: unfit_subset.csv (phase 1 and phase 2), harness B_common_window",
                rescued_means=f"MASE below {GATE:g} (the fit-review gate) on the common test window 2025-09..2026-02",
                products=n, check=check)
    with open(os.path.join(C.EVID, "ch06_rescue.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1); fh.write("\n")
    print(R.to_string(index=False)); print(check)


if __name__ == "__main__":
    main()
