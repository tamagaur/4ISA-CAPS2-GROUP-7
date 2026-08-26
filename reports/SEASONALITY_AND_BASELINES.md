# Seasonality & Baseline Bake-off — Unilever Only

Diagnosis only. No model code changed, nothing refit, nothing written to
`forecast_result`. All numbers are from live queries against
`Unilever_SKU_Demand_Fact_Real` plus the raw staged SOH data
(`staging/ssis_soh/`, category source) and `Forecast_Result`'s existing
rows — read-only.

---

## 1. Full seasonality test — all 136 Tier A SKUs (not a sample)

Of 136 Tier A SKUs, **99 have ≥24 months of series length** (`run_sarima.py`'s
own per-SKU date range, monthly-resampled, zero-filled — same
construction as the prior report). The other 37 are shorter and excluded
here for the same reason `run_sarima.py` itself routes them to
`insufficient_data`.

Two different significance tests are reported, because they answer
different questions and **giving only one is misleading**:

- **Ljung-Box at lags=[3,6,12]** (`alpha=0.05`) — the standard library
  call (`acorr_ljungbox`) tests the JOINT null "no autocorrelation in
  lags 1 through L" for each L. A significant result at L=12 does not
  mean lag 12 itself is autocorrelated — it can be driven entirely by
  lag 1 or 2 (e.g. intermittent series where consecutive zero-months
  cluster).
- **Bound test at lag 12 alone** — `|ACF(12)| > 1.96/√n`, the same test
  the prior sample-of-20 report used, isolating lag 12 specifically.

| Test | Significant | of | % |
|---|---|---|---|
| Ljung-Box through lag 3 | 42 | 99 | 42.4% |
| Ljung-Box through lag 6 | 41 | 99 | 41.4% |
| Ljung-Box through lag 12 | 45 | 99 | 45.5% |
| **Bound test, lag 3 alone** | 24 | 99 | 24.2% |
| **Bound test, lag 6 alone** | 10 | 99 | 10.1% |
| **Bound test, lag 12 alone** | **5** | **99** | **5.1%** |

**This confirms, not overturns, the prior 0/20 sample finding, once lag
12 is isolated correctly.** The Ljung-Box-through-12 number (45.5%
"significant") looks like it overturns the earlier result, but spot-
checking individual SKUs shows this is an artifact: e.g. SKU 21051980
has `ACF(12) = 0.022` (essentially zero) yet `Ljung-Box p = 1.2e-6`
(highly "significant") — the significance is coming from lag 1-2
autocorrelation (intermittent demand clustering), not lag 12. The
isolated bound test at lag 12 gives **5.1% significant — statistically
indistinguishable from the 5% false-positive rate you'd expect at
α=0.05 with no real effect at all.** Lag 3 shows more signal (24.2%,
well above chance) — plausibly a quarterly ordering/replenishment
cadence rather than calendar seasonality, but real enough to be worth a
separate look. **Lag 12 (annual) seasonality is not supported by
per-SKU data even at full-population scale.**

Full per-SKU results: `reports/seasonality_tierA_full.csv`.

---

## 2. Seasonality at higher aggregation — THE KEY TEST

Built monthly series at portfolio level (sum of ALL 1,807 Unilever SKUs,
not just Tier A) and at category level, using each SKU's MOST-RECENT
CATEGORY DESC from the SOH data (R13's ruling) — **1,427/1,807 (79%)
demand-fact SKUs have a category match**; the rest (SOH-only or never
snapshotted) are excluded from the category breakdown but the portfolio
sum still includes every SKU. Note: this SOH-derived "latest per SKU"
mapping yields **17 distinct categories** among matched SKUs, not the 18
seen across the full snapshot history (some category value's SKUs never
have it as their OWN latest snapshot — a real, if minor, discrepancy
from the earlier per-snapshot count, not a data error).

| Series | n (months) | ACF(3) | sig(3) | ACF(6) | sig(6) | ACF(12) | sig(12) | LB p(12) | Seasonal strength* |
|---|---|---|---|---|---|---|---|---|---|
| **PORTFOLIO (all SKUs)** | 38 | 0.286 | no | -0.010 | no | 0.280 | **no** | 0.167 | 0.582 |
| CONDIMENTS | 38 | 0.576 | **yes** | 0.317 | no | 0.232 | no | <0.001 | 0.499 |
| COOKING AIDS | 38 | -0.011 | no | 0.017 | no | 0.044 | no | 0.934 | 0.350 |
| DEODORANTS & FRAGRANCES | 38 | 0.072 | no | -0.164 | no | 0.171 | no | 0.459 | 0.605 |
| DRESSINGS | 32 | 0.803 | **yes** | 0.506 | **yes** | -0.188 | no | <0.001 | 0.148 |
| FABRIC CLEANING | 38 | 0.307 | no | 0.129 | no | 0.189 | no | <0.001 | 0.582 |
| FABRIC ENHANCERS | 38 | -0.061 | no | -0.267 | no | 0.244 | no | 0.032 | 0.681 |
| HAIR CARE | 38 | 0.481 | **yes** | 0.032 | no | 0.251 | no | 0.041 | 0.520 |
| HOME & HYGIENE | 38 | -0.083 | no | -0.072 | no | 0.262 | no | 0.340 | 0.533 |
| MINI MEALS | 38 | 0.691 | **yes** | 0.463 | **yes** | -0.039 | no | <0.001 | 0.281 |
| ORAL CARE | 38 | 0.304 | no | 0.089 | no | 0.120 | no | 0.011 | 0.469 |
| OTHER FOODS | 38 | 0.159 | no | 0.181 | no | 0.055 | no | 0.381 | 0.313 |
| OTHER NUTRITION | 19 | 0.315 | no | -0.086 | no | -0.164 | no | 0.124 | n/a (<24mo) |
| SCRATCH COOKING AIDS | 32 | 0.565 | **yes** | 0.323 | no | -0.113 | no | <0.001 | 0.388 |
| SKIN CARE | 38 | -0.015 | no | -0.061 | no | 0.261 | no | 0.201 | 0.649 |
| SKIN CLEANSING | 38 | 0.038 | no | -0.313 | no | 0.039 | no | 0.680 | 0.506 |

\* "Seasonal strength" = `1 - var(residual)/var(detrended)` from an
additive `seasonal_decompose(period=12)` — a variance-explained figure,
**not a significance test**. Decomposition always extracts *some*
periodic component by construction (it's a by-calendar-month average);
a high value here shows the 12-month averaging captures real variance,
but with only 38 months (~3 cycles) it cannot by itself distinguish a
genuinely recurring pattern from 2-3 large one-off swings that happen to
land in a way the by-month averaging picks up.

**Plain answer: no, aggregation does not confirm annual seasonality
either.** Lag-12 ACF is not significant anywhere — not the portfolio,
not one of the 15 testable categories (0/16). Several categories DO show
significant lag-3 (quarterly) autocorrelation (CONDIMENTS, DRESSINGS,
HAIR CARE, MINI MEALS, SCRATCH COOKING AIDS — 5/16), and DRESSINGS/MINI
MEALS also clear lag-6. That's a real, mild signal worth investigating
as a quarterly cadence, but it is not the annual pattern SARIMA's
seasonal term (period=12) is built to capture. The moderate-to-high
"seasonal strength" decomposition numbers (portfolio 0.58, several
categories 0.50-0.68) are suggestive but not corroborated by any
significant lag-12 correlation test at any level tested — treat them as
inconclusive, not as confirmation.

---

## 3. Negative and zero demand

- **Rows with `quantity_sold < 0`: 1,649** / 24,906 (6.6%)
- **Rows with `net_amount < 0`: 1,681** / 24,906 (6.7%, 2 rows have null `net_amount`)
- **Zero-quantity rows: 0.** Confirmed again this session — the fact
  table never carries an explicit `quantity_sold = 0` row; a month with
  no sale is simply an absent row (already established in the prior
  Demand Diagnosis report, re-verified here).

**Overlap: 1,646 of 1,649 negative-quantity rows (99.8%) are ALSO
negative `net_amount`.** Only 3 rows have negative quantity but
non-negative amount, and only 35 have negative amount but non-negative
quantity. This tight co-occurrence is itself evidence against a sign
error — a sign-flip bug would not consistently hit both columns
together at a 99.8% rate.

**Concentration — both, not one or the other:**
- By SKU: 815 of 1,807 SKUs (45%) have at least one negative-quantity
  month; median is only 1 such row per affected SKU (75th percentile 2),
  but a long tail exists up to 16 negative rows for a few SKUs
  (67223599, 67737497, 68450223).
- By month: every one of the 38 months has at least some negative rows
  (range 18-100), but **2024-02 stands out sharply (100 rows, roughly
  2-3x the typical ~30-60/month background rate)**, with 2025-12 a
  smaller second bump (88). Looks like periodic bulk
  correction/reconciliation events layered on top of a steady low-level
  background rate of individual returns, not a single systemic bug.

**Magnitude — consistent with returns/corrections, not a sign error:**
negative rows have median magnitude **-5** (25th/75th percentile -16/-2),
far smaller than the typical positive sale (median +155, 25th/75th
percentile +35/+866). If this were a sign-flip bug on real sales
figures, negative and positive magnitudes would look similar in scale;
instead negatives are small, one-off adjustments layered on top of much
larger positive volumes — the plausible-cause read is **returns/credit
memos**, not a data-entry sign error. One clear outlier worth a separate
look: SKU 68809314, 2023-10, `quantity_sold = -42,335` /
`net_amount = -255,273.26` (and a second, SKU 68349001, same month,
-35,596 / -214,100.03) — both far larger than anything else in the
negative tail and both landing in the same month; worth asking Yuan
whether October 2023 had a real bulk return/write-off event for these
two SKUs specifically.

**Of the 89 `status='ok'` SKUs: 15 have at least one negative month
somewhere in their full history** (not just the holdout window — this
extends Part 3 of the prior report, which only checked the holdout
slice for the 15 capped-MAPE rows).

---

## 4. Baseline bake-off — backtest only, last 6 months held out

Walk-forward (expanding window, using real actuals as they become
available — not a single static multi-step forecast) for 4 non-fitted
baselines, MASE computed with the identical scale convention
`analytics/forecasting/sarima.py::evaluate_sarima()` uses (mean absolute
seasonal (period=12) difference on the TRAINING portion, i.e. everything
before the last 6 months; falls back to the lag-1 naive difference if
training is too short).

**Caveat, stated plainly:** this is NOT a perfectly controlled
comparison against SARIMA's stored `mase`. SARIMA's own holdout is 20%
of each series (whatever that works out to per SKU, from
`fit_sarima(..., holdout_fraction=0.2)`), evaluated as one static
multi-step forecast from a single origin — not the fixed last-6-months
walk-forward backtest used here. Different window, different evaluation
style, same MASE *scale* convention. Directionally informative, not an
apples-to-apples number.

3 of 136 Tier A SKUs have ≤6 months of history total and can't be
backtested with a 6-month holdout at all (67326639, 64367602, 64817204
— n=5, 6, 6). **133 evaluated.**

**Per-method MASE (all 133 evaluable SKUs, each method's own valid subset — not every method is computable for every SKU, e.g. seasonal_naive needs ≥12 months of prior history):**

| method | n evaluable | mean MASE | median MASE |
|---|---|---|---|
| naive | 130 | 1.362 | 0.909 |
| seasonal_naive | 115 | 3.212 | 1.082 |
| ma3 (3-month avg) | 129 | 1.630 | 0.838 |
| ma6 (6-month avg) | 125 | 2.051 | 0.913 |

**Wins (lowest MASE among the 4 baselines, 115 SKUs where all 4 are computable):**

| method | wins |
|---|---|
| ma3 | 40 |
| naive | 28 |
| seasonal_naive | 24 |
| ma6 | 23 |

**MA3 (simple 3-month moving average) is the single best baseline
overall** — lowest median MASE (0.838) and most outright wins (40/115,
35%). Seasonal naive is the weakest despite being the "seasonal" choice
— consistent with Part 1/2's finding that lag-12 seasonality isn't
really there to exploit.

**vs. SARIMA (89 `status='ok'` rows, all 4 baselines + SARIMA computable for all 89):**

| method | median MASE |
|---|---|
| **SARIMA (existing)** | **1.285** |
| naive | 0.990 |
| seasonal_naive | 1.028 |
| ma3 | 0.795 |
| ma6 | 0.901 |

**SARIMA beats ALL 4 baselines outright on only 16 of 89 SKUs (18%).**
Per-baseline win counts (SARIMA strictly better than that one method):

| baseline | SARIMA wins vs it | / 89 |
|---|---|---|
| naive | 32 | 36% |
| seasonal_naive | 45 | 51% |
| ma3 | 24 | 27% |
| ma6 | 27 | 30% |

**Direct answer: no, SARIMA mostly does not beat a moving average on
this data.** MA3 alone beats SARIMA on 65/89 SKUs (73%) by MASE. SARIMA
does better than the naive and seasonal-naive baselines more often than
not (beats naive 36% vs a coin-flip-ish comparison — actually below
half — and seasonal_naive 51%, just above half), but loses to the
3-month moving average on nearly three-quarters of the SKUs it was
actually fit for, and its MASE distribution (mean 4.72, driven by a long
tail up to 106) is far less stable than any of the four simple
baselines (all four have means under 2.1, medians under 1.1). Combined
with Part 1/2's finding of no real lag-12 seasonality, this is
consistent: SARIMA's seasonal machinery has little real structure to
exploit here, and a much simpler method usually matches or beats it.

Full per-SKU results: `reports/baseline_bakeoff_vs_sarima.csv`.

---

## Summary

1. **Isolating lag 12 correctly matters.** Joint Ljung-Box through lag 12
   looks like 45.5% of Tier A SKUs are seasonal; testing lag 12 alone
   shows only 5.1% — statistically indistinguishable from chance at
   α=0.05. The 0/20 sample finding is **confirmed**, not overturned.
2. **Aggregation doesn't rescue it either.** Portfolio and all 15
   testable categories: 0/16 significant lag-12 ACF. Lag-3 (quarterly)
   shows real signal in 5/16 categories — a different, smaller pattern
   worth its own investigation, not the annual one SARIMA targets.
3. **Negatives (6.6-6.7% of rows) look like real returns/corrections**,
   not a sign bug — tightly co-occurring across quantity and amount
   (99.8%), small relative magnitude vs. typical sales, spread across
   45% of SKUs and every month with two clear bulk-correction spikes
   (2024-02, 2025-12) and one outlier pair worth a direct question to
   Yuan (SKU 68809314 & 68349001, both 2023-10).
4. **SARIMA loses to a 3-month moving average on 73% of the SKUs it
   actually produced a result for**, and beats every one of the 4 simple
   baselines outright on only 18% of them. Given findings 1-2, this
   isn't surprising — there's little real seasonal structure in this
   demand profile for a seasonal model to have an edge on.
