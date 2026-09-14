# Tier-A stability & category-label readiness — 2026-09-09

Read-only. Phase 0 follow-up round 2. No code, schema, or DB changes.
Scripts: `scratchpad/tierA_stability.py`, `scratchpad/category_checks.py`.
**Cohort convention from here on:** every reference states its period —
"Tier A as of 2026-02" (= 132 SKUs), never bare "Tier A".

---

## Headline

The Tier-A count swing (89 → 149 → 132 over 2025-12 → 2026-01 → 2026-02) is a
**churning boundary around a small stable core**, not wholesale instability.

- **Stable core: ~49 SKUs** — 21 are Tier A in **all 38** periods, another 28 in
  **≥30** periods. These are 100% long-history (≥36 months) and 100% smooth
  (ADI median 1.00, CV² 0.08). This is the real "Category A".
- The remaining ~80–100 SKUs in any given month's Tier A are drawn from a pool of
  **366 "occasional" SKUs** (1–29 periods each, median 7). These are shorter
  history (median 16 months, 40% under 12) and mostly not smooth (only 20%).
- The month-to-month count moves with **how many SKUs sell** and **how
  concentrated revenue is** that month — not with total revenue.
- **2025-12 (A=89) is a genuine anomaly** and must not anchor any decision.

**Implication for Phase 2 (ABC recompute) and Phase 3 (clustering):** a
single-calendar-month Tier A is inherently unstable at the boundary. Recommend
Phase 2 also computes a **trailing-3-month ABC** as the cohort of record for
forecasting/LP; the clustering test in Phase 3 should treat the stable core and
the boundary pool as distinct populations, not one cluster space.

---

## 1. Membership frequency (across all 38 ABC periods)

| Bucket | SKUs | Profile |
|---|---|---|
| Tier A in **all 38** periods | **21** | permanent core |
| Tier A in **30–37** periods | **28** | near-permanent |
| Tier A in **1–29** periods | **366** | churning pool (median 7 periods) |
| **never** Tier A | 1,116 | |
| **ever** Tier A | **415** | of 1,807 demand SKUs |

Any single month's Tier A (~110–150 SKUs) = the ~49 core + a rotating ~60–100 from
the 366-SKU pool.

## 2. Buckets × cluster axes (history length × demand shape) — **hypothesis holds**

Hypothesis: always-Tier-A = long-history + smooth; occasional = short-history +
intermittent.

| Bucket | months w/ sales (median) | ≥36 mo | <12 mo | ADI (med) | CV² (med) | smooth | lumpy |
|---|---|---|---|---|---|---|---|
| all_38 (n=21) | 38 | 100% | 0% | 1.00 | 0.08 | **100%** | 0% |
| ≥30 (n=28) | 34 | ~36% | 0% | 1.12 | 0.11 | **100%** | 0% |
| occasional 1–29 (n=366) | 16 | — | **40%** | 2.24 | 0.24 | **20%** | 24% |

The core is unambiguously long-history and smooth. The churn pool is exactly the
short-history / intermittent population. Confirmed.

## 3. Churn detail — 2025-12 → 2026-01 → 2026-02

| Step | A count | entered | exited | stayed |
|---|---|---|---|---|
| 2025-12 → 2026-01 | 89 → 149 | **+71** | −11 | 78 |
| 2026-01 → 2026-02 | 149 → 132 | +24 | **−41** | 108 |

- **2025-12 → 2026-01 (+71):** dominated by SKUs that barely sold in December
  entering a normal January. 26 of the 71 entrants have <12 months of history;
  several top entrants (`65247611`, `65247609`, …) have **2 months** of history
  and did not sell at all in 2025-12 (rank None → rank ~10–35 in 2026-01). The
  jump is a rebound + new-SKU activation, not a real doubling of the core.
- **2026-01 → 2026-02 (−41):** more ordinary boundary churn; a few long-history
  SKUs (`65004623` hist=38, `69668142` hist=32) drop out at revenue ranks ~110–150.

The stable core stayed Tier A through all three months. All churn is at the
revenue-rank ~90–150 boundary.

## 4. Does the swing track total revenue? — **No; it tracks distribution shape**

| period | A | total_rev | top10_share | HHI | n_selling |
|---|---|---|---|---|---|
| 2025-12 | 89 | ₱19.2M (lowest of 38) | 0.342 (highest) | 0.0179 (highest) | 597 (lowest) |
| 2026-01 | 149 | ~₱33M | ~0.24 | 0.0115 | 746 (highest) |
| 2026-02 | 132 | ~₱31M | ~0.26 | ~0.013 | ~690 |

Correlations (A count vs metric, across all 38 periods):

| metric | corr | reading |
|---|---|---|
| total revenue | **+0.31** | weak — not the driver |
| top-10 revenue share | **−0.60** | more concentrated → fewer SKUs reach 80% cutoff |
| HHI | **−0.74** | strongest single signal |
| n SKUs selling that month | **+0.70** | more breadth → more SKUs in Tier A |

When revenue concentrates into a few SKUs (a big-order month, or a thin month),
fewer SKUs are needed to reach the 80% cumulative cutoff, so Tier A shrinks —
purely mechanical from the Pareto rule.

## 5. `_split_negative_revenue` clamp — minor contributor, not the driver

The clamp-to-zero of negative monthly `net_amount` (`orchestrate_abc.py:176-177`):

- Mean **44 SKUs/month** have negative `net_amount` (returns > sales that month).
- Of those, mean **1.1/month** were Tier A the prior period — so the clamp
  typically knocks ~1 SKU off the Tier-A boundary per month.
- corr(n negative-rev SKUs, A count) = **−0.34** — weak-moderate.
- **Exception — 2025-12:** 90 SKUs negative, −₱1.11M total, **8 of them were Tier A
  in 2025-11**. This compounds the December dip but is not its primary cause
  (the concentration + low breadth above dominate).

The clamp is real and worth fixing in Phase 2 (the comment/behavior mismatch), but
it is not what makes Tier A swing 89–149. Deciding clamp-vs-exclude changes ~1
boundary SKU/month in normal months, ~8 in the 2025-12 outlier.

---

## Category-label readiness (round-1 follow-through)

### UNCLASSIFIED bucket revenue share — **immaterial**

The 380 Unilever demand SKUs with no SOH row (so no `CATEGORY DESC`):

| metric | value |
|---|---|
| share of all-time Unilever revenue (2023-01→2026-02) | **0.2%** (₱1.95M / ₱1,231M) |
| share of 2026-02 revenue | **0.2%** |
| Tier A as of 2026-02 | **0 of 380** |
| revenue covered by the 1,427 labelled SKUs | **99.8%** |

**The `<8%` target is dropped as moot** — the residual is a rounding error and
contains zero A-tier SKUs. An `UNCLASSIFIED` bucket is still needed structurally,
but it will never carry a decision-relevant SKU.

### Description-keyword rule — out-of-sample validation

Method: 1,427 labelled SKUs split **70/30** (seed 42) → train 998, test 429.
Per-token `P(category | token)` learned on train only (pack/size tokens stripped);
predict on held-out test by summing per-token category probabilities.

| threshold | coverage | accuracy | error |
|---|---|---|---|
| all predictions | 100% (429/429) | **94.6%** | 5.4% |
| confidence ≥ 0.5 | 96% | 95.6% | 4.4% |
| confidence ≥ 0.6 | 89% | **97.4%** | 2.6% |
| confidence ≥ 0.7 | 74% | 98.7% | 1.3% |

Top mislabels are near-synonym category pairs (`DRESSINGS`↔`CONDIMENTS` ×12,
`SCRATCH COOKING AIDS`↔`COOKING AIDS` ×3, `SKIN CLEANSING`↔`DEODORANTS &
FRAGRANCES`) — i.e. taxonomy granularity, not gross errors.

**Recommended Phase 1c fallback rule:**
1. Direct SOH-snapshot `CATEGORY DESC` (DEC-21 most-recent) — covers 79.0%.
2. Keyword rule **at confidence ≥ 0.6** for SKUs failing step 1 — ~2.6% error on
   the ~89% it covers.
3. `UNCLASSIFIED` for the rest (immaterial by revenue).

Reproducible: the keyword table is built from `staging/ssis_soh` + the labelled
set, committed as a fixture, regenerated in Load. No hand-mapping.

---

## What changed in the plan doc

`yeah-thats-rigth-so-virtual-hollerith.md`:
- ground-truth table: `36` → `38` ABC periods, + the swing/core note.
- Phase 1d verification: `category_path` coverage split into direct 79.0% /
  keyword 94.6% OOS / `UNCLASSIFIED` (0.2% rev); `<8%` target dropped.
- Phase 1d: added the `check_reject_rate_gate` caveat — it measures only
  Extract-stage file rejects (currently an empty list → passes at 0%), does not
  see the 805 `ssis_summary` / 921 transform rejects, and is **not** evidence of
  transform-stage quality.

## Still at the gate

No Phase 1 work started. Nothing prescriptive. Awaiting review.
