# Forecasting model bake-off — real Unilever per-SKU demand

**Read-only simulation, 2026-09-01.** No DB writes, no model artifacts. Source:
`Unilever_SKU_Demand_Fact_Real` (24,906 real rows, 1,807 SKUs, 2023-01 → 2026-02).
Companion data: `reports/model_bakeoff_unilever.csv` (per-SKU per-model MAPE/MASE/sMAPE).

**Reproduce:** `python -m scripts.model_bakeoff` (Tier A, real only) /
`--cohort all` / `--with-synthetic` (the diagnostic what-if in the addendum).
Runtime ~10-15 min; the SARIMA fits dominate.

## Method

- **Backtest:** rolling-origin, **1-step-ahead**, over the **last 6 months**. Refit at
  every origin. Forecasts clipped at 0.
- **Cohorts:**
  - **A — all evaluable** (850 SKUs): ≥14 months span, ≥6 non-zero months.
  - **B — real Tier A** (89 of the 132 in ABC period 2026-02 that are evaluable).
- **Metrics per SKU:** MAPE (zero-actual points excluded), MASE (lag-1 naive scale),
  sMAPE (bounded 0–2). Aggregated as **median** (mean MAPE is unusable here — near-zero
  actuals blow it to 5–90).
- **17 models:** naive, seasonal-naive(12), mean, drift, MA3, MA6, Croston, SBA(α=.1),
  SBA(α=.3), TSB, SES, Holt, damped Holt, Holt-Winters additive(12), Theta,
  SARIMA(1,1,1)(0,1,1)₁₂, SARIMA(1,1,1).

## Headline

**No model reaches the MAPE = 0.20 gate at the median. The 20% gate is not
attainable per-SKU on real monthly Unilever demand with any method tested.** Best
median MAPE is **0.333** (SBA α=.3, Tier A) / **0.734** (SBA α=.3, all). Only
**13–15 % of individual Tier A SKUs** clear MAPE < 0.20 under the best method.

**But there is a clear, consistent ranking** — the smoother family genuinely beats
naive:

| | naive/drift/snaive | MA-family, SES, SBA, TSB, Theta, Holt | Holt-Winters add. |
|---|---|---|---|
| Tier A MASE median | 0.95–1.10 | **0.79–0.86** | **0.74** (n=62) |
| Tier A sMAPE median | 0.39–0.41 | **0.30** | **0.29** (n=62) |
| beats naive (% of SKUs) | — | **67–79 %** | 69 % |

## Cohort B — real Tier A (n=89), ranked by MASE

| model | MAPE med | MASE med | sMAPE med | MAPE<.20 | beats naive | n |
|---|---|---|---|---|---|---|
| **hw_add12** | 0.351 | **0.741** | **0.287** | 13% | 69% | 62 |
| **sba_a3** (α=.3) | **0.333** | 0.788 | 0.314 | **15%** | **79%** | 89 |
| theta | 0.363 | 0.792 | 0.301 | 9% | 74% | 89 |
| sarima_plain | 0.365 | 0.804 | 0.317 | 11% | 71% | 89 |
| tsb | 0.362 | 0.815 | 0.302 | 10% | 71% | 89 |
| ma3 | 0.351 | 0.819 | 0.296 | 7% | 75% | 89 |
| ses | 0.363 | 0.821 | 0.300 | 9% | 67% | 89 |
| ma6 | 0.358 | 0.836 | 0.310 | 8% | 69% | 89 |
| holt | 0.370 | 0.841 | 0.301 | 8% | 72% | 89 |
| holt_damped | 0.362 | 0.854 | 0.302 | 9% | 73% | 89 |
| sba (α=.1) | 0.353 | 0.875 | 0.303 | 12% | 70% | 89 |
| croston | 0.370 | 0.910 | 0.324 | 10% | 64% | 89 |
| snaive12 | 0.395 | 0.953 | 0.350 | 6% | 60% | 89 |
| sarima_seasonal | 0.372 | 0.989 | 0.373 | 4% | 57% | 49 |
| mean | 0.402 | 1.014 | 0.344 | 8% | 56% | 89 |
| **naive** | 0.448 | 1.081 | 0.394 | 4% | — | 89 |
| drift | 0.460 | 1.097 | 0.408 | 4% | 12% | 89 |

Cohort A (all 850) has the same ordering, wider gaps: naive MASE 0.934 / sMAPE 0.959;
best non-HW is **sba_a3** (MASE 0.941, sMAPE 0.756, beats naive **71%**); HW additive
MASE 0.949 / sMAPE 0.675 but only 363/850 SKUs have the 24 months it needs.

## What this changes vs the codebase's current position

`scripts/run_baseline_forecast.py` currently ships **naive / MA3 / SBA(α=0.1)**.

1. **SBA α=0.3 clearly beats SBA α=0.1** — MASE 0.788 vs 0.875, beats-naive 79% vs 70%
   (Tier A). `FORECASTING_METHOD_RECOMMENDATION.md` predicted "a properly tuned higher
   α closes most of the gap"; this confirms it and goes further — **SBA α=.3 is the best
   fixed-α method overall**. A real per-SKU α CV would likely do better still.
2. **MA3 holds up** — MASE 0.819, beats naive 75%. Keeping it as the simple default is
   defensible.
3. **Theta and damped Holt** (not in the current lineup) match MA3/SBA on MASE and beat
   naive 72–74%. Worth adding as candidates — both are cheap.
4. **Holt-Winters additive** is the single best method on both robust metrics, but only
   for the ~44%/70% of SKUs with ≥24 months. Candidate for a "long-history" branch only.
5. **SARIMA seasonal is not worth it** — MASE 0.989 (barely beats naive), needs ≥28
   months (ran on only 49/89), ~100× slower than everything else. Confirms the existing
   codebase decision to drop it. Plain ARIMA(1,1,1) is fine (MASE 0.804) but no better
   than SBA α=.3 and far slower.
6. **naive, drift, seasonal-naive are the worst three** on every robust metric.
   seasonal-naive wins the most SKUs as an *oracle* pick (23/89) but its median is poor
   and its mean MAPE is 2.9 — it's a high-variance lottery, not a usable default.

## Bottom line

- **The MAPE < 0.20 gate should be re-examined** — it is unreachable per-SKU on this
  data. Either move to a portfolio/category-level accuracy target, or replace it with a
  **MASE < 1** gate (which ~64–69% of Tier A SKUs pass under the good methods) plus a
  per-SKU sMAPE report.
- **Best single production choice: SBA with α ≈ 0.3** — no fit cost, best fixed-method
  MASE, beats naive on ~75–79% of SKUs across both cohorts.
- **Add Theta and damped Holt** as low-cost alternatives; **Holt-Winters additive** only
  where ≥24 months exist.
- The per-segment recommendation in `FORECASTING_METHOD_RECOMMENDATION.md` still holds;
  this run refines it: bump SBA's α, and the "smooth / long-history" segment gains HW-add
  and Theta as real options.

---

## Addendum — what if we add the synthetic 2021–2022 history back?

**Tested.** Prepended synthetic `is_demo=true` months (2021-01 → 2022-12) to each real
series, backtested on the **same last-6-real-months** window. Data:
`reports/model_bakeoff_unilever_withsynth.csv`. **Diagnostic only — synthetic rows are
frontend-validation-approved, never reported/manuscript results.**

**First: there is no 2023 gap for Unilever.** Real per-SKU demand is contiguous
2023-01 → 2026-02 (38 months, verified). The only missing month is Del Monte 2023-08.

**The synthetic era is a different data-generating process:**
portfolio ACF(lag 12) = **0.384 synthetic vs 0.280 real**; CV = **0.221 vs 0.180**.
~35 % stronger annual autocorrelation, ~23 % more volatile — and it does not continue
smoothly into the real period.

**Result: it does not help, and it hurts the models that "should" benefit from long
history.** Matched 89-SKU comparison, median sMAPE (the window-independent metric):

| model | real only | + synthetic | |
|---|---|---|---|
| naive | 0.394 | 0.394 | flat — ignores old history |
| MA3 | 0.296 | 0.293 | flat |
| MA6 | 0.310 | 0.303 | marginally better |
| Theta | 0.301 | 0.295 | marginally better |
| SARIMA plain | 0.317 | 0.298 | marginally better |
| SES | 0.300 | 0.303 | flat |
| **SBA α=.3** | **0.314** | **0.322** | **worse** |
| **SBA α=.1** | **0.303** | **0.330** | **worse** |
| **TSB** | **0.302** | **0.320** | **worse** |
| **Croston** | **0.324** | **0.336** | **worse** |
| **damped Holt** | **0.302** | **0.310** | **worse** |
| **Holt-Winters add.** | **0.287** | **0.313** | **worse — best method becomes mediocre** |
| **SARIMA seasonal** | **0.373** | **0.449** | **much worse — chases a synthetic seasonal signal** |
| **mean** | **0.344** | **0.371** | **worse** |

- **Recency models (naive, MA3, MA6) are unaffected** — they only look at the last few
  points, so extra history changes nothing.
- **Every model that integrates the full history (mean, Croston/SBA/TSB, Holt family,
  Holt-Winters, seasonal SARIMA) degrades** — they fit or average over two years of a
  synthetic pattern that doesn't hold in the real test months. **Holt-Winters goes from
  best (0.287) to mid-pack (0.313); seasonal SARIMA collapses (0.373 → 0.449).**
- **Ignore the MASE numbers in the with-synth CSV** — they drop ~0.1 across every model,
  but that is a scale artifact: the more-volatile synthetic era inflates the lag-1 naive
  denominator, shrinking MASE mechanically without any real accuracy gain. sMAPE (above)
  isn't fooled.
- The 37 SKUs that only become "evaluable" with synthetic prepended have forecasts
  resting on synthetic training data — not trustworthy.

**Conclusion: adding the synthetic history changes the answer for the worse. Keep the
purge. Model on real 2023-01 → 2026-02 only.** If longer real history ever arrives
(pre-2023 Unilever from SSM), re-test — but synthetic backfill is not a substitute.

---

## Addendum 2 — auto-ARIMA (per-SKU order selection)

The main table used two *fixed* SARIMA specs. To rule ARIMA out fairly, ran a proper
**auto-ARIMA**: per-SKU grid over (p,d,q) × seasonal (P,D,Q,12), order chosen once by
**AICc** on the pre-test training window, then the same rolling-origin 1-step backtest.
Data: `reports/arima_bakeoff_unilever_tierA.csv` (89 evaluable Tier A SKUs).

| model | MAPE med | MASE med | sMAPE med | MAPE<.20 | beats naive |
|---|---|---|---|---|---|
| **auto-ARIMA** | **0.394** | **0.936** | **0.361** | **9%** | **55%** |
| SBA α=.3 | 0.333 | 0.788 | 0.314 | 15% | 79% |
| MA3 | 0.351 | 0.819 | 0.296 | 7% | 75% |
| Theta | 0.363 | 0.792 | 0.301 | 9% | 74% |
| SES | 0.363 | 0.821 | 0.300 | 9% | 67% |
| naive | 0.448 | 1.081 | 0.394 | 4% | — |

**Auto-ARIMA is worse than every incumbent except naive**, and barely beats naive (55%
of SKUs). Head-to-head it loses to SBA α=.3 (wins only 37% of SKUs), MA3 (31%), Theta
(33%). It is the outright best method on just 17–19% of SKUs — nobody's clear winner.

**Why:** AICc keeps selecting seasonal models — 45% of SKUs got `(0,1,2)(0,1,1)₁₂` — but
with only 38 months (3 seasonal cycles), a seasonal MA term is estimated on ~3 points
per season. It fits in-sample and fails out-of-sample, exactly like the fixed seasonal
SARIMA in the main table (MASE 0.989). 38 months is simply too short for ARIMA's
AR/MA/seasonal machinery.

**Verdict: ARIMA is ruled out — fixed spec or auto-selected. Order selection does not
rescue it.** The simple methods (SBA α=.3, MA3, Theta) are both better and ~100× faster.
