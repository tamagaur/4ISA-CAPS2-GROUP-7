# Calendar adjustment: selection protocol (declared 2026-11-16, before any result for these candidates)

Why: the live settings (shrink 0.5, product grain, own-years weight 2, December rule) were each chosen by scoring on the
windows they are reported on. This file fixes how every setting is chosen so that no setting is scored on data that chose it.
Its sha256 is printed and stored by `scripts/calendar_selection.py` before any scoring and written beside every result.

## Data and base forecasts
- Demand: `Unilever_SKU_Demand_Fact_Real`, read-only (transaction-scoped READ ONLY), through `fetch_demand`.
- Base forecasts: the cached as-served panel with NO calendar factor (`local/accuracy_as_served_rows.csv`, run `as_served`;
  Tier A the month before each month, 4,370 product-months, 2024-01..2026-02, succession/fading treatments and the dead-SKU
  rule in). A candidate factor multiplies `value_before_dead` (zero where the dead rule fired). Treatments are applied after
  the factor in the router, so this is an approximation for the ~7% treated rows; the final rehearsal reruns the real pipeline.
- A factor for target month t reads only months before t (causal), for every candidate, in every fold.

## Candidates (the whole grid; nothing is added after a result is seen)
- Shrink s in {0, 0.1, ..., 1.0} (log-space: f = exp(s * log f_full)).
- Grain: company total; product-median ratio; product own-ratio pulled toward the median with weight n/(n+k), k in {1, 2, 4}.
- Averaging across earlier years: geometric mean; median.
- December rule: off; on (last December's product median in full when below 1).
- Consistency gate (per target month): factor 1 unless every earlier year's ratio is on the same side of 1; and the variant
  "factor 1 when the company ratio and the product median disagree in direction".
- Mechanism B (seasonal index): month / mean of its calendar year (complete years only), product median; factor = index(target
  month) / mean(index of the 3 months before it), earlier complete years only.
- Prior-months window fixed at 3 (the trailing level MA3 uses). Not tuned.

## Selection and test (forward chaining; the score is the system's own measure, pooled WAPE on identical product-months)
Targets with no earlier year have factor 1 in every candidate, so they carry no information and are not counted as evidence.
- T1: choose on targets 2024-04..2025-02, test on 2025-03..2025-08 (holds March 2025 and July 2025).
- T2: choose on targets 2024-04..2025-08, test on 2025-09..2026-02 (holds the December 2025 and January 2026 rebound).
- T3 (secondary, reverse): choose on 2025-01..2026-02, test on 2024-04..2024-12. Uses later years to choose; reported as a check, never as the headline.
- FINAL: choose on all targets 2024-04..2026-02; applied to March 2026. No held-out score exists for it; the T1/T2 scores are its evidence.
- Rule for choosing: lowest pooled WAPE on the choosing window; a candidate within 0.1 WAPE points of the best is replaced
  by the simpler one (smaller shrink, then fewer parts). "Nothing beats live" means: the chosen setting does not have lower
  held-out pooled WAPE than the live settings (shrink 0.5, product grain k=2, geometric, December rule on) in T1 and T2 both.
- A 95% product-bootstrap interval (2,000 draws, seed 20261116) is reported on the held-out change against live and against no factor.

## What is reported for every setting
Held-out pooled WAPE (T1, T2, T3), signed bias by target month for March and July, bias-vs-seasonal-ratio correlation,
median MASE, stock-out months and pesos beyond safety stock (as in `reports/CALENDAR_GRAIN_2026-11-12.md` section 3/7), cost and benefit by shrink.

## Not done here
No live write, no chapter, no manuscript. The rehearsal runs on a local copy only.
