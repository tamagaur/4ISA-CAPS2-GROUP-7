# Adviser Evidence Pack — SARIMA Replacement Discussion (Unilever Only)

Read-only diagnosis. No model code changed, nothing refit, nothing
written to `forecast_result`. Numbers only — no recommendation is made
in this document. Live queries against `Unilever_SKU_Demand_Fact_Real`,
`ABC_Classification`, `Forecast_Result`, plus the SOH-derived category
mapping already used in `reports/SEASONALITY_AND_BASELINES.md`.

---

## 1. The quarterly (lag-3) signal, characterized

**The 5 categories with significant lag-3 monthly ACF:**

| Category | ACF(3) | Ljung-Box p | SKUs | Tier mix (A/B/C) | Revenue share |
|---|---|---|---|---|---|
| DRESSINGS | 0.803 | 4.6e-18 | 45 | 6/6/33 | 2.87% |
| MINI MEALS | 0.691 | 9.5e-15 | **1** | 0/0/1 | 0.01% |
| CONDIMENTS | 0.576 | 1.3e-13 | 91 | 17/15/59 | 12.23% |
| SCRATCH COOKING AIDS | 0.565 | 5.1e-08 | 32 | 2/1/29 | 1.79% |
| HAIR CARE | 0.481 | 1.1e-3 | 298 | 36/33/229 | 24.01% |

**Caveat on MINI MEALS: this "category" is a single SKU.** Its lag-3
ACF is that one series' own autocorrelation, not an aggregate pattern —
treat it as a per-SKU finding that happens to be filed under a
category, not evidence of a MINI MEALS category effect.

**Monthly seasonal profile (average quantity by calendar month,
1=Jan..12=Dec) — the actual shape:**

| Category | Low month(s) | High month(s) | Shape |
|---|---|---|---|
| DRESSINGS | Jul-Aug (≈19.7-19.8k) | Mar (31.9k), Oct (31.1k) | Trough mid-year (Apr-Aug), peaks spring and Q4 |
| MINI MEALS | Apr (22) | Jan (110), Oct (87) | Erratic single-SKU swings, Jan spike stands out |
| CONDIMENTS | Feb (51.8k) | Oct (114.2k), Nov (104.7k) | Clear ramp Jun→Oct, holiday-season-shaped |
| SCRATCH COOKING AIDS | Dec (5.4k), Jul (6.4k) | Oct (16.9k) | Similar Q4 peak, but December itself is the year's lowest |
| HAIR CARE | Oct (564k) | Mar (1.04M), Jun (1.05M) | Higher Q1/Q2, lower H2 — opposite direction from the other 4 |

CONDIMENTS, DRESSINGS, and SCRATCH COOKING AIDS all show a **Q4 (Sep-
Nov) peak** — three of the five point the same direction. HAIR CARE is
the outlier, peaking in Q1/Q2 and troughing in Q4 — the opposite
seasonal direction. MINI MEALS (n=1 SKU) is too erratic/small to read a
clean shape from.

**Do the 5 share anything?** No obvious common driver:
- **SKU count** spans 1 to 298 — no consistent size.
- **Tier mix**: all 5 are majority Tier C, roughly matching the overall
  corpus's C-heavy composition (1,493/1,807 = 83% C corpus-wide) — not
  a distinguishing feature.
- **Revenue share** spans 0.01% (MINI MEALS) to 24.01% (HAIR CARE) — the
  single biggest category by revenue and the single smallest are both
  on this list, so it isn't a size/revenue effect either.
- The one soft pattern: 3 of 5 (CONDIMENTS, DRESSINGS, SCRATCH COOKING
  AIDS) share a Q4 peak — plausibly a cooking/condiment-adjacent
  holiday-season effect, but that's 3 categories, not 5, and HAIR CARE
  (the largest by far) moves opposite.

**Re-tested at lag 3 on QUARTERLY-aggregated series (m=4, i.e. lag 3 =
9 months on the quarterly axis) — the signal does NOT strengthen, it
weakens into statistical noise:**

| Category | Quarterly n | ACF(3) | 95% bound | Bound-sig? | Ljung-Box p |
|---|---|---|---|---|---|
| PORTFOLIO (reference) | 13 | -0.053 | 0.544 | no | 0.306 |
| CONDIMENTS | 13 | 0.176 | 0.544 | no | 0.065 |
| DRESSINGS | 11 | 0.179 | 0.591 | no | 0.002 |
| HAIR CARE | 13 | 0.012 | 0.544 | no | 0.245 |
| MINI MEALS | 13 | 0.241 | 0.544 | no | <0.001 |
| SCRATCH COOKING AIDS | 11 | 0.085 | 0.591 | no | 0.013 |

0/5 significant by the isolated bound test once aggregated to
quarters — the same pattern as lag 12 in the prior report: Ljung-Box
still flags 3 of 5 as "significant" (driven by lower-lag, not lag-3-in-
quarter-units autocorrelation specifically), but the direct test comes
up empty. With only 11-13 quarterly observations the significance bound
widens sharply (0.54-0.59 vs 0.32 monthly), so this is as much a
sample-size problem as a "no effect" finding — **inconclusive, not a
strengthened signal.**

---

## 2. Baseline table, publication-ready

6-month walk-forward holdout (expanding window, real actuals fed in as
they become available), MASE scale = mean absolute seasonal (period=12)
training-set difference, same convention `evaluate_sarima()` uses.
3 of 136 Tier A SKUs (n≤6 months total) can't be backtested at all and
are excluded from every row below.

**Populations differ per method and this is not hidden**: the 5
baselines are evaluable for up to 133 Tier A SKUs (each capped lower by
its own lookback requirement, e.g. seasonal_naive needs ≥12 months);
SARIMA-existing only has a stored result for **89** SKUs (the ones
`run_sarima.py` reached `status='ok'` for — the other 47 Tier-A SKUs are
`insufficient_data`/`dead_sku`, no SARIMA MASE exists to compare). The
"wins" column below is computed on the SARIMA-comparable 89-SKU subset
(the only set where all 6 methods are simultaneously computable) so the
win count is a fair, like-for-like comparison; the mean/median/%<1
columns for the 5 baselines are shown BOTH over their own full
population and, in parentheses, restricted to that same 89-SKU
SARIMA-comparable subset.

| Method | n (own pop.) | mean MASE | median MASE | %MASE<1 | n (89-subset) | mean (89) | median (89) | %<1 (89) | **Wins (of 89)** |
|---|---|---|---|---|---|---|---|---|---|
| naive | 130 | 1.362 | 0.909 | 57.7% | 89 | 1.145 | 0.990 | 52.8% | 11 |
| seasonal_naive | 115 | 3.212 | 1.082 | 43.5% | 89 | 1.288 | 1.028 | 47.2% | 15 |
| ma3 (3-month avg) | 129 | 1.630 | 0.838 | 62.0% | 89 | 1.001 | 0.795 | 64.0% | **31** |
| ma6 (6-month avg) | 125 | 2.051 | 0.913 | 54.4% | 89 | 1.079 | 0.901 | 57.3% | 11 |
| ses (simple exp. smoothing) | 130 | 1.810 | 0.829 | 61.5% | 89 | 1.051 | 0.885 | 61.8% | 6 |
| **SARIMA (existing)** | 89 | 4.724 | 1.285 | 37.1% | 89 | 4.724 | 1.285 | 37.1% | 15 |

Wins sum to 89 (31+15+15+11+11+6=89). **MA3 wins outright on 31/89
(35%) — more than SARIMA and seasonal_naive combined.** SARIMA ties
seasonal_naive for second place on win count (15 each) despite having
by far the worst mean (4.724, next-worst is seasonal_naive's own
1.288 own-population mean) and worst median (1.285) and the lowest
%MASE<1 (37.1%) of all 6 methods.

---

## 3. Demand class × winning method

Crossed the smooth/erratic/intermittent/lumpy classification (Syntetos-
Boylan, from the prior Demand Diagnosis report) against each SKU's
outright-winning baseline, over the 115 Tier-A SKUs where all 5
baselines are computable. (0 `erratic` and 0 `unclassifiable` SKUs exist
in Tier A at all — every Tier-A SKU with enough history to backtest is
smooth, intermittent, or lumpy.)

| class | ma3 | ma6 | naive | seasonal_naive | ses | n |
|---|---|---|---|---|---|---|
| smooth | 31 (40.3%) | 10 (13.0%) | 12 (15.6%) | 18 (23.4%) | 6 (7.8%) | 77 |
| intermittent | 5 (16.7%) | 7 (23.3%) | 10 (33.3%) | 5 (16.7%) | 3 (10.0%) | 30 |
| lumpy | 0 (0.0%) | 3 (37.5%) | 4 (50.0%) | 0 (0.0%) | 1 (12.5%) | 8 |

**The winning method tracks the class — this is not noise.** Smooth
demand favors MA3 by a wide margin (40.3%, roughly double any other
method) — exactly what theory predicts (a stable series rewards
averaging out short-term noise). Intermittent and lumpy demand both
shift sharply toward `naive` (33.3% and 50.0% respectively) and away
from MA3 (16.7%, 0.0%) — also consistent with theory: averaging several
months of a mostly-zero series systematically undershoots the months
that do have demand, while carrying forward the last actual value does
not. **Caveat: lumpy has only 8 SKUs in this subset** — the 50%/37.5%
split there is 4 and 3 SKUs, not a large-sample result; treat the
smooth and intermittent rows as the more load-bearing ones.

---

## 4. Scope of the problem (all 1,807 SKUs)

**Months of non-zero demand** (out of the 38-month corpus, 2023-01..2026-02):

| Bucket | Count | % |
|---|---|---|
| ≥24 months | 369 | 20.4% |
| 12-23 months | 407 | 22.5% |
| <12 months | 1,031 | 57.1% |

**First month a SKU ever sold:**

| Year | SKUs |
|---|---|
| 2023 | 962 |
| 2024 | 442 |
| 2025 | 323 |
| 2026 | 80 |

(2026 covers only Jan-Feb of the corpus — 80 "new" SKUs in 2 months is
a real count, not filtered further here; worth a second look outside
this diagnosis if it seems high.)

**Returned from dormancy** (a zero-run of ≥6 consecutive months,
somewhere after the SKU's first sale, followed by at least one more
non-zero month — i.e. not simply "not launched yet" and not the
trailing "looks dead" case below): **108 SKUs (6.0%)**.

**Likely dead** (the most recent 6+ consecutive months, through
2026-02, are all zero): **837 SKUs (46.3%)**.

These four counts size the population each candidate method would
actually need to handle: roughly half the catalog (46%) looks dormant/
dead as of the corpus's end, 57% have fewer than 12 months of real
sales ever, and a non-trivial 6% swing between dead and active at least
once — a single method/threshold choice has to cover all of this, not
just the well-behaved Tier-A slice the tables above focus on.

---

## 5. The two outlier SKUs — full history

**SKU 68809314** (23 months with any recorded activity):

| Month | Qty | Net amount |
|---|---|---|
| 2023-01 | 100,215 | 604,596.17 |
| 2023-02 | 151,123 | 908,244.43 |
| 2023-03 | 108,884 | 658,935.66 |
| 2023-04 | 81,181 | 489,845.25 |
| 2023-05 | 90,168 | 541,248.62 |
| 2023-06 | 134,033 | 798,948.42 |
| 2023-07 | 32,521 | 195,807.74 |
| 2023-08 | 100,263 | 607,025.67 |
| 2023-09 | 19,346 | 115,076.06 |
| **2023-10** | **-42,335** | **-255,273.26** |
| 2023-11 | -57 | -337.86 |
| 2023-12 | 10,079 | 60,687.55 |
| 2024-01 | -19 | -113.72 |
| 2024-02 | -23 | -137.67 |
| 2024-05 | -2 | -12.34 |
| 2024-09 | 1,440 | 8,619.63 |
| 2024-11 | 1,440 | 8,871.52 |
| 2024-12 | 864 | 5,232.76 |
| 2025-01 | 672 | 3,835.23 |
| 2025-02 | 589 | 3,634.71 |
| 2025-03 | 120 | 740.51 |
| 2025-06 | 276 | 1,703.19 |
| 2025-07 | -25 | -153.79 |

**SKU 68349001** (17 months with any recorded activity):

| Month | Qty | Net amount |
|---|---|---|
| 2023-01 | 173,430 | 1,045,410.06 |
| 2023-02 | 81,076 | 488,552.05 |
| 2023-03 | 107,811 | 651,827.55 |
| 2023-04 | 107,801 | 649,272.46 |
| 2023-05 | 127,037 | 763,123.71 |
| 2023-06 | 140,591 | 836,774.83 |
| 2023-07 | 35,317 | 213,273.61 |
| 2023-08 | 113,761 | 688,906.84 |
| 2023-09 | 11,687 | 69,739.90 |
| **2023-10** | **-35,596** | **-214,100.03** |
| 2023-11 | -62 | -367.69 |
| 2023-12 | 342 | 2,108.50 |
| 2024-01 | 10 | 62.08 |
| 2024-02 | -2 | -12.34 |
| 2024-06 | 24 | 145.89 |
| 2024-08 | -1 | -6.17 |
| 2024-12 | 288 | 1,777.22 |

**Answer: part of a pattern, not a one-off correction.** Both SKUs show
the identical shape: strong five-to-six-figure monthly volume through
Sep-2023, a large negative in **the same month, Oct-2023**, then a
**permanent step-down** to low-hundreds/low-thousands (or zero) for the
rest of the recorded history, punctuated by several more small negative
months (Nov-2023, Jan/Feb-2024, and later isolated ones). The Oct-2023
negative isn't an isolated blip sitting in an otherwise-normal series —
it coincides exactly with both SKUs' volume collapsing and never
recovering to anything close to their 2023 run-rate. Two different SKUs
sharing the same collapse month, the same shape, and roughly the same
relative magnitude (the Oct-2023 negative is ~30-40% of a typical 2023
month for both) points to a real, shared business event around that
date — a delisting, reformulation, or bulk return/write-off affecting
both SKUs together — rather than a random data-entry sign error. The
exact cause isn't identifiable from this table alone (diagnosis-only
scope, not investigated further here).

---

## Summary

1. Five categories show significant monthly lag-3 ACF, no shared driver
   (size, tier, revenue) explains why those five; 3 of 5 share a Q4
   peak. Re-testing at quarterly resolution doesn't strengthen the
   signal — it disappears into a much wider significance bound at n=11-13.
2. Across a full 6-method table, **MA3 wins outright on 31/89 (35%)
   SARIMA-comparable SKUs — more than double SARIMA's 15/89 (17%).**
   SARIMA has the worst mean, worst median, and worst %MASE<1 of all 6
   methods.
3. The winning baseline tracks demand class in the expected theoretical
   direction (smooth→MA3, intermittent/lumpy→naive) — this is a real
   pattern, not noise, though the lumpy row is only 8 SKUs.
4. Scope: 46% of the full 1,807-SKU catalog looks dead (≥6 trailing zero
   months), 57% have under a year of real sales ever, only 20% clear
   the ≥24-month bar `run_sarima.py` requires to even attempt a fit.
5. The two large negative-quantity outliers (68809314, 68349001) are
   not isolated data errors — both show a shared Oct-2023 collapse
   event with a permanent step-down afterward, the signature of a real
   business event, not a sign bug.
