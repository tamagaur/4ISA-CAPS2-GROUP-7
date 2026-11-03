# Differencing, repeated transforms and ARIMA — phase 2, 2026-09-26

**Personal experiment.** It lives on local branch `experiment/target-transforms`
only and is never pushed or merged. Nothing here changes the dashboard,
`forecast_result`, the router, DEC-28, `backup_options.json`, `analytics/` or the
dev viewer. No database writes: the demand data comes from phase 1's single
read-only query. Forecasts are always scored in original units.

## The answer

**0 real wins among the 77 new candidates.** Nothing clears the stricter bar in any
bin, against either MA3 or the served model.

| group | what it is | result |
|---|---|---|
| **A** differencing alone (D2, D3, S12, S12+D1) | forecast the change, then add it back | **Every testable cell loses**: 8 of 8 in the long bin, both harnesses, both baselines. Median MASE is **+0.91** (harness A) and **+0.82** (harness B) worse than not differencing. |
| **B** transform, then D1 or S12 | 8 phase 1 transforms × 2 differencing types | Long bin: 62 losses and 2 ties out of 64 in harness A against MA3; **all 64 lose** against the served model. The transform makes differencing very slightly less bad (median −0.008 against differencing alone), but it stays far worse than not differencing. |
| **C** repeated squeezing (×2 and ×3) | square, cube and asinh roots; log1p twice or three times | The roots **tie** everywhere on MA3, comb_simple and TSB. **log1p ×2 and ×3 lose** in most bins. The only "wins" are the long-bin XGBoost + MA3 average against MA3, and they are inherited from the untransformed average again. |
| **D** AUTO-d (KPSS picks d = 0, 1 or 2) | differencing only where a test says so | **Loses** in the long bin, in both harnesses and against both baselines. KPSS picks d = 0 on 568 of 759 long-bin forecast months. |
| **E** ARIMA | E1 auto-ARIMA; E2 auto-ARIMA on log1p; E3 fixed SARIMA(1,1,1)(0,1,1,12) | E1 **loses** in the long bin in both harnesses. E2 **loses** in harness B and ties in harness A on only 5 testable SKUs. E3 **ties MA3** in harness B (49 SKUs) and **loses to the served model**; it cannot be tested in harness A. Median MASE is **+0.08 to +0.21** worse than MA3. |

The medium bin cannot be tested for any differencing or ARIMA group (see "Where the
groups could run"). Auto-ARIMA chooses **d = 2 often** (see "Group E"), unlike Gate D,
whose grid did not allow it.

## Terms

| term | meaning |
|---|---|
| **MA3** | 3-month moving average: the benchmark, and the served model for short-history SKUs |
| **TSB** | Teunter-Syntetos-Babai, a smoothing model for demand with gaps; served for medium-history SKUs |
| **SES** | simple exponential smoothing |
| **comb_simple** | average of MA4, MA12 and SES |
| **XGBoost + MA3 average** | one gradient-boosted tree model (XGBoost) trained across SKUs, averaged with MA3; served for long-history SKUs |
| **SKU** | stock-keeping unit, one product |
| **MASE** | Mean Absolute Scaled Error: forecast error divided by the error of "next month = this month". Below 1.0 beats that naive guess |
| **WAPE** | Weighted Absolute Percentage Error: total absolute error ÷ total absolute sales for one SKU |
| **two-condition test** | a "win" needs the 95% bootstrap interval (1,000 resamples, seed 20260921) on the median per-SKU WAPE difference to be entirely below zero, **and** more SKUs improving than worsening |
| **D1, D2, D3** | first, second and third differences: month-to-month change, the change of the change, and so on |
| **S12** | seasonal difference: this month minus the same month last year |
| **KPSS** | Kwiatkowski-Phillips-Schmidt-Shin test: asks whether a series is stable around a level; if not, difference and ask again |
| **OCSB / Canova-Hansen** | Osborn-Chui-Smith-Birchenhall and Canova-Hansen tests for seasonal differencing (not available here; see group D) |
| **ARIMA / SARIMA** | AutoRegressive Integrated Moving Average, written (p, d, q) × (P, D, Q, 12); d and D are the numbers of ordinary and seasonal differences. The seasonal version is SARIMA |
| **AICc** | corrected Akaike Information Criterion: a fit score that penalises extra parameters |
| **Gate D** | the 2026-09-20 auto-ARIMA bake-off (`scripts/arima_bakeoff.py`, 89 SKUs) |
| **OpenBLAS** | the linear-algebra library numpy uses for its matrix maths |
| **Duan smearing** | correction for the bias in converting a log-scale forecast back to units |
| **log1p, asinh** | log(1 + x); inverse hyperbolic sine |
| **Box-Cox, Yeo-Johnson, Anscombe** | power transforms; Anscombe is 2·√(x + 3/8) |
| **winsorize** | clip the training months at their 5th and 95th percentiles |

## What was tested

| group | variants | models | new candidates |
|---|---|---|---|
| A | D2, D3, S12, S12+D1 (D1 is phase 1's, kept only as a reference) | MA3, comb_simple | 8 |
| B | {square root, log1p + smearing, Box-Cox, Yeo-Johnson, cube root, asinh, Anscombe, winsorize} × {D1, S12} | MA3, comb_simple | 32 |
| C | square root, cube root, asinh, log1p, each ×2 and ×3 | MA3, comb_simple, XGBoost + MA3 average, TSB (demand sizes only) | 32 |
| D | AUTO-d | MA3, comb_simple | 2 |
| E | E1 auto-ARIMA, E2 auto-ARIMA on log1p, E3 fixed SARIMA(1,1,1)(0,1,1,12) | stand-alone | 3 |
| **total** | | | **77** |

- Candidates in all: 50 original + 35 from phase 1 + 77 here = **162**.
- Runs: 83 prediction columns per harness (77 candidates, 4 identity controls, 2 D1
  references), across 2 harnesses: **166**.
- The harnesses, identity controls, two-condition test and round-trip rule are phase
  1's, imported unchanged.

**Settings, all decided before any result existed:**
- **Minimum history:** D1, D2, D3, AUTO-d, transform + D1, E1 and E2 need ≥ 18
  training months; anything with S12, and E3, needs ≥ 24. Shorter histories are
  skipped and counted.
- **AUTO-d:** d chosen by KPSS (statsmodels; level-stationarity null, automatic lag
  length, alpha 0.05), up to 2. No seasonal order, because OCSB and Canova-Hansen are
  unavailable: `pmdarima` needs scikit-learn, which is blocked on this machine,
  `statsforecast` is not installed, and there is no R. Seasonal differencing is still
  tested in group A (S12) and group E, where AICc picks D.
- **Auto-ARIMA (E1, E2):**
  - Gate D's grid, extended to d = 2: (p, d, q) in {0,1,2}³, seasonal (P, D, Q, 12) in
    {none, (0,1,1), (1,1,0), (0,1,0)}.
  - Seasonal terms only with ≥ 24 months and p + d + q ≤ 3.
  - Lowest AICc wins, and the order is **re-selected at every forecast month**.
  - If no model fits, the forecast is blank (Gate D fell back to (0,1,1); not here).
  - E2 smears using the chosen model's in-sample errors, after dropping the first
    d + 12·D.
- **E3** is `scripts/model_bakeoff.py`'s `m_sarima_seasonal`, unchanged. It keeps its
  own 28-month floor inside the 24-month rule.
- **XGBoost is left out of every differencing candidate** (groups A, B and D). Its
  existing step of dividing by the recent 6-month level removed most forecast months
  under differencing in phase 1 (440 of 769 long-bin months), which would bias any
  result.
- **Repeated transforms:** the phase 1 shift is applied once, before the first pass.
  log1p ×k smears on the whole back-transform.
- **Round trip:** absolute 1e-9, except Box-Cox, Yeo-Johnson and all repeated
  transforms, which use |back − x| ≤ max(1e-9 × |x|, 1e-9). That rule is relative
  for large values and the same as the absolute rule at zero. Repeated transforms got
  it on 2026-09-26 because each pass through a curved function and back adds
  rounding error in proportion to x. Two or three passes on sales of 190,000–300,000
  gave absolute errors of 1.1e-9 to 2.7e-9, which is at most 1.4e-14 relative.
- **Forecast rules match each pipeline:**
  - Harness A clips every component at 0, as the bake-off did. An ARIMA-family
    forecast above the training maximum becomes **blank**, as `model_bakeoff.py` and
    Gate D did.
  - Harness B uses the router's rules: a served MA3 is floored at 0, and a
    challenger above the SKU's historical maximum, or below 0, falls back to MA3.
  - Averages are built from components that are each converted back to units first.

## How the ARIMA stage was run (choice and reason)

- **First attempt:** 12 worker processes with the default multi-threaded OpenBLAS.
  - Each worker started its own maths threads (31 per process), and they competed for
    16 cores.
  - A timed sample measured **76–116 CPU-seconds per search, against 3–13
    single-threaded**.
  - After more than two hours, fewer than 200 of the 1,711 searches had been
    reported. Finished searches were held only in memory, so stopping it lost them.
- **Choice (2026-09-26): option (c).**
  - Stop, and rerun the **same per-forecast-month order search** with the maths
    limited to 1 thread per worker (OMP, MKL and OpenBLAS thread counts set to 1).
  - Use 8 workers, about half the machine.
  - Write each finished search to disk as it completes, so a stop is resumable.
- **Why this option:**
  - The slowdown was a threading problem, not a problem with the method.
  - Per-month selection is what was chosen before any result existed.
  - The other offered option, picking the order once per half-year block, would have
    changed the method to save time.
  - The measured single-threaded cost made the original method affordable.
- **Result:**
  - 1,711 of 1,711 searches ran on 1 maths thread each (confirmed by every worker)
    and were saved to disk.
  - 45 minutes at 38 searches per minute.
  - 19,824 CPU-seconds in total: 11.6 seconds per search on average, 31.3 at most.

## Correctness checks (all passed before scoring)

| check | result |
|---|---|
| Identity, harness A | **0 differences** on 2,711 rows against the exact artifact, including bit-exact XGBoost; 0 against `preds_plus` with the same read/write history |
| Identity, harness B | **0 differences** on 666 SKU-months against the router module; `mase_common` matches for **107 of 107** SKUs at 4 decimals; 25 unfit SKUs (short 5, medium 9, long 11) |
| Recomputed D1 = phase 1's `diff1` | **0 differences**: 759 rows (harness A) and 391 rows (harness B), for both MA3 and comb_simple |
| Round trip | **pass** on every chain and transform, including E2's log1p step: 97 checks covering 119,755 fitted series; worst absolute error 1.5e-6 (Box-Cox + D1, within its relative rule) |
| Control rows match phase 1 | **0 differences** in 64 control rows (skus, verdict, median WAPE, median MASE) |

## Results by group and bin

Full-window verdicts (win / tie / loss / not testable), counted across each group's
candidates. "Change" is the median MASE change against the group's reference:
- A and D: the same model without differencing;
- B: the same differencing without the transform;
- C: the same model untransformed;
- E: MA3.

| group | bin | harness A vs MA3 | A vs served | A change (median) | harness B vs MA3 | B vs served | B change (median) |
|---|---|---|---|---|---|---|---|
| A | long | 0/0/8 | 0/0/8 | **+0.907** | 0/0/8 | 0/0/8 | **+0.815** |
| A | medium | 8 not testable | 8 not testable | +2.058 | 8 not testable | 8 not testable | — |
| B | long | 0/2/30 | 0/0/32 | −0.008 | 0/1/31 | 0/0/32 | −0.008 |
| B | medium | 32 not testable | 32 not testable | −0.036 | 32 not testable | 32 not testable | — |
| C | long | 5/22/5 | 0/13/19 | −0.003 | 0/26/6 | 0/24/8 | −0.009 |
| C | medium | 0/26/6 | 0/24/8 | +0.004 | 0/30/2 | 0/32/0 | −0.029 |
| C | short | 0/24/8 | 0/24/8 | +0.018 | 0/28/4 | 0/28/4 | +0.029 |
| D | long | 0/0/2 | 0/0/2 | 0.000 | 0/0/2 | 0/0/2 | 0.000 |
| D | medium | 2 not testable | 2 not testable | +0.073 | 2 not testable | 2 not testable | — |
| E | long | 0/1/1, 1 not testable | 0/1/1, 1 not testable | E1 +0.082, E2 +0.117 | 0/1/2 | 0/0/3 | E1 +0.214, E2 +0.138, E3 +0.119 |
| E | medium | 2 not testable | 2 not testable | — | 2 not testable | 2 not testable | — |

Per-candidate detail (verdict, blocks, medians, interval, better/worse counts) is in
`results_by_bin.csv`. The details worth knowing:
- In group B, the two long-bin ties against MA3 are comb_simple + Box-Cox + S12 and
  comb_simple + winsorize + S12. Both lose against the served model.
- In group C, log1p ×2 and ×3 lose in the short bin on every model. They also lose
  in the medium bin on every model, except TSB against MA3, which ties. On MA3 they
  lose in the long bin too.
- Also in group C, MA3 and TSB with root transforms mostly lose to the served model
  in the long bin (TSB + square root ×2 ties). The untransformed MA3 already loses
  there, because the served average is better in the long bin.
- **Group E, harness B** (the informative harness for E):

  | candidate | SKUs | median WAPE vs MA3's | SKUs better / worse | verdict vs MA3 | verdict vs served |
  |---|---|---|---|---|---|
  | E1 | 72 | 0.370 vs 0.268 | 23 / 49 | loss | loss |
  | E2 | 71 | 0.353 vs 0.267 | 15 / 50 | loss | loss |
  | E3 | 49 | 0.316 vs 0.262, interval [−0.002, +0.093] | 16 / 33 | tie | loss |

- **Group E, harness A:** blank forecasts shrink the testable set. The blanks come
  from the rule that blanks an ARIMA forecast above the training maximum (92 E1, 364
  E2 and 50 E3 forecasts) and from E3's 28-month floor (256 long-bin months). Only 25
  SKUs remain for E1, 5 for E2 and none for E3. In the medium bin, E2 shows one
  half-year block win (2025-03 to 2025-08). Its full window cannot be tested
  (0 SKUs), so under the label rule it counts as not testable, and it could not meet
  condition (a) anyway.

**Why differencing loses.**
- D1 on MA3 is exactly "last month + (last month − the month 3 before) ÷ 3": a
  last-value forecast plus a 3-month trend (phase 1).
- D2 and D3 extrapolate further. MA3 on D3's raw forecasts run from −88,812 to
  +365,297 units between the 1st and 99th percentiles.
- 325 of MA3 on D3's 1,240 harness A forecasts fall below −10× the SKU's largest
  return; for a SKU that has never had a return, that means below zero.
- Harness A clips negative forecasts at zero, and D3 still loses.

## Group E: the orders auto-ARIMA chose

| | fits | d = 0 | d = 1 | d = 2 | seasonal D = 1 |
|---|---|---|---|---|---|
| E1, harness A | 1,240 | 172 | 418 | **650** (52%) | 765 (62%) |
| E2 (log1p), harness A | 1,240 | 780 | 415 | 45 (4%) | 656 (53%) |
| E1, harness B | 471 | 24 | 289 | **158** (34%) | 389 (83%) |
| E2 (log1p), harness B | 471 | 248 | 201 | 22 (5%) | 317 (67%) |
| Gate D (reference) | 89 SKUs | 0 | 89 | not allowed | 49 (55%) |

- **d = 2 differs sharply from Gate D.** Gate D's grid stopped at d = 1, so it could
  never choose 2. With 2 allowed:
  - E1 picks it on half its harness A fits;
  - in the medium bin it picks it almost always (98% in harness A, 100% in harness B);
  - in the long bin, 23% and 28%.
- Medium-bin histories (18–23 months) are too short for seasonal terms, which may
  push AICc toward extra ordinary differencing.
- On the log scale (E2), d = 2 is rare and d = 0 is the most common choice.
- **One caveat:** AICc values from models with different d are computed on
  differently differenced data, so comparing them across d is not strictly
  like-for-like. Gate D's design has the same limitation.
- These are the orders chosen, not a measure of accuracy; E1 loses (above).

## The 10× check (raw forecasts, before any clip or fallback)

The check counts forecasts above 10× the SKU's historical maximum, or below −10× its
largest return. "Historical" means the training months at that forecast month, and
the lower bound is 0 when the SKU has never had a return.
- **Above 10× the historical maximum: 3,244.**
  - Groups A–D account for 3,028. All come from log-based back-transforms: log1p ×2
    and ×3, log1p + D1, log1p + S12, and a few asinh.
  - The worst is MA3 + log1p + D1, whose raw forecast reaches 1.6 billion units,
    123,000× that SKU's maximum.
  - Group E adds 216, mostly E2 (146 in harness A, 64 in harness B).
- **Below −10× the largest return: 1,835.**
  - All come from differencing (D3, D2, S12 + D1 and the rest) or ARIMA (E1 67, E3 35,
    E2 3).
  - 2,367 of the 2,452 scored forecast months are for SKUs with no return in their
    history, so their bound is 0 and any negative forecast counts.
- All of them stay in scoring:
  - Harness A clips at 0, and blanks ARIMA forecasts above the training maximum.
  - In harness B the router's fallback replaced the following forecasts with MA3.

  | candidate | forecasts replaced |
  |---|---|
  | TSB, log1p ×2 / ×3 | 95 / 115 |
  | average, log1p ×2 / ×3 | 185 / 194 |
  | E1 / E2 / E3 | 51 / 169 / 32 |
  | untransformed average (for comparison) | 5 |

## The stricter bar and the selection-artefact check

A **real** win needs all three:
- (a) the two-condition test passed on the full window;
- (b) a win in a majority of testable half-year blocks;
- (c) no use of the unfit subset in choosing it.

Everything else with a win in it is **exploratory**.

**Real wins: 0.** The 6 exploratory wins in harness A are all the long-bin
XGBoost + MA3 average against MA3, under square root ×2 and ×3, cube root ×2 and ×3,
and asinh ×2 and ×3:
- Each wins the full window (except asinh ×3), and **1 of its 2** testable blocks,
  which is not a majority.
- The untransformed average gets the same full-window result against MA3 (51 SKUs
  better, 13 worse; blocks tie, tie). In the project's terms it remains a tie
  (DEC-26).
- Against the served model, which is that same untransformed average, all six
  **tie**.

Harness B has no wins in any group.

**Exploratory rate** in harness A, all SKUs, counting only testable cells:

| candidate set | testable cells | exploratory | real | block wins |
|---|---|---|---|---|
| original 50 | 294 | 15 (5.1%) | 0 | 10 / 1,074 (0.9%) |
| phase 1 (35) | 184 | 10 (5.4%) | 0 | 6 / 658 (0.9%) |
| **phase 2 (77)** | 280 | **6 (2.1%)** | 0 | 8 / 1,024 (0.8%) |
| — group A | 16 | 0 | 0 | 0 / 56 |
| — group B | 64 | 0 | 0 | 0 / 224 |
| — group C | 192 | 6 (3.1%) | 0 | 6 / 704 (0.9%) |
| — group D | 4 | 0 | 0 | 0 / 20 |
| — group E | 4 | 0 | 0 | 2 / 20 (both are E2's single medium-bin block, against MA3 and against served) |

Adding 77 candidates produced no real result, and an exploratory rate no higher than
the earlier sets.

## Where the groups could run (skips by history)

Forecast months skipped:

| harness | bin | forecast months | under 18 months (D1–D3, AUTO-d, transform + D1, E1, E2) | under 24 months (anything with S12, E3) |
|---|---|---|---|---|
| A | short | 677 | 677 (all) | 677 (all) |
| A | medium | 997 | 519 | 987 |
| A | long | 759 | 0 | 0 |
| B | short | 132 | 132 (all) | 132 (all) |
| B | medium | 102 | 63 | 102 (all) |
| B | long | 432 | 0 | 41 |

- The medium bin is "not testable" for every differencing and ARIMA group. Phase 1's
  harness drops a SKU from a cell if any of its forecast months in that bin is blank,
  and most medium-bin SKUs have some months under 18. For example, only 1 SKU
  survives for D1 in harness A's medium bin, and none does in harness B.
- E3 also has its own 28-month floor, which blanks another 256 long-bin months in
  harness A.

**AUTO-d's choices** (forecast months by chosen d):

| harness | bin | d = 0 | d = 1 | d = 2 |
|---|---|---|---|---|
| A | long | 568 | 167 | 24 |
| A | medium | 397 | 57 | 24 |
| B | long | 288 | 129 | 15 |
| B | medium | 31 | 5 | 3 |

## The unfit SKUs

**25 recomputable** (short 5, medium 9, long 11) plus 3 holdout-only (738, 913, 1280),
as in phase 1. The subset was never used to choose anything.
- **Subset tests (pooled 25):**
  - no wins in either harness;
  - harness A: 32 ties and 45 not testable against MA3; 30 ties, 2 losses and 45 not
    testable against served;
  - harness B: 70 ties and 7 losses against MA3; 67 ties and 10 losses against
    served;
  - E1, E2 and E3 tie on the subset in harness B (9–11 SKUs) and cannot be tested in
    harness A.
- **Brought below MASE 1.1 on the common window:**
  - **62 SKU–candidate pairs**, covering **7 SKUs**: 189, 196, 388, 674, 675, 722
    and 985. Group E adds none.
  - No candidate brings more than 3 of the 25 below 1.1. The best is comb_simple +
    winsorize + S12, and that candidate can score only 9 of the 25 SKUs.
  - With 77 candidates, a few SKUs dipping below 1.1 by chance is expected.
- **Does it hold on earlier blocks?** Harness A was used, with the SKU's months in
  the four half-year blocks before 2025-09, and the candidate had to beat the served
  model in a majority of the testable ones. Only **12 of the 62** pairs hold: 11 for
  SKU 196 and 1 for SKU 189. Each of those 12 had just **one** testable earlier
  block. **None holds where two or more earlier blocks can be tested.**
- **Holdout-only unfit:**
  - 738 and 913 get harness A MASE for 34 of 36 columns, and harness B WAPE (not
    MASE) for 23 of 36.
  - 1280 cannot be scored by either harness, as in phase 1.
  - `unfit_subset.csv` has 5,262 rows for 27 SKUs.

## Data findings

- **SKU 150, 2025-12: quantity is NaN** in `unilever_sku_demand_fact_real`. It is
  treated as 0, as in every earlier script, and has not been fixed (same as phase 1).
- **Multi-threaded OpenBLAS inside process pools** made this machine's ARIMA fits
  about 10× more expensive in CPU. Any future parallel statsmodels run should set the
  thread counts to 1 per worker.
- Phase 1's findings still stand:
  - rounding drift in `preds_plus.csv.gz`;
  - the earlier 28-SKU re-score was against the served model;
  - SKU 1280 cannot be scored.

## What this does not show

- It does not show that differencing or ARIMA can never help. It shows that none of
  these 77 does, on this cohort (Unilever Tier A as of 2026-02), with these two
  harnesses.
- The medium bin could not be tested for differencing or ARIMA under the existing
  harness rule. The long bin has only 2 testable half-year blocks.
- Nothing here changes DEC-28. The work stopped before it.

## Files

| file | contents |
|---|---|
| `chains.py` | differencing chains, repeated transforms, KPSS-chosen d, auto-ARIMA |
| `run_phase2.py` | workers, assembly, gates and scoring. Stages: `precheck`, `full`, `no_arima` (groups A–D), `arima` (group E on the saved A–D state, resumable), `score`, `score_no_arima` |
| `results_by_bin.csv` | 1,136 rows: harness × cohort (all SKUs / unfit 25) × bin × candidate × baseline, with verdict, blocks, label and median MASE change against the reference |
| `results_by_sku.csv` | 24,840 rows: 16,678 harness A per-SKU cells and 8,162 harness B per-SKU rows |
| `unfit_subset.csv` | 5,262 rows for 27 unfit SKUs, with the common-window below-1.1 flag and the earlier-block check on harness B rows |
