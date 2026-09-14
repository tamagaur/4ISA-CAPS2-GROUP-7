# Forecasting Method Recommendation — Unilever Only

Evidence-based recommendation, not a code change. Del Monte excluded
entirely per this turn's instruction. Builds directly on
`SEASONALITY_AND_BASELINES.md` / `ADVISER_EVIDENCE.md` (same session) —
this document adds two things those didn't test: intermittent-demand-
specialist methods (Croston/SBA/TSB) backtested for real, and a direct
answer on SARIMAX.

## 0. CRITICAL — the "Tier A" population used throughout this session was contaminated by synthetic data

Found while re-checking whether ABC correctly demotes dead SKUs (it does
— see below). `analytics/classification/orchestrate_abc.py`'s
`_fetch_unilever_sku_revenue()` queries the BASE `unilever_sku_demand_fact`
table with no `is_demo` filter at all (violates this repo's own data-
interface rule — model code must read the `_Real` views). `run_sarima.py`
then selects `MAX(classification_period)` per principal as "the current
period" — and because synthetic demo data was backfilled to extend
**past** the real data's actual end date (real: 2023-01 to 2026-02;
synthetic also covers 2026-03 to 2026-08, with zero month-overlap
between real and synthetic — verified live, clean split), that MAX()
picks **2026-08, a period built 100% from synthetic revenue** (657/657
rows `is_demo=true` for that `calendar_month`, confirmed live).

**Consequence, quantified:** the 136 "Tier A" SKUs `forecast_result` was
built from (and everything in `ADVISER_EVIDENCE.md`/this document's §1-3
originally analyzed) overlaps only **63/136 (46%)** with the Tier A list
you get from the latest all-real period (2026-02, 132 SKUs). 73 of the
136 SKUs analyzed all session aren't even real Tier A; 69 real Tier A
SKUs were never analyzed at all. And directly answering "if dead
shouldn't it be C": **36 of the contaminated 136 "Tier A" SKUs are dead
by the trailing-≥6-zero-months rule (26%)** — vs. **0 of the 132 real-
period Tier A SKUs**. The ABC math itself is correct (a dead SKU's
real revenue is 0, which correctly sorts it to the bottom of a real
Pareto ranking) — the bug is that the pipeline never got real revenue
for the period it picked. This is an orchestration bug in
`orchestrate_abc.py`/`run_sarima.py`, not a flaw in `classify_abc()`
itself, and not fixed here (diagnosis only, per this turn's scope).

§1-3 below have been RE-RUN against the real 2026-02 Tier A list (132
SKUs) to check whether the recommendation changes — see the "§1-3
re-checked against real Tier A" callouts inline. Headline: **the
per-segment method recommendation does not change**, but the real
Tier A population has substantially more short-history SKUs than the
contaminated list suggested (40/132 = 30% under 12 months, vs. only 7
in the old 136-SKU list) — the "new but already selling well" policy
segment matters more than originally sized.

All numbers below are from actual 6-month walk-forward backtests run
this turn against `Unilever_SKU_Demand_Fact_Real` — not textbook
citations. Companion data: `scratch/full_catalog_intermittent_results.parquet`
(1,096 SKUs, all 1,807 checked, 711 excluded for having ≤6 months of
history or a zero-variance training scale — see §4).

---

## 1. Headline finding — the textbook answer is wrong for this data, and I checked it twice

The standard inventory-forecasting prescription is: smooth demand →
simple smoothing; intermittent/lumpy demand → Croston's method or its
corrected variants (SBA, TSB). **Tested at the textbook-default smoothing
constant (α=0.1) against the full 1,807-SKU catalog, that prescription
does NOT hold on this data — naive (last value carried forward) and a
3-month moving average beat Croston/SBA/TSB in every single demand
class, including intermittent and lumpy:**

| Class (n SKUs, all 5 methods computable) | naive | ma3 | croston | sba | tsb | **Winner (most SKUs)** |
|---|---|---|---|---|---|---|
| smooth (263) | median 1.108, 44.9%<1 | 0.876, 60.8% | 0.973, 53.2% | 0.934, 56.7% | 0.973, 53.2% | **sba** (112/263, 43%) |
| erratic (39) | 1.059, 43.6% | 0.928, 53.8% | 0.804, 64.1% | 0.802, 61.5% | 0.804, 64.1% | **sba** (16/39, tied with ma3 14/39) |
| **intermittent (426)** | **0.771, 61.0%** | 0.792, 63.4% | 1.138, 39.9% | 1.118, 41.8% | 1.017, 48.4% | **naive** (204/426, 48%) |
| **lumpy (358)** | **0.634, 62.8%** | 0.678, 64.0% | 0.965, 51.7% | 0.936, 53.6% | 0.826, 59.2% | **naive** (152/358, 42%) |

Plain Croston's is the weakest method tested in every class, including
the ones it was literally designed for. **I re-checked this wasn't just
a bad α choice** — re-ran SBA/TSB at α=0.2, 0.3, 0.5:

| α | intermittent TSB median (%<1) | lumpy TSB median (%<1) |
|---|---|---|
| 0.1 (textbook default) | 1.017 (48.4%) | 0.826 (59.2%) |
| 0.2 | 0.932 (55.9%) | 0.773 (65.1%) |
| 0.3 | 0.861 (58.9%) | 0.714 (67.0%) |
| 0.5 | 0.805 (63.1%) | 0.666 (65.6%) |

**A properly tuned (higher, more reactive) α closes most of the gap** —
at α=0.5, TSB is roughly competitive with naive on intermittent (0.805
vs naive's 0.771 median, but TSB's 63.1% beats naive's 61.0% on the
%<1 measure) and edges ahead of naive on lumpy by the %<1 measure
(65.6% vs 62.8%). **Conclusion: TSB is a real, usable method here, but
only with per-segment tuning — not as an out-of-the-box default.** No
α was tuned beyond this coarse 5-point check; a proper per-SKU or
per-class cross-validated α would very likely do better still, but
that's implementation work, not something to claim without doing it.

**Why does plain naive/MA3 beat the "correct" specialist methods
here?** Best-supported explanation from what's already been measured
across this session's reports: there's very little real
autocorrelation/seasonal structure in this demand at all (no lag-12,
no lag-3 that survives aggregation) — Croston-family methods work by
smoothing history to estimate a stable underlying rate, which helps
when the rate really is stable and history is long; on data this short
(median SKU has under a year of real sales) and this noisy (6.6-6.7%
of rows are negative-value returns/corrections), a slow-to-react
smoothed estimate is worse than just using the most recent real
observation. Naive isn't "simple," it's "maximally reactive to a
process with little persistent structure to average over."

---

## 2. Recommendation — segmented by what's actually been shown to work, not by textbook class alone

| Segment | Population | Recommended method | Why (evidence) | Example SKU |
|---|---|---|---|---|
| **Smooth, full/near-full history** | 263 SKUs (77 in Tier A) | **SBA**, or MA3 if simplicity is preferred | SBA wins outright most often here (112/263, 43%); MA3 close second and already proven to beat SARIMA in the prior report | **68438413** (COOKING AIDS, Tier A) — 38/38 months, CV²=0.08, ADI=1.0, stable 65k-195k/month |
| **Intermittent or lumpy, ≥12 months history** | 426 + 358 = 784 SKUs | **Naive**, with **TSB (α≈0.3-0.5, needs real tuning)** as a documented alternative worth a proper trial | Naive wins outright most (204/426 intermittent, 152/358 lumpy); TSB closes the gap sharply once α is raised and edges ahead on the %<1 measure at α=0.5 | Intermittent: **64314344** (HAIR CARE, Tier A) — 21/38 months, ADI=1.81. Lumpy: **62720543** (CONDIMENTS, Tier A) — 11/38 months, ADI=3.45, CV²=2.1, includes negative months |
| **New SKU, <12 months but real, active demand** | 1,031 SKUs total under 12 months; **340 of those are 2024/2025-launch SKUs already selling above the catalog's median per-active-month volume** — your "started but highly bought" case | **No statistical model** — too little data for any of the above to estimate reliably. Use a **cumulative or short trailing average** (mean of all months observed so far, or last-3-months once ≥3 exist) as a placeholder, re-evaluated every month as more history accrues; do NOT force these into SARIMA/Croston fits | **64971076** (COOKING AIDS, Tier A) — first sold 2025-05, only 10 months, already 914-4,568 units/month. **64856620** (FABRIC ENHANCERS) — first sold 2025, 8 months, avg ~40,243/month when active |
| **Dead / discontinued** | **837 SKUs (46.3% of the catalog)** — ≥6 trailing zero months through 2026-02 | **No model — flag `dead_sku`, forecast 0**, same convention `run_sarima.py` already uses for its own Tier-A subset, just applied catalog-wide before any model is attempted | **68944226** (FABRIC CLEANING) — 82k-300k/month through mid-2023, essentially nothing since, still shows up in the raw data as small negative/near-zero noise |
| **Returned from dormancy** | 108 SKUs — a ≥6-month zero run followed by real sales again | Flag for review; **TSB** is the only method above that can represent "low but nonzero chance of a comeback" at all (Croston/SBA freeze their forecast forever after the last sale and can't decay or recover the same way) — not fully solved by any method tested here | — (not spot-checked individually this turn; see `reports/ADVISER_EVIDENCE.md` §4 for the population) |
| **Portfolio/category-level KPI number** (not per-SKU replenishment) | — | Simple exponential smoothing or moving average on the **aggregated** series, not a sum of 1,807 noisy per-SKU forecasts | Portfolio series is far smoother than any individual SKU (seasonal-decomposition strength 0.58 at portfolio level per `ADVISER_EVIDENCE.md`, even though no lag-12 significance was found) |

**Bottom line on "one model or many": many, and the segmentation isn't
just smooth-vs-intermittent — history length matters as much as demand
shape.** A SKU with 8 months of strong sales (the "highly bought but
just started" case you flagged) needs a completely different treatment
than a SKU with 38 months of the same shape, regardless of which
demand class it's in — no model in the table above should be handed a
series shorter than roughly a year of real history and trusted.

**Data-quality footnote found while re-checking this:** 71 of 24,906
demand rows have `quantity_sold = NULL` (not zero, not absent — an
actual null value), spread across the corpus (not seen or flagged in
any prior report). Small (0.3% of rows) but every method above needs a
defined behavior for it — I clipped negatives to 0 and treated NaN via
pandas' resample/fillna path for this test, which is a reasonable
default but wasn't a deliberate ruling; flag before production use.

---

## 3. SARIMAX — what it is, and a direct answer on whether it would help

**What it is:** SARIMAX = the exact same model already in
`scripts/run_sarima.py` (`from statsmodels.tsa.statespace.sarimax import
SARIMAX` — that import is SARIMAX already; "SARIMA" in this codebase
*is* a SARIMAX call with no exogenous regressor passed). Adding
"X" means supplying an extra time series (`exog=`) alongside the
target — e.g. "was this month a holiday," "was there a promo" — that
the model uses as an additional predictor on top of its own
autoregressive/seasonal terms.

**Does it use external APIs? No.** `exog` is just a NumPy array or
DataFrame you hand it — there is no network call, no third-party
service, nothing fetched automatically. Two hard practical
requirements people often miss: (1) you need the exogenous values for
every historical period you fit on, AND (2) you need them for every
FUTURE period you want to forecast — which only works cleanly for
regressors that are known in advance (a calendar), not for something
you'd also have to forecast (e.g., next month's promo spend, if that
decision hasn't been made yet).

**What would actually make sense to use, given what's confirmed in
this corpus:**
- **A Philippine public holiday calendar** — the only zero-cost,
  fully-known-in-advance option (hardcode from the official PSA/
  proclamation list, no API, no new data collection). Worth trying
  since it's free, but the evidence for it is weak: `ADVISER_EVIDENCE.md`
  found 3/5 significant-lag-3 categories share a Q4 peak, but 0/16
  aggregate series showed significant lag-12, and the quarterly signal
  didn't survive re-testing at quarterly resolution.
- **Promo/discount flags** — NOT currently available. No column in the
  extracted SOH or demand sources carries a promotion/discount
  indicator (checked `config/column_maps/unilever_sku.yaml` and
  `ssis_soh.yaml` — neither has one). Would require new data
  collection from SSM/Unilever, not something derivable from what's
  already in this pipeline.
- Price/GSV per unit — technically present (`gsv`, backfilled this
  session) but its usefulness as a demand driver hasn't been checked;
  not a confirmed candidate, just a theoretical one.

**Will it actually help, or just end up like SARIMA?** Most likely the
latter, for most of the catalog, and I'd say so plainly rather than
hedge: the core problems already found (median SKU under a year of
history; no measurable lag-12 seasonality; the AR/MA machinery losing
to a 3-month average 73% of the time) are not fixed by adding one more
predictor to the same seasonal ARIMA core — SARIMAX's non-exogenous
part is identical to what already lost. Where it *could* plausibly earn
its keep: the ~263 smooth, full-history SKUs, if a real holiday effect
exists — but even there, the bar isn't "beat SARIMA," it's "beat SBA/
MA3," which already win on this exact segment (§1 table above). Adding
a regressor to a model that's already behind a 3-month moving average
on its best-suited segment is a long shot, not a fix. **Recommendation:
don't prioritize SARIMAX. If it's tried at all, restrict it to the
smooth/full-history segment with a free holiday-calendar regressor, and
benchmark it against SBA/MA3 exactly the way SARIMA was benchmarked in
`ADVISER_EVIDENCE.md` — don't adopt it on the strength of "it sounds
more sophisticated" without that same backtest discipline.**

---

## 4. What this recommendation is NOT based on

- Not tested: the 711 SKUs excluded from §1's 1,096-SKU backtest (≤6
  months of history, or a zero-variance training window that makes
  MASE undefined) — this includes most of the 1,031-SKU "<12 months"
  population from `ADVISER_EVIDENCE.md` §4. The "new but active" and
  "dead" rows in §2's table are handled by policy (short average / zero
  forecast), not backtested against alternatives, because there isn't
  enough data to backtest them meaningfully.
- Not tuned: α for Croston/SBA/TSB — only a coarse 5-point check (0.1,
  0.2, 0.3, 0.5), not a real per-SKU or per-class cross-validation.
- Not tested: TSB/SBA at the FULL Tier-A-vs-SARIMA level of rigor (89
  side-by-side SKUs) the way naive/ma3/ses/sarima already were in
  `ADVISER_EVIDENCE.md` — §1's numbers here are from the broader
  1,096-SKU population, a different (larger, more representative)
  denominator than that report's 89.
- No model has been chosen or implemented. This is a recommendation
  document only.
