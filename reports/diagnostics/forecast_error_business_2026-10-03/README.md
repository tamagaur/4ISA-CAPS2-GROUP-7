# Forecast error in pieces and pesos: Unilever Tier A as of 2026-02

Read-only diagnostic, 2026-10-03, branch `kelvin/forecast-error-business`. Scope: the 132 Unilever products in
Tier A as of 2026-02 under the ABC classification (a Pareto ranking by revenue; method `single`). Products are
identified by SKU (stock-keeping unit) code. Del Monte has no product-level sales, so it is not forecast.

- **Periods:** the headline uses 29 test months, 2023-10 to 2026-02 (§8). §1–§7 detail the latest six,
  2025-09 to 2026-02.
- **Peso labels:** every peso figure is marked either *at selling price, VAT-inclusive (value-added tax)* or
  *at cost (stock count)*.
- **Client data:** per-product sales and prices are not in this folder's committed files (§12).

## Is 30% good or bad, and what does it cost SSM per month?

Over 29 test months, October 2023 to February 2026, the typical Tier A product's forecast missed its actual
sales by 26.9%. That is the median WAPE (weighted absolute percentage error) across 107 products, with the
forecast router as it would have run each month. It is a sizeable miss for one product, but better than the
simplest yardstick: repeating last month's sales missed by 34.6% on the same products and months, and the
forecast did better than that on 91 of the 107 products.

Added together, the misses partly cancel: all 107 products combined were off by 10.7% of sales in pesos at
selling price, VAT-inclusive (value-added tax). The misses are also balanced rather than one-sided. 51.1% of the
peso miss was forecast above sales and 48.9% below, and 51.6% of product-months were over-forecast.

In money, the product-level misses came to 30.0% of the sales value of the products forecast over the 29
months, in pesos at selling price, VAT-inclusive (value-added tax). For a monthly figure, use the latest six
months (2025-09 to 2026-02), where all 107 products are scored in every month (§2):

- **Total miss:** ₱6.82 million per month at selling price, VAT-inclusive (value-added tax), against
  ₱20.57 million per month of sales at selling price, VAT-inclusive (value-added tax).
- **Forecast above sales (surplus):** ₱3.79 million per month at selling price, VAT-inclusive (value-added tax).
  At cost (stock count) that is ₱3.31 million per month for the 100 products that have a cost basis. Surplus
  ties up money at cost.
- **Forecast below sales (shortage):** ₱3.03 million per month at selling price, VAT-inclusive (value-added tax).
  This becomes lost sales only where safety stock does not cover the gap.

**Read those six months as a recent snapshot, not the norm.** They leaned toward over-forecasting: 55.6% of the
peso miss (at selling price, VAT-inclusive (value-added tax)) was surplus, against 51.1% over 29 months. Their
combined miss was also smaller, 8.3% instead of 10.7%.

**None of these pesos is money lost.** What SSM actually loses, meaning storage cost on surplus and margin on
lost sales, can't be computed yet:
- SSM hasn't supplied procurement or storage costs.
- The stock count's cost per piece is a median 0.985 of the sales file's gross sales value per piece, so it is
  probably not SSM's net purchase cost.

**Where the miss sits.** It is concentrated: in the six months, 10 products account for 40% of it (§2). Runs of
three or more over-forecast months in a row are about as common as chance alone would produce, so mostly they
don't mean the forecast is stuck. The exceptions are listed in §11.

---

## 1. Where the numbers come from

| Question | Answer | Source |
|---|---|---|
| Does the database store forecast vs actual per product per month? | **No.** `forecast_result` has one row per product for the next month only. Forecast date 2026-03-01 is the only date in the table (132 rows), and each row carries summary scores such as MAPE (mean absolute percentage error) and MASE (mean absolute scaled error). | `inputs/forecast_result_dates.csv`, `analytics/db/schema.sql:575-590` |
| Where is it stored? | Only in a file: the REAL run inside `reports/simulation/synthetic_2026-10/series.csv` (654 product-months). | that file |
| Regenerated? | **Yes.** Rebuilt locally from one read-only pull with the served router, through the shared harness `reports/diagnostics/fit_diagnosis_2026-10/run_fit_diagnosis.py`. It reproduces `forecast_result` on 132 of 132 rows (status, method, forecast value, stored MASE) and `series.csv` on 654 of 654 product-months. The largest forecast difference is 0.0000005 pieces. The script stops if either check fails. | `results.json` → `reproduction`, `run_log.txt` |

**Which products are scored**

| Group | Products | Test months | Used in |
|---|---|---|---|
| Scored on the common window | 107 | 2025-09 to 2026-02 (6) | every section |
| Scored on one month only | 12 | 2026-02 only. These launched too recently for the common window, so they use their own last-20% split. | per-product files only. Left out of totals, runs, category and correlation. |
| Not scored | 13 | none | Fewer than 3 months with sales gives status `insufficient_data`, and no backtest exists for them. |

**Generated data excluded**

| Data | Filter | What it removed |
|---|---|---|
| Demand | `Unilever_SKU_Demand_Fact_Real`, the view that keeps `is_demo = false` rows only (`schema.sql:865-866`) | The base table has 12,243 `is_demo = true` rows (2021-01 to 2026-08) and 24,906 real rows (2023-01 to 2026-02). Gap fills can't slip through: `fill_source` may only be set on `is_demo = true` rows (CHECK constraint, `0038_data_fills.sql:56-57`). All 3,087 pulled product-months are dated 2023-01 to 2026-02. One of them has an empty quantity: SURF POWDER KALAMANSI L 40(6+1)57G (64861486), 2025-12. It is counted as 0 pieces sold, the pipeline's rule (`run_fit_diagnosis.py:127`). |
| Stock count | `inventory_fact`, `is_demo = false AND fill_source IS NULL` | The snapshot taken 2026-04-06 (period 2026-03) is real: 785 rows. The six snapshots from 2026-05-02 onward are `synthetic_v2_gap` and were not read (`inputs/stock_count_snapshots.csv`). |

**Price and cost basis**

| | Definition | Coverage |
|---|---|---|
| Selling price per piece | Sum of `net_amount` ÷ sum of pieces over the product's own test months. `net_amount` is the La Union Sales-per-SKU file's "Total Sales Amt Inc. Tax" (`config/column_maps/unilever_sku.yaml`, `0010_gsv_and_guards.sql`). So it is **at selling price, VAT-inclusive (value-added tax)**, after any discount. The sales register can't be used here: `sales_fact` has 0 Unilever rows and no product column, and `product_dimension.unit_price` is empty for all 132 products. | All 119 scored products. Across the 107: ₱4.98 to ₱1,125.78 per piece, median ₱31.95, at selling price, VAT-inclusive (value-added tax). |
| Cost per piece | From the stock count taken 2026-04-06: Stock Value ÷ (cases × pack size + loose pieces). A product not in the count gets "no cost basis"; nothing is guessed. | 120 of 132 products. The 12 not in the count include 7 of the 107. |
| What that "cost" is | Stock Value = pieces × "Last Purchase Price (GSV/CS)" exactly, on 120 of 120 products (ratio 0.9999 to 1.0000). GSV/CS is GSV (gross sales value) per case. Per piece, the cost is a median 0.902 of the selling price VAT-inclusive (value-added tax), 111 products, and a median 0.985 of the sales file's GSV per piece, 110 products. So it is close to SSM's own gross selling price before VAT. Whether it equals SSM's actual purchase cost is **UNVERIFIED**; procurement cost is one of the four inputs SSM still owes the LP (the linear programming order optimiser). | `results.json` → `price_cost_checks`. The per-product prices and costs stay in `local/`. |

## 2. Error per product per month (Part 1)

**Definitions.** *Error* = forecast − actual, in pieces. A positive error means the forecast was above sales
(surplus side); a negative error means it was below (shortage side). *WAPE* = sum of |error| ÷ sum of |actual| over
the product's test months.

| Per product, per month, 107 products, 2025-09 to 2026-02 | Median product |
|---|---|
| Actual sales | 5,928.5 pieces |
| Average miss | 1,547.4 pieces |
| Average miss, ₱ at selling price, VAT-inclusive (value-added tax) | ₱30,614 |
| WAPE, served forecast | 29.3% |
| WAPE, MA3 (average of the last 3 months), same months | 32.2% |
| WAPE, naive (last month's sales), same months | 39.6% |

Against MA3, 67 products came out better, 22 worse and 18 the same (those 18 are served MA3). **This is not a
claim that the served models beat MA3.** It is six months only, and DEC-26 (the decision register in
`ARCHITECTURE.md`) records that the trained models tie with MA3 within the measured margin of error.

**By history-length bin** (median WAPE, same months). The bin is set by how many months a product has had
sales, and it decides the served model:
- **Long** (24+ sales months, 72 products): XGBoost+MA3, the average of MA3 and XGBoost (gradient-boosted
  decision trees trained across all products). WAPE 24.5%, against MA3 26.8% and naive 38.0%.
- **Medium** (12-23, 17 products): TSB (Teunter–Syntetos–Babai smoothing). WAPE 49.4%, against 46.5% and 59.0%.
- **Short** (3-11, 18 products): MA3. WAPE 42.4%, against 42.4% and 45.8%.

**Sanity check, "a ~373-piece forecast should miss by ~112 pieces":** CREAM SILK HC ULTREBORN STRT 24X180ML
(68565204) has an average forecast of 377.2 pieces per month and an average miss of 115.0 pieces per month,
2025-09 to 2026-02 (WAPE 29.9%). This holds by construction: average miss = WAPE × average sales.

**Largest peso misses (at selling price, VAT-inclusive (value-added tax)), 2025-09 to 2026-02.** These 10
products are 40% of the total; the top 20 are 57.9%.

| Product | SKU | Served model | Avg miss, pieces/month | WAPE | Avg miss, ₱/month at selling price, VAT-inclusive (value-added tax) | Bias* |
|---|---|---|---:|---:|---:|---:|
| KNORR SINIGANG SAM ORIG 24X12X11G | 67749043 | XGBoost+MA3 | 67,579 | 38% | ₱460,590 | −3.1% |
| KNORR BN CUBES CHICKEN SINGLES 48X12X10G | 68438409 | XGBoost+MA3 | 61,221 | 48% | ₱358,158 | +11.8% |
| SURF POWDER CHERRY BLOSSM L 40(6+1)65G | 69767334 | XGBoost+MA3 | 8,136 | 27% | ₱302,300 | −8.8% |
| LADY'S CHOICE REAL MAYO DOY 12X470ML | 69695556 | XGBoost+MA3 | 1,547 | 57% | ₱283,945 | +3.6% |
| KNORR BN CUBES PORK SINGLES 48X12X10G | 68438413 | XGBoost+MA3 | 47,035 | 51% | ₱274,667 | +33.6% |
| BESTFOODS RGLR MYNS MAYOMAGICDOY24X220ML | 65004662 | XGBoost+MA3 | 4,925 | 56% | ₱253,155 | −11.0% |
| LADY'S CHOICE RAL MAYO DOY 24X220ML | 69695560 | XGBoost+MA3 | 2,456 | 29% | ₱214,800 | +6.9% |
| SURF POWDER ROSE FRSH L 40(6+1)65G | 69767335 | XGBoost+MA3 | 5,458 | 24% | ₱202,122 | −11.8% |
| SURF POWDER ROSE FRESH L 288X65G | 69668148 | XGBoost+MA3 | 32,259 | 38% | ₱199,244 | −8.9% |
| SURF POWDER CHERRY BLOSSOM L 288X65G | 69668140 | XGBoost+MA3 | 29,367 | 79% | ₱181,975 | +79.1% |

\*Bias = sum of error ÷ sum of |actual|. Plus means over-forecast.

**Products near 100% error, 2025-09 to 2026-02** (the cluster at the top of the chart in §5):

| Product | SKU | Served model | WAPE | Bias |
|---|---|---|---:|---:|
| DOVE SH KERATIN STRT&SILKY 288X13.5ML | 64314335 | TSB | 103% | +102.8% |
| SURF PWDR PURPLE BLOOMS L 40(6+1)65G | 64861488 | MA3 | 103% | +45.5% |
| SURF POWDER KALAMANSI L 40(6+1)57G | 64861486 | MA3 | 102% | +4.5% |
| SURF POWDER TAWAS L 40(6+1)57G | 64861490 | MA3 | 100% | −7.1% |

SURF POWDER KALAMANSI L 40(6+1)57G (64861486) has an empty quantity in 2025-12 (§1). It is counted as 0 pieces,
as the pipeline does.

**Monthly totals, 107 products** (`monthly_totals.csv`):

| Month | Sum of misses, pieces | Actual sales, pieces | Sum of misses, ₱ at selling price, VAT-inclusive (value-added tax) | Shortage side, ₱ at selling price, VAT-inclusive (value-added tax) | Surplus side, ₱ at selling price, VAT-inclusive (value-added tax) | Surplus side, ₱ at cost (stock count), 100 products |
|---|---:|---:|---:|---:|---:|---:|
| 2025-09 | 542,743 | 1,809,987 | 5,657,905 | 2,666,777 | 2,991,128 | 2,478,403 |
| 2025-10 | 720,871 | 1,850,600 | 6,720,243 | 3,861,756 | 2,858,487 | 2,508,554 |
| 2025-11 | 464,019 | 1,753,742 | 5,586,693 | 2,315,509 | 3,271,183 | 2,903,817 |
| 2025-12 | 616,688 | 1,234,640 | 7,521,102 | 1,623,173 | 5,897,929 | 5,162,359 |
| 2026-01 | 1,007,637 | 2,149,329 | 9,236,618 | 5,524,695 | 3,711,923 | 3,358,469 |
| 2026-02 | 461,183 | 1,523,253 | 6,196,669 | 2,189,515 | 4,007,154 | 3,450,305 |
| **Average per month** | **635,524** | **1,720,259** | **6,819,872** | **3,030,238** | **3,789,634** | **3,310,318** |

Surplus on the 7 products with no cost basis averages ₱137,555 per month at selling price, VAT-inclusive
(value-added tax). It is left out of the cost column rather than estimated.

## 3. Direction and persistence (Part 2)

107 products, 2025-09 to 2026-02. Six months is the longest possible run.

| Measure | Value |
|---|---|
| Product-months over / under / exact | 361 / 281 / 0, of 642 |
| Median product bias | +4.4% (slightly above sales) |
| Products net over / net under | 70 / 37 |
| Median share of months over-forecast | 50% |
| **Products with 3+ over-forecast months in a row (surplus risk)** | **44** |
| …of which still in that run at 2026-02 | 12 |
| Longest over-forecast run (months: products) | 1: 22, 2: 41, 3: 21, 4: 18, 5: 4, 6: 1 |
| Longest under-forecast run (months: products) | 0: 1, 1: 45, 2: 42, 3: 16, 4: 3 |
| Direction of the run in progress at 2026-02 | over 66, under 41 |

**Over-forecast 3+ months in a row and still running at 2026-02:**

| Product | SKU | Served model | Current run, months | % months over | Bias | Avg surplus, ₱/month at cost (stock count) |
|---|---|---|---:|---:|---:|---:|
| LADY'S CHOICE REAL MAYO DOY 12X470ML | 69695556 | XGBoost+MA3 | 4 | 67% | +3.6% | 136,052 |
| KNORR BN CUBES BEEF SINGLES 48X12X10G | 68438418 | XGBoost+MA3 | 3 | 83% | +21.8% | 98,289 |
| DOVE SH KERATIN STRT&SILKY 288X13.5ML | 64314335 | TSB | 6 | 100% | +102.8% | 94,884 |
| LADY'S CHOICE REAL MAYO 72X80ML | 69695555 | XGBoost+MA3 | 4 | 67% | +15.2% | 73,605 |
| KNORR SINIGANG ISDA 24X12X11G | 67749046 | XGBoost+MA3 | 4 | 67% | +9.1% | 27,044 |
| LADY'S CHOICE SS CHICKEN 72X80ML | 68764000 | TSB | 3 | 67% | +9.2% | 15,542 |
| LADY'S CHOICE SS CHICKEN 72X27ML | 68763997 | TSB | 3 | 83% | +23.0% | 11,488 |
| SURF BAR CHERRY BLOSSOM SXFL 96X120G | 69725979 | XGBoost+MA3 | 3 | 67% | +18.2% | 11,448 |
| AXE DEO RO RLN DARKTEMP 24X40ML | 68736096 | XGBoost+MA3 | 4 | 83% | +10.5% | 10,280 |
| REXONA MEN RO QUANTUM 72H 24X45ML | 69642633 | XGBoost+MA3 | 3 | 67% | +9.0% | 5,305 |
| BESTFOODS SNDWCH SPRDSLDMATEDOY24X220ML | 65004685 | XGBoost+MA3 | 3 | 67% | +6.9% | 4,904 |
| LADY'S CHOICE REAL MAYO DOY 24X130ML | 64961947 | MA3 | 3 | 50% | −15.2% | 3,099 |

All 44 products are flagged in `per_product_summary.csv` (`surplus_risk_3plus_over`, `currently_over_3plus`).

## 4. Accuracy at category and total level (Part 3)

Same 107 products and same six months, 2025-09 to 2026-02. Each level's forecast is the sum of its products'
forecasts. The
pieces column adds different pack sizes together (sachets plus bottles), so the peso column is the fairer
measure above product level.

| Level | Products | Combined forecast error, pieces | Combined forecast error, ₱ at selling price, VAT-inclusive (value-added tax) | Product-level median WAPE |
|---|---:|---:|---:|---:|
| CONDIMENTS | 18 | 18.1% | 26.0% | 28.9% |
| COOKING AIDS | 21 | 13.0% | 10.5% | 30.0% |
| DEODORANTS & FRAGRANCES | 10 | 20.7% | 19.7% | 21.8% |
| FABRIC CLEANING | 25 | 20.9% | 17.0% | 26.9% |
| FABRIC ENHANCERS | 4 | 30.5% | 30.5% | 35.1% |
| HAIR CARE | 25 | 32.7% | 18.7% | 38.7% |
| ORAL CARE | 1 | 29.5% | 29.5% | 29.5% |
| SKIN CLEANSING | 3 | 29.2% | 29.0% | 32.2% |
| **Total, all categories** | **107** | **14.9%** | **8.3%** | **29.3%** |

What this means for SSM: the total stock and cash needed each month is forecast fairly well (8.3% in pesos at
selling price, VAT-inclusive (value-added tax)). The *mix* across products is not (29.3% median WAPE), and the
mix is what leaves surplus on one product next to a shortage on another.

## 5. Demand swing vs error (Part 4)

*CV (coefficient of variation)* = standard deviation ÷ mean of monthly pieces sold, from the first sale. It uses
the project's own `analytics/segmentation/traits.py:125`. 107 products; WAPE is over the test months 2025-09 to
2026-02.

| CV measured over | Pearson r | r² | Spearman ρ |
|---|---:|---:|---:|
| First sale to 2026-02, including the test months | 0.61 (p < 0.001) | 0.38 | 0.64 (p < 0.001) |
| First sale to 2025-08, before the test months (known in advance) | 0.13 (p = 0.19) | 0.02 | 0.38 (p < 0.001) |

| Swing third (CV, first sale to 2026-02) | Products | CV range | Median WAPE |
|---|---:|---|---:|
| Low swing | 36 | 0.16–0.31 | 22.3% |
| Middle | 35 | 0.32–0.45 | 29.5% |
| High swing | 36 | 0.45–0.87 | 49.2% |

![Demand swing vs forecast error](cv_vs_wape.svg)

**Does high swing explain high error? Partly, and mostly after the fact.** The high-swing third misses about
twice as much as the low-swing third (49.2% vs 22.3%). But swing explains 38% of the differences in error only
when it is measured over the same months as the error. Measured beforehand, it explains 2% on a straight-line
fit. The ranking relationship survives (ρ = 0.38), but it is weak. The big misses come from shocks inside the
test window, which push up the CV and the error at the same time. One example is DOVE SH KERATIN STRT&SILKY
288X13.5ML (64314335), whose sales went from a normal month in 2025-11 to net returns, below zero, in 2025-12.
So swing is a fair explanation after the fact, but a weak early warning.

## 6. Seasonality (Part 5)

**Does the XGBoost half use calendar month? Yes.** `analytics/forecasting/global_model.py:47-51` lists
`month_of_year` among the 14 features, and `:106` sets it to `float(target_month.month)`. The model trained for
the 2026-03 forecast used 2,719 training rows. In it, `month_of_year` has the largest share of total gain
(13.9%, rank 1 of 14) and ranks 4th by number of splits (8.7%). A high gain shows the model leans on the
feature; it does not prove real seasonality. With only three Decembers in the data, the trees may also be
fitting one-off months. Total actual sales of the 107 products in 2025-12 were 1,234,640 pieces, against
1,523,253 to 2,149,329 pieces in the other test months. §9 runs the with-and-without comparison: removing the
feature makes the forecast worse.

**The two tests behind the two claims:**

| | Dashboard "Strong seasonality" | "About 5% seasonal" |
|---|---|---|
| Test | STL (Seasonal-Trend decomposition using Loess) seasonal strength = max(0, 1 − Var(remainder) ÷ Var(seasonal + remainder)) | Lag-12 autocorrelation (each month vs the same month a year earlier): \|ACF(12)\| > 1.96 ÷ √n |
| Threshold | ≥ 0.6 Strong, ≥ 0.3 Moderate, otherwise Weak | 95% bound |
| Minimum history | 36 months from first sale | 24 months |
| Code / record | `analytics/forecasting/decomposition.py`, `frontend/src/components/SkuDemandPatternPanel.jsx:80-83`, `backend/routers/decomposition.py` | `reports/SEASONALITY_AND_BASELINES.md:28, :38`, DEC-23 |
| Today's 132 products, real data to 2026-02 | 16 Strong, 17 Moderate, 7 Weak; 92 have too little history | **3 of 72 significant (4.2%)** |
| Share of pure random noise that reads "seasonal" (500 simulations each, seed 20261003) | 26.0% at 36 months, 22.2% at 37, 15.6% at 38 | 1.6%, 1.6%, 2.4% |

The "about 5%" finding still holds on today's cohort, at 4.2%. The dashboard test calls 15.6% to 26.0% of
pure-noise series "Strong" at these lengths. With three yearly cycles, STL folds one-off spikes into the
seasonal shape; `decomposition.py` notes this in its own docstring.

**Disagreements: 13 products the dashboard labels Strong where the lag-12 test is not significant.** There are
none the other way. The *shuffle* columns re-run the dashboard test on 200 random re-orderings of the product's
own months. A low p means the real order looks more seasonal than shuffled data. The shuffle test assumes the
months are independent, which overstates significance for products whose sales drift, so read it as generous.

| Product | SKU | STL strength | Peak / low month | ACF(12) vs bound 0.318 | Shuffled orders reading Strong | Shuffle p | Verdict |
|---|---|---:|---|---:|---:|---:|---|
| BESTFOODS RGLR MYNS MAYOMAGICDOY24X220ML | 65004662 | 0.971 | Dec / Feb | 0.463 | 24.5% | 0.005 | agree: seasonal |
| CREAM SILK HC ULTREBORN HFALL 24X180ML | 68565205 | 0.787 | Jan / Oct | 0.344 | 21.0% | 0.015 | agree: seasonal |
| AXE DEO AP RLN DARKTEMP 24X25ML | 65003211 | 0.726 | Jun / Feb | 0.326 | 18.0% | 0.035 | agree: seasonal |
| REXONA DLN PASSION 360X3ML | 67633590 | 0.777 | Jan / Feb | 0.154 | 18.5% | 0.020 | **disagree** |
| REXONA DLN SHOWER CLEAN 360X3ML | 67633600 | 0.774 | May / Apr | 0.204 | 13.5% | 0.015 | **disagree** |
| DOVE BS BAR REGLR FBX 48X135G | 67311414 | 0.768 | Jun / Apr | 0.209 | 18.5% | 0.025 | **disagree** |
| SURF POWDER TAWAS S 288X57G | 68178533 | 0.762 | Jan / Mar | 0.112 | 15.5% | 0.015 | **disagree** |
| KNORR SINIGANG NA GABI 24X12X11G | 67749045 | 0.718 | Oct / May | 0.222 | 18.5% | 0.065 | **disagree** |
| REXONA MEN RO ICE COOL IN 24X25ML | 67404149 | 0.680 | Jan / Dec | 0.187 | 17.5% | 0.040 | **disagree** |
| BESTFOODS RGLR MYNS MAYO MAGIC 72X80ML | 65004477 | 0.677 | Sep / Jan | 0.315 | 23.5% | 0.104 | **disagree** |
| KNORR SINIGANG ISDA 24X12X11G | 67749046 | 0.652 | Oct / Dec | 0.194 | 16.5% | 0.114 | **disagree** |
| KNORR BN CUBES BEEF SAVERS 36X120G | 68438405 | 0.626 | Aug / Dec | 0.024 | 16.0% | 0.124 | **disagree** |
| CREAM SILK HC ULTREBORN STRT 24X180ML | 68565204 | 0.615 | Jan / May | 0.138 | 20.5% | 0.184 | **disagree** |
| KNORR SOUP CHICKEN&CORN 60X60G | 67975949 | 0.612 | Jun / Nov | 0.275 | 24.0% | 0.229 | **disagree** |
| DOVE BAR PINK 48X90G | 68864121 | 0.610 | Jun / Dec | 0.166 | 12.0% | 0.119 | **disagree** |
| KNORR LIQUID SEASONING ORIGINAL 24X250ML | 68394708 | 0.604 | Jan / May | 0.082 | 22.0% | 0.224 | **disagree** |

All 16 products here have 38 months from first sale.

**Reconciliation:**
- Three products are seasonal on both tests: BESTFOODS RGLR MYNS MAYOMAGICDOY24X220ML (65004662), which peaks
  in December; CREAM SILK HC ULTREBORN HFALL 24X180ML (68565205); and AXE DEO AP RLN DARKTEMP 24X25ML (65003211).
- Eight of the 16 "Strong" labels can't be told apart from a random re-ordering of the same months
  (shuffle p ≥ 0.05).
- The other five pass the generous shuffle test but not the lag-12 test.
- In preview mode (`X-Data-Mode: preview`), the dashboard also feeds the 2021-22 placeholder months into
  this fit (`backend/routers/decomposition.py` docstring). A label seen in preview mode can therefore come
  from generated data. Every number here is real mode, the default (`backend/data_mode.py`, `get_data_mode`).

## 7. Collapse flag (Part 6)

**Proposed rule (a proposal, not adopted).** Flag a product when the average of its last 3 months is below 50%
of the average of its last 12 months. Months count from the first sale, a month with no row counts as zero,
and the rule needs at least 12 months since the first sale. The 0.5 threshold is Yuan's example
(2026-10-03). 0.7 is the lower edge of the recent-level band already on record (`reports/diagnostics/README.md`,
"Verdict thresholds"). The flag marks a product for review; it does not change any forecast.

| Threshold (last 3 ÷ last 12) | Flagged as of 2026-02 | Assessable |
|---|---:|---:|
| < 0.4 | 2 | 92 |
| **< 0.5 (proposed)** | **4** | 92 |
| < 0.6 | 7 | 92 |
| < 0.7 | 11 | 92 |

40 products can't be assessed (fewer than 12 months since first sale).

**Flagged now, plus the next ones up to 0.6** (`collapse_flag.csv`). Ratios use months up to 2026-02; the
forecasts are for 2026-03, in pieces.

| Product | SKU | Served model | Last 3 ÷ last 12 months | Served forecast 2026-03, pieces | Served ÷ MA3 |
|---|---|---|---:|---:|---:|
| SURF POWDER CHERRY BLOSSOM L 288X65G | 69668140 | XGBoost+MA3 | **0.18** | 31,365 | 1.98 |
| DOVE SH KERATIN STRT&SILKY 288X13.5ML | 64314335 | TSB | **0.18** | 20,714 | 3.61 |
| SURF PWDR PURPLE BLOOMS L 40(6+1)65G | 64861488 | MA3 | **0.41** | 640 | 1.00 |
| KNORR CUBES CHICKEN DUO 48X6X20G | 64784421 | TSB | **0.50** | 11,961 | 1.63 |
| SURF BAR CHERRY BLOSSOM SXFL 96X120G | 69725979 | XGBoost+MA3 | 0.50 | 3,845 | 1.28 |
| KNORR BN CUBES PORK SINGLES 48X12X10G | 68438413 | XGBoost+MA3 | 0.51 | 70,394 | 1.19 |
| KNORR CUBES PORK DUO 48X6X20G | 64784425 | TSB | 0.60 | 14,845 | 1.51 |

The ratio for KNORR CUBES CHICKEN DUO 48X6X20G (64784421) is 0.4964, so it falls under 0.5. The ratio for SURF
BAR CHERRY BLOSSOM SXFL 96X120G (69725979) is 0.5046, just over. The four products between 0.6 and 0.7 are
listed in `collapse_flag.csv`.

**DOVE SH KERATIN STRT&SILKY 288X13.5ML (SKU 64314335, product key 674)**, medium bin, served by TSB
(Teunter–Syntetos–Babai smoothing). Its 2026-03 TSB forecast, 20,714.3 pieces, is 3.61 times its MA3. In the
test window it was over-forecast in all six months (bias +102.8%), because TSB kept carrying the level from
before December. Error = forecast − actual, in pieces:

| Month | Error, pieces |
|---|---:|
| 2025-09 | +18,475 |
| 2025-10 | +11,866 |
| 2025-11 | +5,618 |
| 2025-12 | +36,009 |
| 2026-01 | +30,417 |
| 2026-02 | +7,549 |

**Would the rule have warned in advance?** This re-runs the rule each test month using only the history known
before that month (`collapse_flag_backtest.csv`):

| Rule result that month | Product-months | Products | % over-forecast | Bias | WAPE |
|---|---:|---:|---:|---:|---:|
| Flagged | 19 | 8 | 57.9% | +9.4% | 44.2% |
| Not flagged | 511 | 88 | 56.0% | +9.5% | 36.3% |
| Not assessable | 112 | 21 | 57.1% | +4.7% | 36.5% |

In this window, flagged months had larger errors (44.2% vs 36.3%) but were not more often over-forecast. That
makes it an "unreliable forecast, review it" flag rather than a "cut the order" flag. The sample is small (19
product-months).

One caveat: three of the four flagged products bounced back in 2026-02 after one or two very low months.
They are KNORR CUBES CHICKEN DUO 48X6X20G (64784421), SURF PWDR PURPLE BLOOMS L 40(6+1)65G (64861488) and SURF
POWDER CHERRY BLOSSOM L 288X65G (69668140). A very low month followed by a rebound looks more like a stock-out or
a delivery gap than lost demand, and sales data alone can't tell the two apart.

## 8. Longer backtest: 29 months vs 6 months (follow-up 1)

The same 107 products appear in every column, so only the window and the bin rule change (`run_followups.py`,
`window_comparison.csv`).

| Column | Test months | How the model is chosen |
|---|---|---|
| **A** | 2025-09 to 2026-02 (6) | The product's served bin (as of 2026-03) held fixed. This is the first report. |
| **B** | the same 6 months | Bin re-worked each month from the history known then, as the router actually runs |
| **C** | 2023-10 to 2026-02 (29) | Same rule as B |

**How B and C were built.**
- **B vs A:** the two differ on 53 of 642 product-months across 14 products (49 long → medium, 4 medium →
  short; `window_bin_changes.csv`). Everywhere else B reproduces A to within 0.00005 pieces.
- **Who is in C:** a product enters C once it has 3 months with sales. So each month covers 57 to 107 products,
  and the median product has all 29 months scored (minimum 5).
- **Peso basis:** each window's price per piece comes from its own test months, at selling price,
  VAT-inclusive (value-added tax). Cost is the same stock count (2026-04-06) throughout.

| Measure | A: 6 months, bin fixed | B: 6 months, bin re-worked | C: 29 months, bin re-worked |
|---|---:|---:|---:|
| Product-months scored | 642 | 636 | 2,419 |
| **Median product WAPE** | **29.3%** | **29.3%** | **26.9%** |
| …MA3, same months | 32.2% | 31.9% | 28.0% |
| …naive (last month's sales), same months | 39.6% | 40.6% | 34.6% |
| Products beating naive | 83 | 84 | 91 |
| Median product's average miss, pieces/month | 1,547 | 1,584 | 1,709 |
| Median product's average miss, ₱/month at selling price, VAT-inclusive (value-added tax) | 30,614 | 30,614 | 31,366 |
| **All 107 products summed: WAPE in pieces** | 14.9% | 15.4% | 14.2% |
| **All 107 products summed: WAPE in ₱ at selling price, VAT-inclusive (value-added tax)** | **8.3%** | **8.5%** | **10.7%** |
| …MA3 summed the same way | 11.4% | 11.5% | 11.4% |
| Product misses ÷ sales, ₱ at selling price, VAT-inclusive (value-added tax) | 33.2% | 33.3% | 30.0% |
| Average monthly miss, ₱ at selling price, VAT-inclusive (value-added tax) | 6.82M | 6.83M | 5.72M* |
| …surplus side, ₱ at selling price, VAT-inclusive (value-added tax) | 3.79M | 3.77M | 2.92M* |
| …shortage side, ₱ at selling price, VAT-inclusive (value-added tax) | 3.03M | 3.06M | 2.80M* |
| …surplus side, ₱ at cost (stock count), products with a cost basis | 3.31M | 3.29M | 2.61M* |
| **Surplus share of the peso miss** | **55.6%** | **55.1%** | **51.1%** |
| Product-months over / under / exact | 361 / 281 / 0 | 357 / 279 / 0 | 1,249 / 1,169 / 1 |
| Share of product-months over-forecast | 56.2% | 56.1% | 51.6% |
| Median product bias | +4.4% | +4.5% | +0.9% |
| Products net over / net under | 70 / 37 | 70 / 37 | 61 / 46 |
| **Products with 3+ over-forecast months in a row** | **44** | **43** | **87** |
| …expected if each product's own over/under months came in random order (mean, 95% range, 1,000 shuffles) | 45 (38–53) | 44 (37–51) | 87 (82–93) |
| Products in a 3+ over-forecast run at 2026-02 | 12 | 11 | 11 |
| Longest over-forecast run, median / max (months) | 2 / 6 | 2 / 6 | 4 / 10 |
| Longest under-forecast run, median / max (months) | 2 / 4 | 2 / 4 | 3 / 9 |

\*C's early months cover fewer products (57 at the start), so its peso amounts per month aren't comparable
with A and B. Compare the shares instead.

**What changes with the longer window:**
- **Product level:** the typical product's miss is slightly lower over 29 months, 26.9% vs 29.3%.
- **Total level:** the total miss is higher, 10.7% vs 8.3% in pesos at selling price, VAT-inclusive (value-added
  tax). The 8.3% was a good half-year. MA3 summed the same way is 11.4% in both windows. That is not a claim
  the served models beat MA3; DEC-26 records a tie.
- **Direction:** the over-forecast tilt mostly fades. The share of months over goes from 56.2% to 51.6%, and the
  median bias from +4.4% to +0.9%.
- **Runs:** the number of products with 3+ over-forecast months in a row matches what random ordering of each
  product's own over and under months produces (44 vs 45 expected; 87 vs 87). So a run mostly reflects a
  product's overall tilt, not a forecast stuck in one direction. Products like DOVE SH KERATIN STRT&SILKY
  288X13.5ML (64314335), over-forecast in 6 of 6 months, are the real cases, and §11 lists them.

**Category and total level, ₱ at selling price, VAT-inclusive (value-added tax)**
(`window_category_total_accuracy.csv`, which also has the pieces version):

| Level | Combined forecast, A | Combined forecast, B | Combined forecast, C | Product median WAPE, A | Product median WAPE, C |
|---|---:|---:|---:|---:|---:|
| CONDIMENTS | 26.0% | 25.9% | 26.2% | 28.9% | 27.7% |
| COOKING AIDS | 10.5% | 10.5% | 12.3% | 30.0% | 22.7% |
| DEODORANTS & FRAGRANCES | 19.7% | 19.6% | 17.2% | 21.8% | 20.3% |
| FABRIC CLEANING | 17.0% | 17.2% | 17.9% | 26.9% | 25.0% |
| FABRIC ENHANCERS | 30.5% | 31.3% | 31.3% | 35.1% | 35.6% |
| HAIR CARE | 18.7% | 19.3% | 22.2% | 38.7% | 36.1% |
| ORAL CARE | 29.5% | 29.5% | 28.8% | 29.5% | 28.8% |
| SKIN CLEANSING | 29.0% | 29.0% | 23.0% | 32.2% | 25.5% |
| **Total, all categories** | **8.3%** | **8.5%** | **10.7%** | **29.3%** | **26.9%** |

## 9. XGBoost with vs without the calendar-month feature (follow-up 2)

**Setup.** `month_of_year` was removed from the feature list in both training and forecasting. This was done
by wrapping `global_model.build_features` (`run_followups.py`, `variant()`), with nothing else changed. Before
comparing, the served version was rerun and reproduced all 72 of the 2026-03 forecasts and every backtest
forecast, to within 0.0001 pieces. As a noise yardstick, the same model was also rerun with only the random
seed changed (20260922 instead of 20260921). Only long-bin products are served by XGBoost, so the test covers
those. The feature set was fixed beforehand, not tuned on these months (`global_model.py:16-17`).

| Test | Products / product-months | Median WAPE, with → without | Change (95% interval) | Products better / worse without | Pooled WAPE, with → without | Bias, with → without | XGBoost part alone, pooled WAPE | Seed-only change (95% interval); better / worse |
|---|---|---|---|---|---|---|---|---|
| A: 6 months, bin fixed | 72 / 432 | 24.5% → 27.3% | **+2.8 points** (+0.2 to +3.6) | 13 / 59 | 35.0% → 36.8% | +8.0% → +7.8% | 36.2% → 40.2% | −0.2 points (−0.6 to +0.5); 36 / 36 |
| C: long-bin months, 2025-01 to 2026-02, bin re-worked | 67 / 759 | 24.8% → 26.6% | **+1.8 points** (+0.2 to +3.4) | 14 / 53 | 30.6% → 32.6% | +5.7% → +4.8% | 32.1% → 36.0% | +0.1 points (−0.6 to +1.5); 38 / 29 |

The 95% interval comes from resampling products with replacement (2,000 draws, seed 20261003). Over- vs
under-forecast flipped on 25 and 46 product-months, against 6 and 13 for the seed-only rerun.

**2026-03 forecasts without the feature:** all 72 change. The median change is 3.0% (seed only: 0.8%), the
90th percentile 6.3% (3.0%) and the largest 11.3% (7.5%). 40 go up and 32 go down (`xgb_month_ablation_2026-03.csv`).

**Answer.**
- **Accuracy:** calendar month helps. Without it, the forecast is worse on both test sets, the interval excludes
  zero, and most products get worse (59 of 72; 53 of 67). Changing only the seed moves nothing beyond noise.
- **Bias:** removing the feature doesn't fix the over-forecast tilt either; bias barely moves.
- **Why it can still fit with "about 5% seasonal" (a hypothesis, not tested):** the per-product tests look at
  one product's 24–38 months. The pooled model for the 2026-03 forecast trains on 2,719 product-months, so it can pick up a
  calendar pattern shared across products that no single series is long enough to show.

## 10. Seasonality label: proposed fix (follow-up 3)

**Code that computes today's label:**

| Step | Code |
|---|---|
| Series | `backend/routers/decomposition.py:37-75`, `GET /decomposition`. Builds a monthly series with missing months as zeros from `Unilever_SKU_Demand_Fact_Real`, or with the 2021-22 placeholder months in preview mode (`:46`). It calls `stl_summary` at `:71`. |
| Strength | `analytics/forecasting/decomposition.py:42-89`, `stl_summary`. STL fit at `:64`, strength formula `_strength` at `:35-39`, returned as `seasonal_strength` at `:83`. |
| Label | `frontend/src/components/SkuDemandPatternPanel.jsx:80-83`: ≥ 0.6 "Strong", ≥ 0.3 "Moderate", otherwise "Weak". Shown at `:244`, tooltip at `:251`. |

**Candidate rules, tested on series with no seasonality at our lengths.** STL needs 36+ months, and all 40
products with 36+ months have 38. The lag-12 tests need 24+ months, and the 72 products that qualify have 24
to 38. Three kinds of "no seasonality" series were simulated:
- **White noise:** 500 simulations per length.
- **AR(1):** each month carries over a little of the last one (φ = 0.085, the measured median lag-1
  autocorrelation of the 72 products). 500 simulations per length.
- **Own series shuffled:** each product's own straight-line trend plus its own leftover months in random order,
  200 per product.

| Rule | Products it can label | False alarm: white noise | AR(1) | Own series shuffled | Expected false "seasonal" labels among our products | Labelled seasonal today (real data to 2026-02) |
|---|---:|---:|---:|---:|---:|---:|
| R0, today: STL strength ≥ 0.6 | 40 | 14.6% | 15.8% | 17.8% | 5.8–7.1 | 16 |
| **R1: lag-12 test, \|ACF(12)\| > 1.96 ÷ √n (DEC-23)** | **72** | **0.9%** | **0.9%** | **0.7%** | **0.5–0.7** | **3** |
| R2: R1 after removing a straight-line trend | 72 | 0.8% | 1.3% | 1.25% | 0.6–0.9 | 3 |
| R3: R0 and R1 together | 40 | 0.2% | 0.2% | 0.4% | 0.1–0.2 | 3 |

Per-length rates are in `seasonality_rule_false_alarm_by_length.csv`; per-product rates are in `…_own_series.csv`.

**Proposal: R1, the lag-12 test already on record (DEC-23).**
- **24+ months and the test is significant:** label "Repeats yearly". Keep the STL chart and its peak/low
  months for these products only.
- **24+ months, not significant:** "No reliable yearly pattern".
- **Under 24 months:** "Not enough history (needs 24 months)".
- **Drop "Moderate":** no test sits behind it.

**Why R1:**
- It can label 72 products instead of 40.
- Its false alarms stay under 1% on all three null series at our lengths, against 15–18% for today's rule.
- It flags the same three products as R2 and R3.
- R2 would be the pick if trending products start triggering R1. In this cohort a trend did not inflate R1's
  false alarms (own-series null, 0.7%).

**Caveat:** at these lengths the test fires less often than its nominal 5% on random data, so it will miss weak
seasonality. There is no known-seasonal data here to measure how much. Making the change means the backend
returning ACF(12) and its bound from `/decomposition`, and a new label in `SkuDemandPatternPanel.jsx`.
Nothing was changed here.

**New "Repeats yearly" list (R1):**

| Product | SKU | Months | ACF(12) vs bound 0.318 | Peak / low month (STL) |
|---|---|---:|---:|---|
| BESTFOODS RGLR MYNS MAYOMAGICDOY24X220ML | 65004662 | 38 | 0.463 | Dec / Feb |
| CREAM SILK HC ULTREBORN HFALL 24X180ML | 68565205 | 38 | 0.344 | Jan / Oct |
| AXE DEO AP RLN DARKTEMP 24X25ML | 65003211 | 38 | 0.326 | Jun / Feb |

The other 13 products the dashboard calls "Strong" today become "No reliable yearly pattern" (§6 lists them).

## 11. Review before ordering (follow-up 4)

This table combines the 12 products in a 3+ month over-forecast run at 2026-02 (§3) with the 4 collapse-flagged
products (§7). DOVE SH KERATIN STRT&SILKY 288X13.5ML (64314335) is on both lists, so there are 15 products
(`review_before_ordering.csv`).
- **Forecast:** the served forecast for 2026-03.
- **Recent average:** the mean of 2025-12 to 2026-02, which is also the MA3 for 2026-03. It is shown only as
  the ratio "forecast ÷ recent", because per-product sales are client data.
- **Exposure:** max(forecast − recent average, 0) × the product's selling price per piece over 2025-09 to
  2026-02, at selling price, VAT-inclusive (value-added tax). It is how much more the forecast asks for than
  recent sales.
- **Months in run:** the over-forecast run in progress at 2026-02, counted with the bin fixed (6-month window)
  and with the bin re-worked (29-month window).

| Product | SKU | Why listed | Served model | Forecast 2026-03, pieces | Forecast ÷ recent average | Months in run (6 m / 29 m) | Exposure, ₱ at selling price, VAT-inclusive (value-added tax) |
|---|---|---|---|---:|---:|---|---:|
| SURF POWDER CHERRY BLOSSOM L 288X65G | 69668140 | collapse flag | XGBoost+MA3 | 31,365 | 1.98 | 0 / 0 | 96,195 |
| DOVE SH KERATIN STRT&SILKY 288X13.5ML | 64314335 | **both** | TSB | 20,714 | 3.61 | 6 / 6 | 85,383 |
| KNORR CUBES CHICKEN DUO 48X6X20G | 64784421 | collapse flag | TSB | 11,961 | 1.63 | 0 / 0 | 38,598 |
| KNORR BN CUBES BEEF SINGLES 48X12X10G | 68438418 | over-forecast run | XGBoost+MA3 | 84,180 | 1.08 | 3 / 3 | 37,603 |
| LADY'S CHOICE REAL MAYO 72X80ML | 69695555 | over-forecast run | XGBoost+MA3 | 13,842 | 1.04 | 4 / 4 | 16,890 |
| LADY'S CHOICE SS CHICKEN 72X80ML | 68764000 | over-forecast run | TSB | 2,329 | 1.23 | 3 / 3 | 14,939 |
| LADY'S CHOICE SS CHICKEN 72X27ML | 68763997 | over-forecast run | TSB | 3,971 | 1.37 | 3 / 3 | 12,920 |
| SURF BAR CHERRY BLOSSOM SXFL 96X120G | 69725979 | over-forecast run | XGBoost+MA3 | 3,845 | 1.28 | 3 / 3 | 9,232 |
| KNORR SINIGANG ISDA 24X12X11G | 67749046 | over-forecast run | XGBoost+MA3 | 14,810 | 1.10 | 4 / 4 | 9,219 |
| AXE DEO RO RLN DARKTEMP 24X40ML | 68736096 | over-forecast run | XGBoost+MA3 | 508 | 1.14 | 4 / 4 | 8,272 |
| REXONA MEN RO QUANTUM 72H 24X45ML | 69642633 | over-forecast run | XGBoost+MA3 | 439 | 1.17 | 3 / 3 | 7,434 |
| BESTFOODS SNDWCH SPRDSLDMATEDOY24X220ML | 65004685 | over-forecast run | XGBoost+MA3 | 678 | 1.08 | 3 / 3 | 3,018 |
| SURF PWDR PURPLE BLOOMS L 40(6+1)65G | 64861488 | collapse flag | MA3 | 640 | 1.00 | 0 / 0 | 0 |
| LADY'S CHOICE REAL MAYO DOY 24X130ML | 64961947 | over-forecast run | MA3 | 928 | 1.00 | 3 / 3 | 0 |
| LADY'S CHOICE REAL MAYO DOY 12X470ML | 69695556 | over-forecast run | XGBoost+MA3 | 1,634 | 0.96 | 4 / 2 | 0 |
| **Total** | | | | | | | **339,703** |

Notes:
- Three products show zero exposure because their 2026-03 forecast is at or below recent sales. Two of them are served
  MA3, so the forecast *is* the recent average; their risk shows in the run, not in next month's number.
- LADY'S CHOICE REAL MAYO DOY 12X470ML has a 4-month run with the bin fixed but 2 with the bin re-worked.
  With the bin re-worked, it is in the medium bin (served TSB) in all six months, and TSB under-forecast
  2025-12, which breaks the run.
- This is a review list. It changes no forecast or order (CLAUDE.md rule 9: nothing prescriptive).

## 12. Files

| File | Rows | What it holds |
|---|---:|---|
| `pull_inputs.py`, `pull_stock_count.py` | | The two read-only pulls (BEGIN; SET TRANSACTION READ ONLY; …; ROLLBACK), run 2026-10-03 06:28 UTC (Coordinated Universal Time) |
| `inputs/` | | Everything pulled. Nothing else was read from the database. **Not committed** (this folder's `.gitignore`): raw extracts of SSM client data, the same never-committed class as `backups/` and `data/processed/` in the repo `.gitignore`. Rerun the two pull scripts to recreate them. |
| `local/` | | **Not committed** (`.gitignore`). Full-detail tables with per-product sales and prices: both per-month files (`per_product_month.csv`, 654 rows; `longwindow_per_product_month.csv`, 2,419 rows) and the full copy of every table below. |
| `run_analysis.py` | | Offline. Rebuilds the backtest, checks the reproduction, writes everything below and in `local/`. `--svg-only` redraws the chart. Its `CLIENT_COLUMNS` list names every column kept out of the committed copies. |
| `per_product_summary.csv` | 132 | Per product: WAPE, average miss in pieces and ₱ (at selling price, VAT-inclusive (value-added tax), and surplus at cost (stock count)), bias, runs, flags, 2026-03 forecast. The 13 unscored products are included with their status. |
| `monthly_totals.csv` | 7 | §2 monthly totals |
| `category_total_accuracy.csv` | 9 | §4 |
| `cv_vs_wape.csv`, `cv_terciles.csv`, `cv_vs_wape.svg` | 107, 3 | §5 |
| `seasonality_reconciliation.csv`, `seasonality_noise_calibration.csv` | 132, 3 | §6 |
| `collapse_flag.csv`, `collapse_threshold_sensitivity.csv`, `collapse_flag_backtest.csv` | 132, 4, 3 | §7 |
| `price_and_cost_basis.csv` | 132 | Which products have a cost basis. The per-piece prices and costs are in `local/`; their aggregate checks are in `results.json` → `price_cost_checks`. |
| `results.json`, `run_log.txt` | | Headline numbers, the summary figures quoted in §1–§7, and the reproduction check |
| `run_followups.py` | | Offline. §8–§11. Stops unless B reproduces A where the bin is unchanged, and the served XGBoost reproduces the 2026-03 forecasts and every backtest forecast. |
| `longwindow_per_product_summary.csv` | 107 | §8 window C, per product: WAPE, average miss, bias, runs |
| `window_comparison.csv`, `window_category_total_accuracy.csv`, `window_bin_changes.csv` | 37, 9, 53 | §8 side by side; the product-months where the re-worked bin differs from the fixed one |
| `xgb_month_ablation.csv`, `xgb_month_ablation_2026-03.csv` | 6, 72 | §9 |
| `seasonality_rule_false_alarm_summary.csv`, `…_by_length.csv`, `…_own_series.csv`, `seasonality_rule_labels.csv` | 3, 22, 72, 72 | §10 |
| `review_before_ordering.csv` | 15 | §11 |
| `followups_results.json`, `followups_log.txt` | | Follow-up checks, output, and the summary figures quoted in §8–§11 |
| `run_quality_check.py`, `quality_check.csv`, `qc_numbers.csv` | | §14: the final quality check, and every README number with the file it was found in |

Rerun, after the two pull scripts: `run_analysis.py` (about 3.5 minutes, mostly the 200-shuffle STL test), then
`run_followups.py` (about 5 minutes, mostly the no-seasonality simulations). Both run with
`../Capstone-Project/.venv/Scripts/python.exe` from the worktree root.

## 13. Limits

- The headline and §8 use 29 test months; §1–§7 use the latest six. Window C's early months cover fewer
  products, because products enter as they reach 3 sales months.
- Peso figures at selling price show how much is exposed, not how much is lost. The "at cost" figures use the
  stock count's valuation, which is close to gross sales value, not a confirmed purchase cost.
- The 12 one-month products and the 13 unscored products are left out of totals, runs, category and
  correlation.
- Category totals in pieces add different pack sizes together.
- Window C values surplus in 2023–2025 at the 2026-04-06 stock-count cost, the only count used.
- The calendar-month test (§9) covers the long-bin products only, since they are the only ones served by
  XGBoost. Why the feature helps is not tested.
- The seasonality rules' ability to *find* real seasonality is not measured; there is no known-seasonal data here.
- Per-product sales and prices are not stored in the committed files, but some can still be worked out:
  - **Price per piece:** a product's average miss in pesos ÷ its average miss in pieces.
  - **Average sales:** its average miss ÷ its WAPE.

  Those error summaries were kept as asked; drop one of them if that matters.

## 14. Quality check (2026-10-03)

`run_quality_check.py` runs read-only and offline, using fresh code for the recompute. It writes
`quality_check.csv` (28 checks, all PASS after the fixes below) and `qc_numbers.csv`, which lists every README
number with the file it came from. This section reports on the check itself, so it is not part of the number
check.

| Check | Result | Evidence |
|---|---|---|
| 1. Number check | **FIXED** | 1,001 numbers outside §14. 988 were found in their own section's files, 262 of them on product rows matched only against that product's row. 13 are stated settings: seeds, 95% bounds, 1.96, 2,000 draws, the 20% split, p < 0.001 and a runtime. 0 unsourced. **Fixed:** two hand-rounding slips, BESTFOODS RGLR MYNS MAYOMAGICDOY24X220ML (65004662) average miss 4,926 → 4,925 pieces/month and LADY'S CHOICE SS CHICKEN 72X80ML (68764000) exposure ₱14,940 → ₱14,939 at selling price, VAT-inclusive (value-added tax); "about 2,700" → 2,719 training rows; "0.0001" (a tolerance) → 0.00005 pieces (the measured gap); and the 3-of-72 share (4.2%) added to `results.json`. A first version of the check matched numbers against every file and passed everything, so it was narrowed to each section's own files. |
| 2. Arithmetic | PASS | Surplus + shortage = miss to ₱0.0000 in every month and all three windows. Over + under + exact = scored product-months: 361 + 281 + 0 = 642; 357 + 279 + 0 = 636; 1,249 + 1,169 + 1 = 2,419. Category counts 18 + 21 + 10 + 25 + 4 + 25 + 1 + 3 = 107. Category sales and misses add to the total to ₱0.0000 in the 6- and 29-month windows (₱ at selling price, VAT-inclusive (value-added tax)). The review exposure adds to ₱339,703.24 at selling price, VAT-inclusive (value-added tax), and each row equals max(forecast − recent average, 0) × price. |
| 3. Independent recompute | **FIXED** | Fresh code: its own WAPE, prices and autocorrelation; actual sales from the raw pull; forecasts taken as given. Results: median product WAPE 29.315% (6 months) and 26.860% (29 months); total 8.254% and 10.653% in pesos at selling price, VAT-inclusive (value-added tax); surplus share 51.103%; the same 3 "Repeats yearly" products. **Fixed:** the first fresh run read the one empty quantity as missing rather than 0 pieces (the pipeline's rule), which dropped that product from the median. The README now names that product-month (§1). |
| 4. Data rules | PASS | Demand is read only through `Unilever_SKU_Demand_Fact_Real` (`is_demo = false`): 0 `is_demo` rows among 3,087 product-months. Gap fills are blocked by 0038's CHECK constraint. The stock count is filtered on `is_demo = false AND fill_source IS NULL`: snapshot 2026-04-06, 785 rows, 120 Tier A products. |
| 5. Wording | **FIXED** | Every peso figure is labelled. Product name comes before SKU on all 82 SKU mentions. Jargon is spelled out at first use (WAPE, MA3, TSB, STL, ACF, CV, GSV, VAT, LP, MASE, MAPE, XGBoost, SKU, ABC, AR(1), DEC-26, UTC). DEC-26 "tie" is kept, and both sentences about beating MA3 say it is not claimed. **Fixed:** headline rebuilt on the 29-month result; three unlabelled peso lines; shortened product names replaced by full name and SKU; §6's "not run" note updated (§9 runs it); periods added in §4, §5 and §10. |
| Client data | **FIXED** | Per-product monthly sales and prices removed from every committed file. Both per-month tables are local only, and `run_analysis.py`'s `CLIENT_COLUMNS` list drops sales, last-month and 3-month sales, prices and costs from the rest. The README tables no longer show sales or prices. See the last bullet of §13 for what can still be worked out. |

Repo hygiene (no client data in this branch's commit, and a dry merge into `group7/kelvin-etl`) is checked
on the commit itself, so it is reported with the commit rather than here.
