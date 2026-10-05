# Forecast model audit — 2026-10-03

Read-only and offline: one read-only database pull, then everything ran on the local copy. No production code
changed. Branch `kelvin/model-audit`, cut from `kelvin-etl` 953cda3. Unilever only: Del Monte has no
product-level sales, so it has no product forecast to audit.
Quality-checked 2026-10-03 (independent recompute, every number traced, arithmetic, wording, repo hygiene):
see the Quality check section near the end.

## Headline (restated 2026-10-03: quote the at-the-time cohort)

**Basis:** one-month-ahead forecasts, every month 2023-10..2026-02 (29 months), Unilever real rows only.

- **Served** = the router's forecast (the router picks a model by how many months a product has sold).
- **MA3** = the 3-month-average benchmark.
- **WAPE** (weighted absolute percentage error) = total absolute miss ÷ total sales. **Median product
  WAPE** is the middle product's own WAPE. **Pooled WAPE** puts all product-months together.
  **Total-level WAPE** adds all products up within each month first, so misses can cancel.
- Pesos are at selling price, VAT-inclusive (value-added tax), each product's own net amount ÷ pieces over
  its scored months (the eebd741 basis).
- Note 2026-10-05: `GET /dashboard/accuracy` reads this total-level figure as 9.8% (9.82%), not 9.9% (9.87%); the one input that differs is 3 product-months with a blank quantity, counted here as 0 sold and by the endpoint as missing (3,503 against 3,500 scored product-months).

**Why two cohorts.** The ~27% figure scored the 107 products that were Tier A in February 2026, the *last*
test month. (Tier A = the products making up the top 80% of revenue; ABC method `single` ranks them on one
month's revenue.) Choosing products by how they ended up is survivorship. Products that faded, or that were Tier A
for only a month or two, drop out of the list. Those are exactly the ones that are harder to forecast. A
fair test scores, each month, the products the system would have been forecasting *then*: those that were
Tier A in the month before. That is the at-the-time cohort, and the number to quote.

| Measure | Unit / basis | **At-the-time cohort** (Tier A the month before each test month) | Today's Tier A (as of 2026-02, the ~27% figure) |
|---|---|---|---|
| Products / product-months scored | count | **337 / 3,503** | 107 / 2,419 |
| Median product WAPE, served / MA3 | % of each product's own sales, pieces | **34.8% / 35.9%** | 26.9% / 28.0% |
| Pooled WAPE (all product-months), served / MA3 | % of sales, pieces | 29.6% / 30.2% | 28.5% / 29.1% |
| **Total-level WAPE** (all products added up each month), served / MA3 | % of total sales, **pesos** | **9.9% / 10.9%** | 10.7% / 11.4% |
| Total-level WAPE, served / MA3 | % of total sales, pieces | 15.1% / 15.5% | 14.2% / 14.9% |
| Average monthly sales | pesos per month | ₱23.54M | ₱19.09M |
| Average monthly miss (product misses summed) | pesos per month | ₱7.85M (33.3% of sales) | ₱5.72M (30.0% of sales) |
| … of which **surplus** (forecast above sales) | pesos per month, share of the miss | **₱4.39M (55.9%)** | ₱2.92M (51.1%) |
| … of which **shortage** (forecast below sales) | pesos per month, share of the miss | **₱3.46M (44.1%)** | ₱2.80M (48.9%) |
| Bias, served (+ = over-forecast) | % of sales, pieces | +5.2% | +3.3% |
| Product-months over-forecast | % of product-months | 57.3% | 51.6% |
| Products with no price basis (left out of the peso rows only) | count | 6 products, 7 product-months | 0 |

How to read it:

- **Product level.** The served model and MA3 still tie on the fair cohort (−1.1 points in both columns).
- **Total level.** The total-level peso error is *smaller* on the fair cohort, because product misses
  cancel out when more products are added up.
- **Over-forecast lean.** The lean is stronger on the fair cohort (56% of the peso miss is surplus).
  Briefly-Tier-A products are over-forecast by about 13–18% (Q3 below, `q3_cohort_lookahead.csv`).
- **Reproduction.** The 107-product column reproduces eebd741's 29-month figures exactly (largest relative
  gap 0.0, `headline_two_cohorts_check.json`).

Source: `headline_two_cohorts.csv` (`headline_pesos.py`).

## The answer in plain language

**Is the model built and tested correctly? Mostly yes.**

- **No future data leaks in.** I scrambled the month being forecast, and every month after it, in every
  product and in the training pool of XGBoost (a gradient-boosted decision-tree model, one model across all
  products). Not one forecast changed (0 pieces difference; 3 test months,
  up to 107 products each; test months 2024-06, 2025-03, 2026-01; `p1_leakage_perturbation.csv`).
- **The backtest is a genuine rolling test.** XGBoost is retrained 29 times (2023-10..2026-02), each time on
  earlier months only (`p1_checks.csv`).
- **The router works as documented.** Every product-month got the bin its sales history says
  (0 mismatches in 2,419). A bin is the router's history-length group: short = 3–11, medium = 12–23,
  long = 24+ months with sales. The long bin really serves (XGBoost + MA3) ÷ 2 (`p1_checks.csv`,
  `p1_router_bins_by_month.csv`).
- **Scoring is right.** WAPE is computed as documented, on the same rows for every model (`p1_checks.csv`).

Three things are wrong or misleading.

1. **The ~27% is measured on a survivor group.** The 107 products are the ones that were Tier A in
   **February 2026, the last test month**. The products the system would actually have been forecasting
   are those that were Tier A *at the time*. Scoring those over the same 29 months gives a median product
   WAPE of **34.8% served / 35.9% MA3**, not 26.9% / 28.0%. On that wider set (337 products), pooled WAPE
   is **29.6% / 30.2%** (fixed 107: 28.5% / 29.1%), in pieces. The served-vs-MA3 tie does not change
   (`headline_two_cohorts.csv`).
   - The products missing from the 107 are mostly products that were Tier A only briefly. ABC `single`
     ranks on one month's revenue, so a strong month puts a product in, and the next forecasts run high:
     over-forecast by about 13–18% of their sales (bias, pieces, 2023-10..2026-02; `q3_cohort_lookahead.csv`).
2. **The router's model choices were picked on the 29 months it is scored on.** So the served figure is
   slightly flattering. MA3's figure has no such choice in it (DEC-26, entry 26 of the decision register in ARCHITECTURE.md; `p1_checks.csv`).
3. **Blank quantities are read as 0 pieces.** This affects 71 real product-months (all real Unilever
   products, 2023-01..2026-02). 69 of them have a peso amount, so a sale did happen. One is in the scored set.
   Fix written on `kelvin/blank-qty-fix`: a blank quantity is now a flagged missing month, never 0
   (`p1_checks.csv`, `audit_results.json`).

**Is the ~27% noise or something fixable? Mostly noise. At most a few points look fixable, and mainly with
information from other products (the calendar effect below).**

- **Month-to-month noise is about 32% of the median product's usual level.** A perfect forecaster for a
  "level plus random noise" product, using only that product's own history, would still miss by about
  **23½–25%** (two estimation methods). The served model misses by 25.2% and MA3 by 26.8%. All are median
  product WAPE, 2023-10..2026-02, over the 89 of the 107 products with 13+ months of history
  (`p3_noise_yardsticks.csv`, `qc_recompute.csv`, `p2_count_scale.csv`).
- **Even knowing the future doesn't help.** Forecasting each month from the months on *both* sides of it
  does **worse** than MA3: median product WAPE 29.5% vs 27.2%, on the 2,312 product-months that have both
  neighbours. That is the fingerprint of independent month-to-month noise (`p3_noise_yardsticks.csv`).
- **No carry-over.** Last month's miss does not predict this month's beyond what noise alone produces.
  The correlation between consecutive misses is −0.08 for MA3; pure noise gives −0.083
  (`p3_autocorrelation.csv`).
- **No size effect.** There is no pattern by product size: median product WAPE (served) is 26.6% / 27.0% /
  26.9% for the low / middle / high sales thirds (about 35 products each; `p3_by_volume_tercile.csv`).

Two leftover patterns are real.

- **(a) A company-wide calendar effect.** In any one month, products tend to miss in the same direction.
  The month explains **11–13%** of the error variation (served / MA3, errors scaled to each product's size,
  2023-10..2026-02). Shuffling the months at random explains at most 1.8% (`p3_common_month_shocks.csv`).
  - At company-total level, the same calendar month misses the same way a year later:
    correlation **0.57** over 23 month pairs (2024-04..2026-02). The p-value is 0.004: the chance of a
    correlation this strong if there were no real calendar effect (`audit_results.json`,
    `p3_portfolio_month_effect.csv`).
  - On the company total, as % of the MA3 forecast: January was under-forecast by **34%, 29% and 35%**
    (2024, 2025, 2026). December was over-forecast by **32% and 38%** (2024, 2025;
    `p3_portfolio_month_effect.csv`).
  - MA3 and TSB (Teunter-Syntetos-Babai smoothing, the medium bin's model) cannot see this. XGBoost partly
    can: taking its month feature away worsens its median product WAPE by 2.8 percentage points (long bin;
    kelvin/forecast-error-business eebd741, `eebd741:README.md`).
- **(b) Collapses.** These are sudden drops such as DOVE SH KERATIN STRT&SILKY 288X13.5ML (64314335) in
  2025-12. The three months that start a sharp drop are **5.9%** of product-months but **12.3%** of all
  absolute error (served, pieces, 2023-10..2026-02; `p3_level_shifts.csv`).

**What should the next experiment try?** A **calendar (month-of-year) effect learned across all products**,
added to the MA3 and TSB bins.

- Test it on the products that were Tier A *at the time*.
- Choose any setting on early months and confirm on later months.
- A crude version (a company-total month factor, Q4 below) **hurt** with one year of history behind it:
  +5.0 percentage points of median product WAPE on 2024-04..2025-02 (`q4_calendar_factor.csv`).
- It **tied** with one to two years behind it: −1.4 points on 2025-03..2026-02, 95% interval −3.7 to +0.9
  (`q4_calendar_factor.csv`).
  (A 95% interval is the range the true change falls in, 95 times out of 100; one that spans 0 is a tie.)
- A pooled, shrunk index is the untried form.
- Expect at most about 1.6–1.8 percentage points. If all of the shared 11–13% were captured, the spread of the
  errors would shrink by 1 − √(1 − share) = 5.9–6.8%, which is 1.6–1.8 points on the 26.9% median WAPE
  (`qc_arithmetic.csv`, `p3_common_month_shocks.csv`).
- That 162 alternatives tied with MA3 is what this noise level predicts. Poisson/Tweedie objectives (training losses built for count data) and
  blend-weight changes gave nothing in quick checks.
- Separately, before any number is reported, restate the headline on the at-the-time cohort.

## Scope and data

| Item | Value |
|---|---|
| Source | `Unilever_SKU_Demand_Fact_Real`: real rows only (`is_demo = false`). |
| Generated rows excluded | Excluded by the **`is_demo`** flag: 12,243 `is_demo = true` rows, tagged `fill_source = synthetic_v2`, dated 2021-01..2026-08. |
| Real rows | 24,906, the same as the base table's `is_demo = false` count. 0 real rows carry a `fill_source` tag (migration 0038:56-57 forbids it). |
| Products | **107**: the cohort behind the ~27% figure (Tier A as of 2026-02, ABC method `single`; `cohort_107.csv`). Q3 also scores the at-the-time Tier A cohort: 337 products. |
| Test months | 2023-10..2026-02 (29 months), one month ahead, bin re-worked each month. |
| Unit | Pieces (DEC-11). |
| Reproduction | Matches kelvin/forecast-error-business eebd741: the same 2,419 product-months, 0 bin differences, forecasts within 0.00005 pieces (that CSV's rounding). Median product WAPE: 0.2686 served / 0.2796 MA3 / 0.3458 naive ("same as last month"). |
| Pull | 2026-10-03 07:33 UTC, one transaction, `transaction_read_only = on`, rolled back (`pull_inputs.py`). |

## Part 1 — Correctness

Full list with evidence: `p1_checks.csv`.

| # | Check | Result | Evidence | Numbers |
|---|---|---|---|---|
| 1 | Features and training use only months before the forecast month | **PASS** | `global_model.py:90,123`; `router.py:80`; perturbation test `p1_leakage_perturbation.csv` | Scrambling the forecast month and everything after it changed 0 forecasts and 0 bins. Tested at 2024-06, 2025-03 and 2026-01; MA3, TSB and XGBoost all bins. |
| 1 | Scalers / encoders / product stats fitted on the full history | **PASS** | `global_model.py:84-107` | Scale = that product's own last-6-month mean before the month. No global scaler or encoder. TSB starts from the training-window averages only (`baseline.py:180-181`). |
| 1 | Cohort and XGBoost pool chosen with future data | **ISSUE** | `run_fit_diagnosis.py:113-120` (`ABC_PERIOD = '2026-02'`); `schema.sql:498` (`single` = that month's revenue); `run_baseline_forecast.py:880-881` | Only 81.4% of scored product-months were Tier A the month before. Pool effect: none (Q3: +0.8 percentage points of XGBoost-alone median product WAPE, 95% interval −0.6 to +1.6). Cohort effect: large (median product WAPE 34.8% vs 26.9%, served; see the headline). |
| 2 | Rolling origin (refit, past only) | **PASS** | `global_model.py:123,138-148` | 29 retrainings, each on months strictly before the forecast month. |
| 2 | Bin thresholds 3 / 12 / 24 tuned on the test months | **PASS** | `bins.py:14-15,35` | Conventions set before DEC-26 (eligibility gate; Round-1 cut-off; two yearly cycles). |
| 2 | Model per bin and XGBoost settings chosen on the scored months | **ISSUE** | DEC-26 (`ARCHITECTURE.md:96`) rests on the 2023-10..2026-02 rolling test | The served figure includes this choice; MA3's does not. The served−MA3 gap is the same on the at-the-time cohort (−1.1 points both ways). |
| 3 | Each product-month gets the bin its history gives | **PASS** | `router.py:52-56,86`; independent recount | 0 mismatches in 2,419. Guards fired 0 times. 103 product-months had fewer than 3 sales months and got no model (not scored). |
| 3 | "History length" means months **with sales**, not calendar months | NOTE | `router.py:55`; DEC-26 wording | 19 product-months (5 products) would bin differently on calendar months since the first sale. |
| 3 | Products on sale before the data starts look new | **ISSUE** | `run_baseline_forecast.py:202-204`; `global_model.py:104` | 40 of 107 products start at 2023-01 (the data start). No product can be `long` before 2025-01, and `medium` only exists from 2024-01 (`p1_router_bins_by_month.csv`). The bin tracks how old the data is more than how old the product is. |
| 3 | Product code changes | ISSUE (open, known) | migration 0029 (`supersedes_product_key` added empty) | 12 Unilever products share 6 names (KNORR SINGLES / KNORR SIN codes, new codes from 2026-01). 1 is in the cohort: KNORR SIN ORIG+SINORIG 48(6+1)X11G (64971078). Each code is scored as its own product (`p1_same_name_products.csv`). |
| 3 | Dead products | NOTE | `common.backtest` = `run_followups.py:119` | Months after a product's last row are never scored. This hit 4 product-months (all Unilever, 2023-10..2026-02) where a product was Tier A the month before. |
| 3 | Gaps | NOTE | `run_baseline_forecast.py:204` | A missing month inside a product's span is read as 0 sales: 11 product-months in 6 cohort products. Every one of the 38 months has rows company-wide, so these are not file gaps. |
| 4 | Generated / filled rows excluded | **PASS** | `schema.sql:865-866`; migration 0038:56-57 | See Scope. |
| 4 | Blank (NULL) quantity read as 0 pieces | **ISSUE** | `run_baseline_forecast.py:189` `fillna(0.0)` (same in `run_fit_diagnosis.load_inputs`) | 71 real product-months, 69 of them with a peso amount. 1 in the pool and cohort: SURF POWDER KALAMANSI L 40(6+1)57G (64861486), 2025-12. DEC-31 says "unknown is not zero". |
| 4 | Negative months (returns > sales) | PASS (as documented) | DEC-15; `router.py:55,122`; `baseline.py:182-187`; `global_model.py:90`; `diagnostic_metrics.py:47-51` | 8 in the cohort's history, 7 scored as actuals (1,649 across all real Unilever products). Not a sales month for binning. Raw in MA3, but a served MA3 is floored at 0. TSB treats one as a no-sale month. WAPE uses \|actual\|. |
| 4 | Unit = pieces | PASS (code; source files not re-opened) | DEC-11; `schema.sql:458-463` | — |
| 5 | Long bin = (XGBoost + MA3) ÷ 2 | **PASS** | `router.py:109` | 759 long product-months; the largest gap from (xgb + ma3) / 2 is 0. |
| 5 | Was the 50/50 weight ever tested? | **ISSUE: never** | `router.py:109`; `coverage_map.csv` | See Q2. |
| 6 | WAPE = Σ\|error\| ÷ Σ\|actual\| | **PASS** | `diagnostic_metrics.py:47-51` | Independent recompute differs by at most 1e-16. |
| 6 | Same products and months for every model | **PASS** | `run_followups.py:118-122,139-141` | 2,419 of 2,419 rows scored by served, MA3 and naive alike. |
| 6 | Bias = Σerror ÷ Σ\|actual\|; MASE (mean absolute scaled error: the miss ÷ the miss of "same as last month") | PASS (formula) | `run_followups.py:142`; `diagnostic_metrics.py:63-83` | MASE is defined for only 61 of 107 products (it needs 2+ real months before 2023-10): median 0.760 served vs 0.756 MA3. |
| 6 | Headline = median of per-product WAPEs | NOTE | `run_followups.py:156` | Products are scored on 5 to 29 months, but each counts once. |

## Part 2 — Setup

The question is whether each setting suits monthly count data.

| Setting | Current value | Where | Fit for this data? |
|---|---|---|---|
| Model | One **global** XGBoost across products (not per product). | `global_model.py:1-27` | Right choice: each product has at most 38 months. |
| Objective | `reg:absoluteerror`, which aims at the **median** of the target. | `global_model.py:41-44` | Right for WAPE, which is a sum of absolute errors and is lowest at the median. Poisson / Tweedie / squared error aim at the **mean** and gave no gain (Q1). Count losses do not describe this noise: the median product sells **6,217 pieces a month** (2023-10..2026-02), where pure count (Poisson) noise would be about 1.3% of level against the ~32% observed (`p2_count_scale.csv`). |
| Target transform | Quantity ÷ the product's own last-6-month mean (a level ratio). No log or power transform. | `global_model.py:7-10,90,126` | Scaling is what made XGBoost competitive (unscaled: no gain, 2026-09-21 recon). `experiment/target-transforms` tried 35 + 77 transforms and differencing schemes: **0 real wins** (target_transforms SUMMARY.md:11; differencing_phase2 SUMMARY.md:11). |
| Hyperparameters | Depth 4, learning rate 0.05, subsample 0.8, column sample 0.8, 300 rounds, no early stopping, seed 20260921, 1 thread. | `global_model.py:38-45` | **Fixed, never tuned** (`global_model.py:16-17`; no grid, random or early-stopping search anywhere). |
| Features (14) | Lags 1–6 and 12; 3- and 12-month means; 6-month standard deviation (all ÷ scale); zero months in the last 6; months of history; share of months with a sale; month of year. | `global_model.py:47-51,93-107` | Months of history is cut off at the data start (40 of 107 products). Month of year is a plain number 1–12; it helps (removing it costs +2.8 percentage points, `eebd741:README.md`). No price, promotion, stock, category-total or holiday feature. |
| Training window | Expanding: every product-month with 3+ months since first sale, strictly before the forecast month; at least 100 rows. | `global_model.py:110-128,135` | 2,600 training rows for 2026-02 (Tier A pool). |
| Training pool | Tier A as of the latest ABC month (132 products, `pull_counts.csv`). | `run_baseline_forecast.py:880-881` | In the backtest it carries the look-ahead above. Training on every real product: tie on WAPE; XGBoost-alone over-forecast bias +5.2% → +0.3%, but the long-bin average's stays +6.3% (Q3). |
| TSB (medium bin) | Demand-size weight 0.3, probability weight 0.1, **fixed** (locked 2026-09-21); starts from the training-window averages. | `baseline.py:65-70,161-188` | Tier A has 0 real zero-quantity rows. On **937 of 1,002** medium-bin product-months TSB equals plain exponential smoothing with weight 0.3, so its intermittent-demand part never switches on (`p2_tsb_equals_ses.csv`). Fitted-weight SES (simple exponential smoothing) was tried and tied (`coverage_map.csv`). |
| MA3 | Mean of the last 3 months from the first sale; floored at 0 when served. | `baseline.py:128-134`; `router.py:122` | — |
| Guards | No XGBoost number, above the product's historical maximum, or below 0 → MA3. | `router.py:111-121` | Fired 0 times in 2,419 product-months. |

## Part 3 — Leftover patterns in the 29-month errors

Served and MA3, 107 products, 2023-10..2026-02. Error = forecast − actual, in pieces: + means over-forecast,
− means under-forecast. To compare products of different sizes, each error is divided by that product's
average monthly sales ("scaled error").

| Look | What it shows | Pattern? | File |
|---|---|---|---|
| Calendar month | January: served bias −17.1%, MA3 −24.2%. December: served +13.4%, MA3 +15.5%. July: served +28.8%, MA3 +25.7%. March: served −18.2%, MA3 −16.7%. October: served +10.0%, MA3 +6.5%. | **Yes** | `p3_by_calendar_month.csv` |
| Is it shared and repeatable? | The test month explains **11.4%** (served) / **13.2%** (MA3) of scaled-error variance, against a shuffle-null 95% limit of 1.8%. The 107 products' summed monthly error is **2.1×** what independent product errors would give. The company-total MA3 miss (% of the MA3 forecast) correlates **0.57** with the same month a year earlier (p = 0.004, 23 pairs 2024-04..2026-02, 16 with the same sign); for the 107 products it is 0.45 (p = 0.07, 17 pairs). | **Yes, at company level** | `p3_common_month_shocks.csv`, `p3_portfolio_month_effect.csv` |
| Selling days | Average monthly error vs the number of Mon–Sat days: correlation r = 0.03, p-value 0.87. | No | `p3_common_month_shocks.csv` |
| December / January | Over / under by year: 2023-12 −19%, 2024-01 −22%, 2024-12 **+45%**, 2025-01 −14%, 2025-12 **+36%**, 2026-01 −15% (served bias). | Yes (part of the calendar effect) | `p3_dec_jan.csv` |
| Product size (sales thirds) | Median WAPE, served: low 26.6%, middle 27.0%, high 26.9%. Bias −1.5% / −0.4% / +3.7%. | No | `p3_by_volume_tercile.csv` |
| Bin | Pooled WAPE (served vs MA3): short 30.7% vs 30.7%, medium 25.7% vs 26.5%, long 30.6% vs 31.4%. Median product WAPE, long: 24.8% vs 26.9%. | Small (DEC-26's tie) | `p3_by_bin.csv` |
| Months since first sale | Products launched inside the data and now 24+ months old: pooled WAPE 43.3%, bias **+20.2%** (served, pieces; 27 products, 209 product-months). 51% of that group's net over-forecast is one product, SURF POWDER CHERRY BLOSSOM L 288X65G (69668140), which collapsed. Without the collapse and surge months the bias is +2.7% (181 product-months). | Weak, mostly collapses | `p3_by_months_since_first_sale.csv`, `p3_age24_concentration.csv` |
| Does last month's miss predict this month's? | Pooled lag-1 correlation of scaled errors: served −0.068 (interval −0.119 to −0.024), MA3 −0.080. MA3 on pure noise gives −0.083. Lags 2–3 are less negative than pure noise (MA3 −0.049 / −0.188 against −0.167 / −0.250), pointing to a level that drifts slowly. Ljung-Box (a test for leftover pattern in a run of errors) flags 14 of 89 products (MA3); pure noise would flag about 17. | **No** beyond noise | `p3_autocorrelation*.csv`, `p3_ljungbox_null.csv` |
| Collapses / surges | The three months that start a fall to under half (or a rise to over double) the previous 3-month average. Collapse windows: 143 product-months (5.9%, 67 events, 33 products) carry **12.3%** of absolute error, at ~100% WAPE. Surge windows: 4.3% of rows, 4.7% of error. Everything else: 25.2% pooled WAPE. | **Yes**, concentrated | `p3_level_shifts.csv` |
| Collapse example | DOVE SH KERATIN STRT&SILKY 288X13.5ML (64314335; product key 674), medium bin, measured against its own 2025-06..2025-11 average. It sold −0.3% of that level in 2025-12 (returns exceeded sales) and 4.3% in 2026-01. TSB still forecast 91% and 81% of the level; MA3 came down faster (75% and 51%). SURF POWDER CHERRY BLOSSOM L 288X65G (69668140; product key 613) sold 3.3% and 9.6% of its own level in the same two months and 63% in 2026-02. That looks like a supply break, not demand (UNVERIFIED). | Collapse; TSB slow | `p3_collapse_examples.csv` (ratios only; monthly pieces stay in `local/`) |
| Two-sided yardstick | Forecasting each month as the average of the month before and the month after (it uses the future): median product WAPE **29.5%**, against served 26.3% / MA3 27.2% on the same 2,312 rows. Under a drifting level that would be far better than MA3; under pure noise, slightly worse. | Points to noise | `p3_noise_yardsticks.csv` |
| Noise floor | Fitting each product as "a level that drifts + month noise" (89 products with 13+ months): noise is a median **32%** of the product's level; estimated level drift is 0 for the median product. The best possible one-month forecast for that model gives a median product WAPE of about **23.5%** (method of moments) or **25.2%** (maximum likelihood, a different estimation method), against 25.2% served / 26.8% MA3. Rough: each product has only 13–38 months, and the moment fit over-predicts MA3's error (actual ÷ model = 0.78). | Headroom from a product's own history ≈ 0–1.7 points vs served, 1.6–3.3 vs MA3 (`qc_arithmetic.csv`) | `p3_noise_yardsticks.csv`, `qc_recompute.csv` |

## Part 4 — What the 162 alternatives covered, and what is left

`coverage_map.csv` has one row per candidate family, with result vs MA3 and source. The count reconciles
exactly: 50 original + 35 phase-1 + 77 phase-2 = 162 (`reports/evidence/ch05_candidate_names.csv`).

**Covered:**

- Every simple average (naive, seasonal naive, mean, drift, MA2–MA12, MA with a trained window, median3).
- Methods built for products with many zero months: Croston, SBA (Syntetos-Boylan approximation; weights 0.1
  and 0.3) and TSB; ADIDA and IMAPA (forecasting from months grouped into longer blocks).
- Smoothing: SES, Holt (adds a trend), damped Holt, Holt-Winters (trend and season), auto-ETS (error, trend
  and season form picked automatically), Theta and optimised Theta (smoothing plus a damped trend).
- Fixed and auto ARIMA / SARIMA (autoregressive integrated moving average, without / with a yearly season).
- XGBoost: absolute, squared, unscaled, Tier A and Tier A+B+C pools.
- LightGBM (another gradient-boosted tree library): absolute error, median, Tweedie on the clipped scaled target.
- Random forest, ridge (a penalised straight-line regression) and a small neural net.
- k-nearest analog products (forecast from the 5 most similar older products); category shrinkage; category top-down.
- Six ensembles, including the served 50/50 average.
- 8 target transforms × 4 models, differencing (D1–D3 = forecasting the month-to-month change, once to three times; seasonal =
  the change from the same month last year) and STL (seasonal-trend decomposition).
- Repeated transforms and auto-ARIMA re-chosen monthly.

Outside the 162: the month-feature ablation and the surplus bias fixes A–E. Chronos (a pretrained time-series model) was **not run**
(torch is blocked).

**Never tried before this audit:**

- Poisson objective.
- Any blend weight other than 0.5.
- Any hyperparameter tuning.
- Any feature beyond the 14 (stock, price, promotion, category totals, calendar indices).
- Per-bin global models.
- Sliding training windows.
- Quantile or multi-month forecasts.
- Negative binomial / iETS / fitted-weight Croston, SBA or TSB.

Ranked list: `untried_options_ranked.csv`.

### Quick checks (exploratory, same 29 months unless stated)

Each ran in under 10 minutes; run times are recorded in `quick_checks_results.json` (they vary run to run).

| Check | Result |
|---|---|
| **Q1** XGBoost objective | XGBoost alone, every bin, median product WAPE: absolute (served) 28.3%, Poisson 28.3% (+0.1 points, −0.9 to +1.6), Tweedie 1.5 28.8% (+0.5, −0.6 to +2.2), squared 29.8% (+1.6, −0.4 to +3.1). Long-bin average: all 24.8–25.4%, served best. Tweedie lowers over-forecast bias to +2.1% (served +5.2%). **No gain.** (`q1_xgb_objective.csv`; 7 negative training targets clipped to 0 for Poisson / Tweedie.) |
| **Q2** Blend weight | Best fixed weight on 2023-10..2024-12: **0 (MA3)**, 23.9% vs 25.0% at 0.5. On 2025-01..2026-02 the order flips: XGBoost alone 26.3%, 0.5 27.3%, MA3 29.6%. The weight chosen on the first period **loses** on the second: +2.3 points (+1.0 to +4.0), 19 products better / 88 worse. **0.5 is a reasonable hedge; a fixed weight is not stable.** (`q2_blend_weight.csv`) |
| **Q3** Pool look-ahead | XGBoost alone vs the served pool: Tier A as of the month before, +0.8 points (−0.6 to +1.6); every real product (21,671 training rows at 2026-02), −0.9 (−2.2 to +1.1), 72/35, XGBoost-alone bias +5.2% → **+0.3%** (long-bin average: tie, +1.1 points, −0.7 to +2.5; bias +6.3%). **No inflation from the pool.** (`q3_pool_lookahead.csv`) |
| **Q3** Cohort look-ahead | At-the-time Tier A (337 products, 3,503 product-months; 160 Tier A product-months not scorable): median product WAPE **34.8% served / 35.9% MA3**; pooled 29.6% / 30.2%. Products also in the 107: 28.0% / 28.8%. Products not in the 107 (231): **40.8% / 42.5%, bias +13.5%**. Products scored under 12 months (218): 44.2%, bias +18.0%. **The headline is optimistic; the tie is not affected.** (`q3_cohort_lookahead.csv`) |
| **Q4** Company calendar factor | MA3 × (same month's company-total ratio, averaged over earlier years): 2024-04..2025-02 (1 year back) **worse**, +5.0 points (+2.4 to +7.8); 2025-03..2026-02 (1–2 years back) −1.4 points (−3.7 to +0.9), 71 better / 36 worse, **tie**. **Promising, unproven; the crude form is too noisy with 1 year.** (`q4_calendar_factor*.csv`) |

### Ranked untried options

Payoff is the expected effect on product WAPE.

| Rank | Option | Expected payoff | Why |
|---|---|---|---|
| 1 | Calendar effect shared across products (pooled month index, shrunk; for MA3 / TSB bins) | Small to moderate (up to about 1.6–1.8 points), grows with years | The only large leftover pattern; repeatable at company level; Q4's crude version ties with 2 years. |
| 2 | Stock-out / supply signal for collapse months | Small on median WAPE, larger in pesos | 5.9% of rows carry 12.3% of error; needs purchase-order (PO) quantity / correctly dated counts. |
| 3 | Train XGBoost on every real product | None on WAPE; XGBoost-alone bias +5.2% → +0.3% (not yet in the long-bin average: +6.3%) | Q3. Matters given the stated preference for under- over over-forecasting. |
| 4 | Time-adaptive blend weight | Small | Q2: the best fixed weight flips between periods. |
| 5 | True launch dates from SSM | Small; fixes bin labels | 40 of 107 products look new in 2023. |
| 6 | Hyperparameter tuning (rolling validation) | Small | The single-product noise floor (23½–25%) leaves 0–1.7 points vs served; overfitting risk with 29 months. |
| 7 | Poisson / Tweedie | None | Q1. |
| 8 | Count / intermittent variants | None for Tier A | TSB = SES(0.3) on 93.5% of medium-bin months. |
| 9–12 | Quantile, multi-month, Chronos, selling days | None on one-month WAPE / unknown / none | See CSV. |

## Quality check (2026-10-03)

Read-only; only report files were changed. Scripts: `qc_recompute.py`, `qc_check.py`, `qc_hygiene.py`. No FAIL.

| Check | Result | What was checked | What was fixed |
|---|---|---|---|
| Every number traced to a file | **FIXED → PASS** | All 821 numbers in the report body (every section except this one): 388 match a value in the file cited in their own bullet or table row (allowing for rounding, % and ₱ millions); 339 are identifiers (dates, product codes, file:line references, list numbers); 94 are design constants or counts with a named source. **0 untraced** (`qc_numbers.csv`, `qc_summary.json`). Whole numbers under 100 can match a cited file by coincidence, so all 84 of them were also checked by hand (`qc_small_integer_review.csv`). | File citations added to every plain-language bullet. Trace files added for numbers that came from one-off checks (`p2_count_scale.csv`, `p2_tsb_equals_ses.csv`, `p3_age24_concentration.csv`, `p3_collapse_examples.csv`, `pull_counts.csv`). Quick-check run times dropped: they change from run to run, and they had been "traced" to unrelated cells. Headroom against MA3 corrected to 1.6–3.3 points. The expected payoff of the calendar experiment now shows its derivation. |
| Arithmetic | **PASS** | 31 of 31 sums, shares, differences and derived ranges recompute within rounding (`qc_arithmetic.csv`). | — |
| Independent recompute | **PASS** (5 of 5) | Re-coded from the documented design without importing any production forecasting code (`qc_recompute.py`). 26.9% / 28.0% (0.2686 / 0.2796), 34.8% / 35.9% (0.3479 / 0.3594) and the 23.5% noise floor (0.2352) all reproduce exactly. | A different estimation method (maximum likelihood) puts the floor at 25.2%, the served model's own level. The report now gives a range (23½–25%) and a smaller headroom against the served model (0–1.7 points). The months-of-history range behind the floor was misquoted and is corrected (13–38). |
| Data rules | **PASS** | Generated rows are excluded by the `is_demo` flag: 12,243 `is_demo = true` rows (`fill_source = synthetic_v2`) never enter, and 0 real rows carry a `fill_source` tag (`pull_counts.csv`). | — |
| Wording | **FIXED** | Period, unit and basis on every number; each term spelled out where first used; product name before product code (6 of 6 mentions, `qc_summary.json`); survivorship explained in plain words in the headline. | Period, unit and basis added to the plain-language numbers. Spelled out: WAPE, Tier A, XGBoost, TSB, bin, MASE, Ljung-Box, Poisson / Tweedie and the Part 4 model names. `p1_same_name_products.csv` now lists the product name first. |
| Repo hygiene: no single product's sales or prices in any commit | **FIXED → PASS** | Scripted scan of every commit on `kelvin/model-audit` and `kelvin/blank-qty-fix` (`qc_hygiene.csv`): 0 files from `inputs/` or `local/`; 0 per-product CSV columns with sales, quantity or price; 0 README lines pairing a product code with a piece count or peso price. | This branch's first commit (61ff127) had product key 674's monthly pieces and forecasts in one README row. The row now gives ratios to the product's own level (`p3_collapse_examples.csv`). The unpushed branch was rewritten so no commit on it carries those numbers; 61ff127 is on no branch (local reflog only, never pushed). |
| Dry merge into `group7/kelvin-etl` | **PASS** | Both branches merge with 0 conflicts; both merges were aborted, nothing committed (`qc_hygiene.csv`). | — |

## Files

Committed (all ratios, counts or cohort totals; no single product's sales or prices):

| File | What |
|---|---|
| `pull_inputs.py` | The one read-only pull (writes `inputs/`). |
| `pull_counts.csv` | Row counts behind the Scope table (from `inputs/`; counts only). |
| `common.py` | Loaders; the served backtest through production `route()`; `FastForecaster` (reproduces production XGBoost exactly, max difference 0.0, checked in both scripts). |
| `run_audit.py` | Parts 1–3 (a few minutes). Writes `p1_*.csv`, `p2_*.csv`, `p3_*.csv`, `audit_results.json`. |
| `quick_checks.py` | Q1–Q4 (a few minutes). Writes `q*.csv`, `quick_checks_results.json`, and the at-the-time cohort backtest to `local/`. |
| `headline_pesos.py` | The restated headline, both cohorts, pieces and pesos (seconds). Writes `headline_two_cohorts.csv` and the reproduction check `headline_two_cohorts_check.json`. |
| `qc_recompute.py` | Quality check: independent recompute of the headline numbers. Writes `qc_recompute.csv` / `.json`. |
| `qc_check.py` | Quality check: every README number traced, arithmetic, wording counts. Writes `qc_numbers.csv`, `qc_arithmetic.csv`, `qc_small_integer_review.csv`, `qc_summary.json`, `pull_counts.csv`. |
| `qc_hygiene.py` | Quality check: scan of every commit on both branches, dry merges into `group7/kelvin-etl` (aborted). Writes `qc_hygiene.csv`. |
| `cohort_107.csv` | Product keys of the scored cohort (from eebd741). |
| `coverage_map.csv`, `untried_options_ranked.csv` | Part 4. |
| `p3_per_product.csv` | Per product: WAPE, bias, error autocorrelation and noise estimates (ratios). No monthly quantities. |

**Not committed** (`.gitignore`: client data, Yuan's 2026-10-03 rule): `inputs/` (raw pull) and `local/`
(per-product monthly backtests and logs).

Rerun, from the worktree root (the worktree has no `.env`; the pull reads the main checkout's):

```
SUPABASE_DIRECT_URL= ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/pull_inputs.py
../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/run_audit.py
../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/quick_checks.py
../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/headline_pesos.py
../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/qc_recompute.py
../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/qc_check.py
../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/qc_hygiene.py
```

`cohort_107.csv` is rebuilt from `git show eebd741:...` if it is missing (needs the
`dsd-forecast-error-business` worktree).

## Words used

- **WAPE** (weighted absolute percentage error): total absolute miss ÷ total sales.
- **MASE** (mean absolute scaled error): the miss ÷ the miss of "same as last month" on earlier months;
  under 1 beats it.
- **Bias**: total (forecast − actual) ÷ total sales; + means over-forecast.
- **MA3**: average of the last 3 months.
- **TSB** (Teunter-Syntetos-Babai): smoothing built for products with many zero months.
- **SES** (simple exponential smoothing): a weighted average that favours recent months.
- **XGBoost**: a gradient-boosted decision-tree model, here one model across all products.
- **Look-ahead / leakage**: using information that would not exist at forecast time.
- **Rolling origin**: re-forecast each month using only the months before it.
- **Shuffle null**: the same statistic after randomly reordering months, to show what chance gives.
- **Ljung-Box**: a test for leftover pattern in a sequence of errors.
- **ABC classification**: ranking products by revenue into tiers A, B, C.
- **Tier A**: products in the top 80% of revenue; ABC `single` ranks on one month's revenue.
- **Median product WAPE / pooled WAPE / total-level WAPE**: the middle product's own WAPE; all product-months
  together; all products added up within each month first, so misses can cancel.
- **Percentage point**: the difference between two percentages (27% → 25% is 2 points).
- **95% interval**: the range the true value falls in 95 times out of 100 (bootstrap over products); one that
  spans 0 means "no difference shown".
- **p-value**: the chance of a result at least this strong if there were no real effect.
- **Bin**: the router's history-length group (short 3–11, medium 12–23, long 24+ months with sales).
- **Cohort**: the set of products scored. **Survivorship**: judging by products picked for how they ended
  up, which drops the ones that faded.
- **Collapse / surge window**: the three months that start a fall to under half (rise to over double) the
  previous 3-month average.
