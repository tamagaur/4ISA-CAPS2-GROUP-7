"""
Chart 7 - ABC Pareto per principal, latest period. Cumulative revenue share vs rank,
from the stored ABC_Classification rows (inputs/abc_latest.csv; nothing recomputed).
Cut points 0.80 / 0.95: analytics/classification/abc.py:56-57.
Unilever: SKU grain, methods single and t3m at 2026-02. Del Monte: category grain,
method single only (no t3m row exists in ABC_Classification for Del Monte).
Descriptive: no decision threshold is on record for single vs t3m.

Check G6, AMENDED 2026-09-30 (reports/evidence/AMENDMENTS.csv; approved by Yuan; the
column changed, not the criterion): Unilever single 2026-02 gives 132 Tier A SKUs;
the sum of their stored revenue_share = 0.7996 (DEC-22's 79.96%); the stored
cumulative_share of the last Tier A SKU <= 0.80 < that of the first Tier B SKU.
(The original read 0.7996 from cumulative_share, which is accumulated before
rounding and stores 0.7999.)
"""
import _common as C
import os
import sys

import pandas as pd

sys.path.insert(0, C.REPO)
from analytics.classification.abc import TIER_A_CUTOFF, TIER_B_CUTOFF  # noqa: E402


def main():
    a = pd.read_csv(os.path.join(C.INPUTS, "abc_latest.csv"))
    a["label"] = a.sku_code.fillna(a.category_path).astype(str)
    a = a.sort_values(["principal", "method", "cumulative_share", "revenue_share"], ascending=[True, True, True, False])
    a["rank"] = a.groupby(["principal", "method"]).cumcount() + 1
    a["n_items"] = a.groupby(["principal", "method"]).pk.transform("size")
    a["rank_share"] = a["rank"] / a.n_items

    us = a[(a.principal == "unilever") & (a.method == "single") & (a.period == "2026-02")]
    nA = int((us.tier == "A").sum())
    sumA = round(float(us[us.tier == "A"].revenue_share.sum()), 4)
    cumA = float(us[us.tier == "A"].cumulative_share.max())
    cumB = float(us[us.tier == "B"].cumulative_share.min())
    ok = nA == 132 and sumA == 0.7996 and cumA <= TIER_A_CUTOFF < cumB
    checks = [dict(id="G6", **{"pass": ok},
                   detail=f"Unilever single 2026-02: {nA} Tier A SKUs (expected 132); sum of stored revenue_share {sumA:.4f} "
                          f"(expected 0.7996, DEC-22); stored cumulative_share last A {cumA:.4f} <= {TIER_A_CUTOFF:.2f} < first B "
                          f"{cumB:.4f}: {cumA <= TIER_A_CUTOFF < cumB}")]
    if not ok:
        C.fail("G6", checks[0]["detail"])

    tiers = a.groupby(["principal", "method", "period", "tier"]).size().unstack(fill_value=0).reset_index()
    ul = a[a.principal == "unilever"].pivot_table(index="pk", columns="method", values="tier", aggfunc="first")
    both = ul.dropna()
    moves = both.groupby(["single", "t3m"]).size().rename("n").reset_index()
    changed = int((both.single != both.t3m).sum())
    only_s, only_t = int(ul.t3m.isna().sum()), int(ul.single.isna().sum())
    a_changed = int(((both.single == "A") != (both.t3m == "A")).sum())

    def tier_txt(p, m):
        r = tiers[(tiers.principal == p) & (tiers.method == m)].iloc[0]
        return f"{int(r.get('A', 0))} A / {int(r.get('B', 0))} B / {int(r.get('C', 0))} C of {int(r.A + r.B + r.C)}"

    dm_period = a[a.principal == "delmonte"].period.iloc[0]
    dm = a[a.principal == "delmonte"]
    caption = (
        f"ABC Pareto at each principal's latest classification period, from the stored ABC_Classification rows: cumulative "
        f"revenue share against rank, cut points {TIER_A_CUTOFF:.2f} and {TIER_B_CUTOFF:.2f} (abc.py). Unilever 2026-02, SKU "
        f"grain: single {tier_txt('unilever', 'single')}; trailing-3-month (t3m) {tier_txt('unilever', 't3m')}. Of the "
        f"{len(both)} SKUs classified by both methods, {changed} change class ({a_changed} move into or out of Tier A); "
        f"{only_s} are classified only by single and {only_t} only by t3m. Del Monte {dm_period}, category grain, single only "
        f"(no t3m rows exist): {tier_txt('delmonte', 'single')} - "
        + ", ".join(f"{r.label} {r.revenue_share:.1%}" for r in dm.itertuples())
        + f". Del Monte's category vocabulary changed in January 2025, so {len(dm)} categories is the post-change count. "
          f"The Unilever forecast cohort is Tier A as of 2026-02 (single): {nA} SKUs; their stored revenue shares sum to "
          f"{sumA:.2%} (DEC-22's figure), while the stored cumulative share of the last of them reads {cumA:.2%} because it is "
          f"accumulated before rounding; the first Tier B SKU sits at {cumB:.2%}. The curve plots the stored cumulative share."
    )
    C.write_result(7, "pareto", "ABC Pareto", {"curve": a[["principal", "method", "period", "rank", "n_items", "rank_share", "pk",
                                                            "label", "tier", "revenue_share", "cumulative_share", "boundary_flag"]],
                                                "tiers": tiers, "unilever_moves": moves},
                   caption, "DESCRIPTIVE", f"no threshold on record; {changed} Unilever SKUs change class single vs t3m",
                   checks, "ch07_pareto.py", extra=dict(data_notes=[], cutoffs=[TIER_A_CUTOFF, TIER_B_CUTOFF],
                                                         tierA_sum_revenue_share=sumA, tierA_last_cumulative=cumA,
                                                         tierB_first_cumulative=cumB, amendment="reports/evidence/AMENDMENTS.csv (G6)"))


if __name__ == "__main__":
    main()
