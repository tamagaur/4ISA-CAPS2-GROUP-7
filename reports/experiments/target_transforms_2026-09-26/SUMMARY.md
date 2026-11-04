# Target transforms experiment — 2026-09-26

**Personal experiment.** Local branch `experiment/target-transforms` only. It is never
pushed or merged. Nothing here changes the dashboard, `forecast_result`, the router,
DEC-28, `backup_options.json` or the dev viewer, and the database was only read (one
read-only SELECT on `unilever_sku_demand_fact_real`). Forecasts are always compared in
original units.

## The answer

**No transform produced a real win.** Under the stricter bar set for this experiment,
**0 of the 35 new candidates** qualify, in any bin, against either MA3 or the served
model.

- **Gentle squeezes and winsorizing tie.** This covers square root, Box-Cox,
  Yeo-Johnson, cube root, inverse hyperbolic sine, Anscombe and winsorizing. Each
  transform's median change in MASE is within ±0.02. The largest single cell is
  +0.085 (inverse hyperbolic sine on comb_simple, harness B short bin).
- **log1p with smearing is consistently worse.** Median MASE rises by +0.01 to +1.06
  across its cells, and most cells are losses.
- **First differencing and STL are worse in the long bin**, where they apply. Median
  MASE rises by +0.05 to +0.44.
- **The long-bin "wins" come from the model, not the transform.** Six transformed
  versions of the XGBoost + MA3 average beat MA3 on the full window. The
  *untransformed* average shows the same result in the same harness. Against that
  untransformed average (the served model), all six tie.

## Terms

| term | meaning |
|---|---|
| **MA3** | 3-month moving average: the benchmark model, and the served model for short-history SKUs |
| **TSB** | Teunter-Syntetos-Babai, a smoothing model for demand that has gaps; served for medium-history SKUs |
| **SES** | simple exponential smoothing |
| **comb_simple** | the average of MA4, MA12 and SES (4- and 12-month moving averages plus SES) |
| **XGBoost + MA3 average** | the average of one XGBoost (gradient-boosted trees) model trained across SKUs and MA3; served for long-history SKUs |
| **SKU** | stock-keeping unit, one product |
| **MASE** | Mean Absolute Scaled Error: forecast error divided by the error of "next month = this month". Below 1.0 is better than that naive guess |
| **WAPE** | Weighted Absolute Percentage Error: total absolute error ÷ total absolute sales for one SKU |
| **two-condition test** | the project's rule for a "win": the 95% bootstrap interval (1,000 resamples, seed 20260921) on the difference in median per-SKU WAPE is entirely below zero, **and** more SKUs improve than get worse |
| **block** | one of 5 half-year test periods from 2023-10 to 2026-02 |
| **λ (lambda)** | the power fitted for Box-Cox and Yeo-Johnson |
| **MLE** | maximum likelihood estimation, the method used to fit λ |
| **STL** | Seasonal-Trend decomposition using LOESS (locally weighted smoothing) |
| **log1p** | log(1 + x) |
| **Duan smearing** | a correction for the bias that appears when a forecast made on the log scale is converted back |
| **Anscombe** | 2·√(x + 3/8) |
| **asinh** | inverse hyperbolic sine |

## What was tested

Every candidate follows the same recipe:

1. Fit the transform on one SKU's training months only (a fresh fit for every forecast
   month, so nothing from the month being forecast leaks in).
2. Forecast on the transformed scale.
3. Convert the forecast back to original units and score it there.

| model | transforms | new candidates |
|---|---|---|
| MA3 | square root, log1p, Box-Cox, Yeo-Johnson, cube root, asinh, Anscombe, winsorize; plus first difference and STL (long bin only) | 10 |
| comb_simple | same 10 | 10 |
| XGBoost + MA3 average | same 10 | 10 |
| TSB | square root, log1p, cube root, asinh, winsorize, applied to demand sizes only | 5 |
| **total** | | **35**, so the candidate count rises from **50 to 85** |

The run also included 6 sanity columns and 4 controls. The sanity columns are square
and min-max scaling to 1–10, each on MA3, comb_simple and the average; they are never
adoptable. The controls are the identity transform, one per model. That gives 45
prediction columns in each of 2 harnesses, **90 runs** in total. Across all SKUs this
means 1,722 tests: 246 comparisons × 6 windows in harness A, plus 246 in harness B.

**Settings.** All were fixed before any result existed.
- Shift: c = 1 − min(training data) when the minimum is ≤ 0.
- λ: fitted by MLE and bounded to [−1, 2]. The bounds were not widened.
- log1p: Duan smearing on the same model's in-sample one-step errors.
- Winsorize: clip at the 5th and 95th percentiles of the training data. There is no
  inverse.
- The two averages (XGBoost + MA3, and comb_simple): each component is transformed and
  converted back on its own, then the components are averaged in original units.
- XGBoost: transform first, then apply the existing division by the recent 6-month
  level, unchanged.
- A failed fit, or a forecast the inverse can't convert back, is left blank, counted,
  and never replaced.

**The two harnesses.** Both reproduce the code that produced the numbers on record.

| | harness A: bake-off | harness B: common window |
|---|---|---|
| reproduces | `final_fit.py`, `final_models.py`, `cells_all.py` | `fit_review_common.py` (an earlier session's scratch script, not in git) |
| forecast months | every month 2023-10 … 2026-02, plus 5 half-year blocks | 2025-09 … 2026-02 |
| bins | assigned at each forecast month from the history known then | the SKU's stored router bin |
| forecast rules | clip at 0, as the bake-off did | the router's rules: a forecast above the SKU's historical maximum, or below 0, falls back to MA3 |
| MASE scale | recomputed at each forecast month | fixed per SKU, from the months before 2025-09 |
| SKUs tested (≥ 3 months) | short 113, medium 89, long 64 | short 22, medium 17, long 72 |

The "win" rule is the existing WAPE two-condition test, run twice: against MA3 and
against the served model. MASE is reported alongside.

## Correctness checks (all passed before anything was scored)

| check | result |
|---|---|
| Identity, harness A | **0 differences** on 2,711 forecast rows for MA3, TSB, MA4, MA12, SES, XGBoost and the average, against `candidate_search_tierA_preds.csv.gz` read with an exact parser. **XGBoost is bit-exact** (8 threads, seed 20260921). comb_simple also matches exactly once the file's own read/write history is reproduced (see data findings). |
| Identity, harness B | **0 differences** on 666 SKU-months between the router module and this experiment's code. `mase_common` and `ma3_mase_common` match for **107 of 107 SKUs** at 4 decimals. |
| Round trip: inverse(transform(x)) = x | Checked on every fitted training series. |
| Old `preds_plus.csv.gz` as the baseline instead of the exact values | **0 changes** across 336 compared rows: verdict, blocks, label, and SKU better/worse counts |

**The round-trip tolerance.** Every transform must round-trip to within an absolute
1e-9, except Box-Cox and Yeo-Johnson. For those two the rule is
**|back − x| ≤ max(1e-9 × |x|, 1e-9)**. It is relative for large values and identical
to the absolute rule at zero.

The reason is a float64 limit. When λ is near −1, Box-Cox stores x as roughly 1 − 1/x.
A float64 holds only about 16 significant digits, so a value of 300,000 comes back
with an error near 1e-5, however the formula is written. A purely relative rule would
fail at months with zero sales: after a shift, a zero comes back as 3 − 3 with about
1e-15 of rounding error, and a relative rule demands exactly 0.

| | worst absolute error | worst relative error |
|---|---|---|
| Box-Cox | 5.1e-6 | 1.7e-11 |
| Yeo-Johnson | 1.5e-5 | 4.9e-11 |
| all other transforms | 2.9e-10 (log1p) | — |

## Results by transform

Each cell counts full-window verdicts (win/tie/loss) across that transform's model ×
bin combinations. MASE change is the transformed model minus the same model
untransformed; negative means better.

| transform | A vs MA3 | A vs served | A median MASE change [range] | B vs MA3 | B vs served | B median MASE change [range] |
|---|---|---|---|---|---|---|
| square root | 1/11/0 | 0/10/2 | −0.000 [−0.006, +0.006] | 0/12/0 | 0/11/1 | −0.002 [−0.028, +0.030] |
| log1p + smearing | 0/3/9 | 0/0/12 | **+0.041** [+0.020, +0.262] | 0/7/5 | 0/6/6 | **+0.041** [+0.011, +1.061] |
| Box-Cox | 1/8/0 | 0/7/2 | +0.001 [−0.003, +0.004] | 0/9/0 | 0/8/1 | +0.002 [−0.020, +0.016] |
| Yeo-Johnson | 1/7/1 | 0/7/2 | +0.001 [−0.002, +0.004] | 0/9/0 | 0/8/1 | −0.000 [−0.013, +0.026] |
| cube root | 1/11/0 | 0/11/1 | +0.001 [−0.007, +0.011] | 0/12/0 | 0/11/1 | −0.009 [−0.036, +0.034] |
| asinh | 0/12/0 | 0/10/2 | +0.003 [−0.011, +0.023] | 0/12/0 | 0/12/0 | −0.016 [−0.043, +0.085] |
| Anscombe | 1/8/0 | 0/7/2 | +0.001 [−0.006, +0.008] | 0/9/0 | 0/8/1 | −0.004 [−0.028, +0.030] |
| first difference (long) | 0/0/2, 1 not testable | 0/0/2, 1 not testable | **+0.373** [+0.332, +0.413] | 0/0/3 | 0/0/3 | **+0.321** [+0.124, +0.441] |
| STL (long) | 0/1/2 | 0/0/3 | **+0.094** [+0.091, +0.137] | 0/0/3 | 0/0/3 | **+0.122** [+0.049, +0.155] |
| winsorize | 1/11/0 | 0/10/2 | −0.001 [−0.015, +0.003] | 0/12/0 | 0/9/3 | −0.000 [−0.011, +0.021] |
| *square (sanity)* | 1/8/0 | 0/6/3 | +0.007 [−0.005, +0.022] | 0/9/0 | 0/8/1 | +0.017 [+0.009, +0.044] |
| *min-max (sanity)* | 1/8/0 | 0/7/2 | +0.000 [−0.011, +0.003] | 0/9/0 | 0/8/1 | +0.000 [−0.018, +0.053] |

Every "1" in the A-vs-MA3 column is the same long-bin XGBoost + MA3 average cell (next
section). Per-bin detail for every candidate is in `results_by_bin.csv`: wins, ties and
losses by block, and median MASE change.

**Sanity checks behaved as expected.** Min-max is a linear rescaling, so it leaves MA3
unchanged: its MASE change is exactly 0.0000 in every bin of both harnesses. That
confirms the transform-and-convert-back code adds no error of its own. Square pushes in
the wrong direction and is worse in most cells, as it should be: median +0.007 in
harness A and +0.017 in harness B. The exception is two harness A cells for the
average, where it comes out slightly better (−0.005).

**Why log1p goes wrong, as far as measured.** In harness B, the router's fallback
(forecast above the SKU's historical maximum, or below 0) fired on log1p forecasts 65
times for TSB and 132 times for the average. For the untransformed versions it fired 0
and 5 times. The converted-back forecasts run high.

## The stricter win bar and the selection-artefact check

A result is a **real win** only if all three hold:
- (a) it passes the two-condition test on the full window;
- (b) it also wins a majority of the testable blocks;
- (c) it was not selected using the unfit subset.

Anything else with a win in it is **exploratory**. Condition (c) holds by construction:
every candidate was scored on all SKUs, and the unfit subset is reported separately and
never used to choose anything.

**Real wins: 0.** Exploratory wins in harness A, all SKUs:

| candidate | bin | against | full window | blocks | why it is not real |
|---|---|---|---|---|---|
| MA3 winsorized | short | MA3 and served (both are MA3 here) | tie: WAPE 0.263 vs 0.269, interval [−0.013, +0.003] | T T **W** T T | wins 1 of 5 blocks. This is the pattern that made `rf@ABC` and `lgbm_tweedie@A` artefacts |
| TSB winsorized | short | MA3 and served | tie | T T **W** T T | same |
| average + square root | long | MA3 | win | –, –, –, T, T | wins 0 of 2 testable blocks; the untransformed average also wins here |
| average + Box-Cox | long | MA3 | win | –, –, –, T, T | same |
| average + Yeo-Johnson | long | MA3 | win | –, –, –, T, T | same |
| average + winsorize | long | MA3 | win | –, –, –, T, T | same |
| average + cube root | long | MA3 | win | –, –, –, T, **W** | wins 1 of 2 blocks, not a majority; untransformed average also wins |
| average + Anscombe | long | MA3 | win | –, –, –, T, **W** | same |

**The long-bin control.** The untransformed XGBoost + MA3 average against MA3, same
harness, gets:
- WAPE 0.247 vs 0.270, interval [−0.042, −0.008];
- 51 SKUs better, 13 worse;
- blocks tie, tie.

So it fails the stricter bar in exactly the same way, and in the project's terms it
remains a **tie** with MA3 (DEC-26). In harness B the same untransformed average also
ties MA3 (interval [−0.050, +0.008]).

Against the untransformed average (the served model), in the long bin of harness A:
- all six of the transformed versions above **tie** it, with median MASE changes from
  −0.002 to +0.004;
- log1p and STL **lose** to it;
- first difference is not testable.

**Background rate.** Scored the same way, the 50 existing candidates give
**0 real wins** and **11 exploratory wins against MA3** (15 including against served).
Their block wins against MA3 are 6 of 540 testable blocks (1.1%). The 35 new candidates
give 4 of 329 (1.2%). Adding 35 candidates produced exploratory results at the same
rate as the existing 50, which is what chance alone would give.

## λ bounds (Box-Cox and Yeo-Johnson)

For positive sales, Yeo-Johnson is Box-Cox applied to x + 1. With sales in the
hundreds, the two fitted λ values nearly coincide, and the bound counts below came out
identical for both.

**Where the fits sit, per bin**, on the months that are scored:

| harness | bin | λ at −1 | interior | λ at 2 | at a bound | failed fit |
|---|---|---|---|---|---|---|
| A | short | 57 | 565 | 55 | 16.5% | 0 |
| A | medium | 30 | 954 | 13 | 4.3% | 0 |
| A | long | 7 | 751 | 1 | 1.1% | 0 |
| A | intermittent | 0 | 19 | 0 | 0% | 0 |
| B | short | 10 | 104 | 4 | 11.9% of fitted | 14 (fewer than 3 months of history) |
| B | medium | 0 | 102 | 0 | 0% | 0 |
| B | long | 4 | 421 | 7 | 2.5% | 0 |

The earlier count of 439 bound hits (248 at −1, 191 at 2) covered all 5,170 series. That
included the extra series fitted inside the XGBoost training pools, not just the scored
months. Bound hits concentrate in the short bin, where 3–11 months give λ little to go
on.

**Results split into bound-hit fits and interior fits.** For every Box-Cox and
Yeo-Johnson result, the test was rerun on interior-fit months only and on bound-hit
months only. The columns `verdict_lambda_interior`, `verdict_lambda_bound` and
`gain_share_from_bound_*` are in `results_by_bin.csv`.
- **No result depends mainly on bound-hit fits.** The only Box-Cox and Yeo-Johnson
  exploratory wins are the long-bin average against MA3, above. The long bin has just
  8 bound-hit months, and only 1 SKU has enough of them to test. Both results still win
  on interior fits alone (62 SKUs).
- Elsewhere the interior-only verdicts are ties or losses, with two differences from
  the overall verdict:
  - comb_simple + Box-Cox against the served model, harness A long bin: a loss
    overall, a tie on interior fits;
  - the average + Box-Cox against MA3, harness B long bin: a tie overall, a win on
    interior fits only (69 SKUs). That is one window on a subset, so it is exploratory
    at most, and it comes from removing bound-hit fits, not from relying on them.
- Bound-only subsets can be tested only in harness A's short and medium bins (22 and 7
  SKUs), and tie there. Elsewhere they have fewer than 5 SKUs.
- The `gain_share` columns are blank when a candidate does not lower the total
  absolute error. That can happen even when the median-based test favours it, because
  a few large SKUs dominate the total. They can also swing to values like −3.3 when the
  total is near zero. Read the interior-only verdicts, not those ratios.

## The unfit SKUs

**25 recomputable, not 28.** Recomputing "MASE ≥ 1.1 on the common window 2025-09 …
2026-02" gives **25 SKUs: short 5, medium 9, long 11**. The documents on record say 28.
The other 3 (738, 913, 1280, all short bin) are "not fit" only on the pipeline's own
20% holdout. They have no sales history before 2025-09, so the common-window MASE has no
scale to divide by. They are reported below as **holdout-only unfit**. The documents
that say 28 were not edited.

**The 25 were never used to select anything, and a win on them would not count as
evidence.** They were picked *because* they score badly.
- **Harness B, pooled:** 0 wins against MA3 or served; 1 and 2 losses respectively.
- **Harness A, pooled over all their forecast months:** 2 exploratory single-block
  wins, TSB + square root (T T T W T) and TSB + winsorize (T T W T T). Both are the
  artefact pattern, and both are ties on the full window.
- **Per SKU, harness B:**
  - The best candidates move at most **2 of the 25** below MASE 1.1. For example,
    comb_simple + Box-Cox improves 16 SKUs, worsens 8, and moves 2 below 1.1 (median
    MASE change −0.042).
  - Under the served model itself, 0 of the 25 are below 1.1, by definition.
  - The worst results are first differencing (median +0.20 to +0.53) and log1p
    (+0.06).
- **Holdout-only unfit:**
  - **738 and 913:** harness A gives MASE, on its per-forecast-month scale, for 38 and
    36 of 39 columns. Harness B gives WAPE only, for 20 of 39 columns (the rest have at
    least one blank month), and no MASE.
  - **1280 cannot be scored by either harness.** All 5 of its months fall inside the
    common window, and harness A has only 2 forecast months for it, under the minimum
    of 3. It is the only one of the 28 with no rows in `unfit_subset.csv` (3,357 rows,
    27 SKUs).

## Blanks, skips and fallbacks (counted, never replaced)

| where | count |
|---|---|
| XGBoost, harness A (2,459 forecast months) | log1p 70 blank: a SKU's first forecast month has no in-sample errors to smear with. Box-Cox 71 and Yeo-Johnson 66 blank: the XGBoost prediction fell outside the range the inverse accepts. Square 1. |
| XGBoost + first difference, harness A | 1,690 SKU-months left out of training (fewer than 24 months). 10,047 training rows and **440 forecast months** skipped because the mean of the last 6 differences is ≤ 0 (the division rule), leaving 329 forecast months. 15 months had under 100 training rows. |
| XGBoost + STL, harness A | 1,690 SKU-months left out; 15 months under 100 training rows; 769 forecast months |
| harness B, per-SKU transform fit failures | first difference 41 and STL 41 (long SKUs with under 24 months before the forecast month); Box-Cox 14 and Yeo-Johnson 14 (under 3 months of history); min-max 4 (constant history) |
| harness B, XGBoost | first difference: 226 fell back to MA3 (level ≤ 0) and 41 blank; log1p 29 blank; Box-Cox 23 and Yeo-Johnson 23 blank; STL 41 blank; min-max 4 blank |
| harness B, the router's own fallbacks (forecast above the historical maximum or below 0, so MA3 is served) | untransformed average 5; log1p TSB 65 and average 132; STL average 23; all others ≤ 8 |

## Data findings

1. **SKU 150, 2025-12: the quantity is NaN** (not a number) in
   `unilever_sku_demand_fact_real`. It is treated as 0, matching every earlier script:
   `final_fit.py` skips non-finite values, and `fit_review_common.py` and `a_load.py`
   fill with 0. It has not been fixed.
2. **`preds_plus.csv.gz` has small rounding drift in its numbers.** It differs from the
   exact values by up to 1.2e-10, on 11–511 rows per column. The cause is three rounds
   of reading and rewriting the file with pandas' default number parser (run7 →
   run_lgbm → score_arms). Simulating those three rounds reproduces the stored file
   exactly. `candidate_search_tierA_preds.csv.gz` was exported from a pickle and is
   exact. Scoring against either file gives the same verdicts.
3. **The earlier 28-SKU re-score was against the served model, not MA3.** It is
   documented as "50 candidates against MA3, 2 wins / 241 ties / 7 losses = 250
   cells". Rebuilt from committed files, that tally is **51 columns against the served
   model** (255 cells, 5 not testable). Against MA3, the same scoring gives 4 wins /
   233 ties / 8 losses / 5 not testable. The document was not edited.
4. **Negative and zero months.**
   - The view has 8 negative rows for these 132 SKUs.
   - The 2,711 scored forecast months include 7 negative actuals and 5 zero actuals.
     The zeros are months with no row, filled with 0.
   - The shift rule changes the transform only for SKUs whose training months include
     a zero or negative value.

## What this does not show

- It does not show that no transform could ever help. It shows that none of these 35
  does, on this cohort (Unilever Tier A as of 2026-02), with these two harnesses.
- The long bin has only 2 testable half-year blocks, so no long-bin candidate can meet
  condition (b) with fewer than 2 block wins. Nothing here changes that.
- Nothing here changes DEC-28. The work stopped before it.

## Files

| file | contents |
|---|---|
| `transforms.py` | the transforms, round-trip check, and TSB-on-sizes model |
| `run_experiment.py` | both harnesses, identity controls, scoring, λ analysis. Stages: `identity`, `full`, `score` |
| `results_by_bin.csv` | 672 rows: harness × cohort (all SKUs / unfit 25) × bin × candidate × baseline, with full-window verdict, blocks, label, median MASE change, and λ split columns |
| `results_by_sku.csv` | 15,519 rows: 10,758 harness A per-SKU cells and 4,761 harness B per-SKU rows |
| `unfit_subset.csv` | 3,357 rows: the `results_by_sku.csv` rows for the unfit SKUs (27 of 28; 1280 has none) |
