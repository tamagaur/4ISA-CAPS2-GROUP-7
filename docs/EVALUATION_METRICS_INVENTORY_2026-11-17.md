> **Dated record (2026-11-17), not a maintained document.** Its figures are as of that date and have not been re-checked against live since; they are not current claims. Current state: STATE.md; the provenance rules: docs/FIGURE_PROVENANCE.json.

# Where an evaluation metric is stated, and whether it agrees with the pinned set (2026-11-17)

**The pinned set:** `docs/EVALUATION_METRICS.json` / `.md` (`scripts/evaluation_metrics.py`; checked against live by `scripts/check.sh`,
both modes, and by `tests/invariants/test_j_evaluation_metrics.py`, which also holds the error card's served figures equal to the pinned
cell of the same population). This file is a DATED RECORD of a read-only sweep of the tracked tree on 2026-11-17 (git grep and reading;
no database, except where a row says live). Line numbers are as of the sweep, before the fixes below. "Agrees" = same measure, population
and window as a pinned cell, value equal to the precision shown; "n.a." = a different measure, population or window, named in the row.

## What this commit changed because of the sweep

| Item | Before | Now |
|---|---|---|
| Error card near-zero MAE / RMSE (backend/marts.py mape_summary) | raw net pieces: 4,280 / 10,696 on Mar 2025-Feb 2026 | a net-negative month counts as 0 sold, the WAPE's and the pinned set's basis: 4,241 / 10,676 (42 of the 368 product-months were net-negative) |
| Card line, near-zero MAE / RMSE | "(MAE 4,280, RMSE 10,696)" | "(MAE 4,241, RMSE 10,676, those 39 only)"; the tooltip label says they are not the forecastable products' MAE / RMSE |
| Card line, pooled WAPE over 233 | "the same 233 scored products (pieces)" | "(pieces, near-zero ones included)"; its tooltip label was "Typical product, weighted by sales", the MAPE's name too; now "Pooled product WAPE, every scored product ... Not the typical product's MAPE" |
| Card line, MASE entry test | "115 of 175 under 1" | "115 of 175 forecast products with a MASE under 1" |
| Data Dictionary, WAPE entry | no basis, no population | the net-negative rule and "covers more products than the card's MAPE" |
| docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.md table | 110 of 175 / 0.823; 37.88% / 29.69% / 10.77%; 17.44%; error split of 2026-11-10 | the JSON's values (115 of 175 / 0.755; 36.37% / 28.87% / 8.70%; 19.50%; 9,389,241 / 5,083,650 / 3,096,724) |
| STATE.md :415 "Pinned (published) figures" | "MASE < 1 for 109 of 175; ... 749 months" | 115 of 175, median 0.755; 852 of 4,370 months |
| STATE.md :211, :296, :384, :145, :169 | current-tense card / forecast figures of earlier dates | dated, with today's value or "not re-measured" |
| ARCHITECTURE.md DEC-46 | "109 of the 175 ok forecasts pass ... and are the plan" | 115 (lp_run 10), 109 when recorded |
| docs/CHAPTER4_MOVED_FIGURES_2026-11-11.md :73, :275 | 30.12% called "headline pooled WAPE"; pre-rule pooled WAPEs "the same on live" | 30.12% named as the run without the calendar factor; 31.95% / 36.33% / 27.24% since 2026-11-17 |
| reports/CALENDAR_GRAIN_2026-11-12.md :42-43 | card pooled WAPE and MAPE of 2026-11-12 shown as live | each row says its basis and today's value |
| docs/CALENDAR_SELECTION_2026-11-16.md :12 | 31.93% "for live" | the panel's approximation of live, not the card's 31.95% |
| docs/DEPLOY_AND_TEST_2026-11-13.md row 6 | near-zero 4,280 / 10,696 | 4,241 / 10,676 and the new card wording; the after-March value marked as measured on the old basis |
| The two scratch folders with the in-window R² (git-ignored local/: metrics_recon_2026-11-17 in worktree dsd-metrics-recon, metrics_six_2026-11-17 here) | unlabelled | banner: hindsight benchmark, not used, why; quote nothing |

## Left as they are, and why

| Item | Why |
|---|---|
| reports/figures/FIGURES.md :160 caption "pinned figure 109 of 175"; :179 "median product WAPE about 40%" vs :204 "35.49%" (same window); scripts/manuscript_figures.py :690 / :720 | manuscript figure text (out of scope); reported |
| docs/ACCURACY_AS_SERVED.md "2023-10 to 2026-02" | generated, its sections pinned verbatim in the published snapshot; the run label (mart.forecast_run) says 2023-10, but run 21's scored rows span 2024-01..2026-02 (4,370 rows, read on live 2026-11-17): the label names the forecast span, the rows start at 2024-01 |
| Backtest MASE of the earlier window, 0.871 (error hunt, STATE :341) vs 0.901 (CALENDAR_GRAIN :40, STATE :230) | unresolved; a re-run of both scripts on the same product set would settle it; not investigated |
| CHAPTER4_MOVED :322 baselines 32.00% / 36.43% | match no card value of any date; unresolved |
| Dated records (reports/ experiment folders, STATE.md entries with a date, KNOWN_ISSUES A12 / P5b) | dated, labelled with their run; not current claims |
| Comments with old counts (Charts.jsx :2624 / :2645, dashboard.py :105, abc.py :103) | each carries its date |
| Company-total WAPE "all 233 scored products (pesos)" | 9 product-months of 2 products have no price on Mar 2025-Feb 2026 (live, read-only) and add nothing to the pesos; side finding, not changed |

## Settled later the same day (the figure-provenance audit, docs/FIGURE_PROVENANCE.md)

| Item left above | What it was |
|---|---|
| FIGURES.md "median product WAPE about 40%" beside "35.49%" | 35.49% is stored run 11's median product WAPE (raw per-product rule, 222 products), not the run the figures read. No stored Tier A run gives "about 40%" on the window. Both captions are now computed from the rows drawn: 33.2% over 222 products (run 21). |
| CHAPTER4_MOVED baselines 32.00% / 36.43% | The card's rows (run 21) scored Σ|forecast − actual| ÷ Σ|actual| by `local/q9.py`: 32.00% / 36.43% / 27.25% on live. A third scoring rule beside the card's two, now named in place. |
| Backtest MASE 0.871 vs 0.901, earlier window | Two MASE scales on one forecast (run 16): fixed 2023-01..2025-08 (error hunt; 0.871, 270 products, exact on live) and the change before the window (calendar grain; 188 products; 0.904 on live, so 0.003 unresolved). Labelled in place. |

## A. Code and the app

Scope: tracked files under backend/, frontend/src/, analytics/, scripts/ (not scripts/archive/), tests/. Searched with git grep for
MAE/RMSE/MAPE/WAPE/MASE/R2 variants (mae_, _rmse, r2, r_squared, R², "coefficient of determination") and for every pinned literal.
No database, no app run. "Card" = ForecastErrorSummaryCard (frontend/src/components/RangeCards.jsx:401), shown on SKU Forecast
(SKUForecast.jsx:2118), fed by GET /dashboard/accuracy (backend/routers/dashboard_range.py:240); GET /dashboard serves the same
block as `forecast_accuracy` (backend/routers/dashboard.py:2467-2493, no longer drawn on the Dashboard). Default run = mart.accuracy_mart
run labelled DEFAULT_BACKTEST_LABEL (backend/marts.py:990); "run 21" is the caller's id, the code uses the label only.

### Headline answers

- **R²: not anywhere in code.** No forecast R² is computed, stored, served or stated. The pinned R² figures have no code counterpart.
- **MAE / RMSE served to a page: only the near-zero line** (backend/marts.py:1293-1294 -> RangeCards.jsx:537, 578). The pinned MAE/RMSE
  for all-scored / forecastable / order-plan exist nowhere in code. Per-product holdout MAE/RMSE are SERVED but not drawn: GET
  /forecast/{sku} returns Forecast_Result.model_params (backend/routers/forecast.py:162-180), which holds `holdout_metrics_served.rmse`
  and `holdout_metrics_all_methods.{m}.mae/.rmse` (scripts/run_baseline_forecast.py:973-983, 1271-1275). The SKU page's "Off by about X
  pcs per month" (PendingCards.jsx:52, from SKUForecast.jsx:812) is a per-product MAE, raw net, not called MAE.
- **Backtest MASE (pinned 0.718 / 0.722 / 0.626 ...) is not computed or served anywhere.** The only MASE served is the stored
  Forecast_Result.mase (entry test, per-SKU reliability, ABC/Reorder reasons).
- **Label problem (1), near-zero MAE/RMSE**: visible text names the population (near-zero products only) but NOT the basis (raw net, vs the
  pinned set's actual clipped at 0) and not that they are not the forecastable/all set. Exact text below (rows C7, C8).
- **Label problem (2), WAPE over 233 beside MAPE over 179**: the visible line DOES name each population (rows C1-C4). Remaining gaps:
  the pooled WAPE's basis rule ("a net-negative month counts as 0 sold") is in the API `measure`/`wape_pieces_rule` but never on screen;
  "all 233 scored products" on the company-total pesos WAPE is UNVERIFIED (pesos sums only rows with a price; `products_without_price` is
  served but not shown); the entry-test MASE "115 of 175" has no noun naming the 175.

### Table

| # | file:line | metric | value stated / computed | population | window, source run | basis | label names population? | agrees with pinned? | note |
|---|---|---|---|---|---|---|---|---|---|
| C1 | frontend/src/components/RangeCards.jsx:520 (backend/marts.py:1540, 1557, 1159) | WAPE, company total, pesos | computed (`company_total.value`) | text says "all {products} scored products" = every product with a scored month (233) | picked range (default card window Mar 2025-Feb 2026, UNVERIFIED default); default run per month (marts.py:1098-1127) | raw net, pesos at selling price; only rows with a price contribute (marts.py:1403-1407) | yes ("Company-total WAPE, all 233 scored products (pesos)") | n.a.-different measure (company total ~8.5%) | "all 233" is UNVERIFIED: priced rows only; `products_without_price` (marts.py:1565) not shown |
| C2 | RangeCards.jsx:524 (marts.py:1539, 1163) | WAPE pooled, pieces | computed (`typical_product_weighted.value` = `wape_pieces`) | all scored (233 / 2,052 pm on card window) | as C1 | clipped: sum\|f-max(a,0)\|/sum max(a,0) (marts.py:1320-1322, 1401-1402) | yes ("Pooled product WAPE, the same 233 scored products (pieces)") | yes (31.95% card window; full span 28.87% if that range is picked) | basis rule not on screen (only in API `measure`, `wape_pieces_rule`) |
| C3 | RangeCards.jsx:529 (marts.py:1273, 1278-1279) | MAPE headline | computed (`mape.value`) | forecastable: no near-zero month, sold >=1 month (179) | as C1 | a>0 months only (clip irrelevant) | yes ("MAPE, 179 Tier A products with no near-zero month (typical product)") | yes (32.42%; mean 51.66% in `mape.mean`, tooltip RangeCards.jsx:566) | tooltip label MAPE_LABEL marts.py:1176-1178 |
| C4 | RangeCards.jsx:534 (marts.py:1275, 1286) | MAPE all products | computed (`mape.all_products`) | every scored product that sold (218) | as C1 | a>0 | yes ("MAPE, all 218 Tier A products that sold in the window, the 39 near-zero ones included") | yes (38.70%) | tooltip RangeCards.jsx:567-569 also explains 233 vs 218 |
| C5 | RangeCards.jsx:531, 580-584 (marts.py:1274, 1287-1290) | MAPE stock-limited variant | computed | forecastable products with a non-stock-limited month sold | as C1 | a>0, stock-limited months removed | partly ("leaving out stock-limited months"; product count only in tooltip) | n.a.-not in pinned set | |
| C6 | RangeCards.jsx:616-620 (marts.py:1247-1267) | MAPE order plan | computed (`mape.planned_products`) | forecastable products with a row in the current plan (100 of 115, cycle 2026-03-01, LP run 10) | as C1 | a>0 | yes ("MAPE, 100 of the 115 products in the Mar 2026 order plan (LP run 10) with no near-zero month (typical product): ..., against 32.4% for all 179 above") | yes (27.21%; mean 30.71% served as `planned_products.mean`, not drawn) | caveat "Backtest errors on past months, not the plan's quantities" |
| C7 | RangeCards.jsx:537 (marts.py:1293) | MAE, pieces | computed (`near_zero_flag.mae_pieces`; 4,280 on card window per test fixture) | the 39 near-zero products only, all their scored months | as C1 | **raw net** (`abs(fc-act)`, act unclipped; marts.py:1335) | yes, population; no, basis. Exact: "· {39} near-zero Tier A products scored in pieces instead (MAE <strong>4,280</strong>, RMSE <strong>10,696</strong>)" | n.a.-different measure (pinned MAE is clipped and over all/forecastable/plan) | sits on the same line as C2-C4; nothing says it is not the forecastable set's MAE |
| C8 | RangeCards.jsx:537, 577-578 (marts.py:1294) | RMSE, pieces | computed (`near_zero_flag.rmse_pieces`; 10,696) | as C7 | as C1 | raw net (`(fc-act)^2`, marts.py:1337, 1422) | tooltip: "Near-zero products (39; N product-months). [NEAR_ZERO_LABEL] MAE X pieces, RMSE Y pieces a product-month." NEAR_ZERO_LABEL (marts.py:1197-1200): "...left out of the MAPE above, counted here, and scored in pieces: MAE ... and RMSE ... over all their scored months" | n.a.-different measure | basis never stated anywhere on screen or in the API block |
| C9 | RangeCards.jsx:543-544, 587-589 (backend/routers/dashboard.py:1052-1061, 1077-1091; dashboard_range.py:233-237) | MASE entry test | computed (`entry_test`: passed / scored / median) | Forecast_Result rows of Unilever's latest forecast_date with status 'ok' and a MASE (175) | Forecast_Result 2026-03-01; served model's rolling one-step holdout, last 20% of history, scale from earlier months (ENTRY_TEST_MEASURE dashboard.py:1077-1080) | series as stored by the runner (UNVERIFIED whether clipped) | partly: "MASE, plan entry test on the latest forecast, not this range: 115 of 175 under 1 (median 0.76)"; the 175 is not named | n.a.-different measure (stored MASE; snapshot pin 115/0.755; manuscript 109/0.827 held) | code calls it a HOLDOUT MASE, not in-sample (see contradictions) |
| C10 | RangeCards.jsx:338, 347 | company-total pesos miss share per month | computed (\|net_miss_pesos\|/actual_pesos) | all scored products of that month | one month | raw net pesos | "Difference ... · X% of sales" (no population) | n.a.-different measure | monthly company-total error, not labelled WAPE |
| C11 | backend/marts.py:1509-1513, 1560 | per-product median WAPE | computed (`median_product_wape`), served by /dashboard and /dashboard/accuracy, not drawn | products with sum\|a\|>0 | as C1 | raw: sum\|f-a\|/sum\|a\| (p["act"] += abs(act), marts.py:1340) | n.a. (API only, no label) | n.a.-different measure (pinned 36.37% full span) | |
| C12 | backend/marts.py:1536 | monthly pooled WAPE pieces | computed (`by_month[].wape_pieces`), not drawn | all scored that month | one month | clipped | n.a. | n.a. | |
| C13 | backend/marts.py:1576-1598 (dashboard_range.py:283-284) | category WAPE pieces | computed (`wape_pieces` per category, level=category), not drawn (CATEGORY_MISS_COLUMNS RangeCards.jsx:887-894 shows no %) | products of the category | as C1 | clipped | n.a. | n.a. | |
| C14 | backend/marts.py:1142, 1155 | WAPE (comment/docstring) | "9.9% or 29.6%"; "0.099 = 9.9%" | default backtest of 2026-10-05 | stale | old raw basis | no | no (29.6% matches neither 31.95 nor 28.87; 9.9 is not the current ~8.5/8.7) | stale comment |
| C15 | backend/marts.py:1380; tests/invariants/test_h_error_card_populations.py:89 | WAPE pooled (comment) | "32.04% against 31.95%" | all scored, card window | default run | 32.04 raw, 31.95 clipped | yes (in comment) | yes (31.95) | |
| C16 | backend/marts.py:1190-1194 (comment) | MAPE near-zero rationale | "46 product-months (2.5%) carried 94%", "38 of them" | card default range 2026-11-15 | as of 2026-11-15 | a>0 | yes | n.a. | measurement note |
| C17 | frontend/src/components/HeroKpis.jsx:957-963 (Dashboard.jsx:1560-1566; dashboard.py:1062-1065, 2522-2528) | MASE pass count | computed: "{passed} of {total} top sellers planned"; passed = evaluated_count - unreliable_count | all Forecast_Result rows of latest date in scope (189, all statuses) | Forecast_Result latest | stored MASE | partly: says "top sellers"; "{total-evaluated} had too little history" also counts dead_sku rows (5 of the 14 per manuscript_figures.py:779) | n.a.-different measure | "planned" is the MASE pass count, not the plan's row count (equal today only if both are 115, UNVERIFIED) |
| C18 | frontend/src/components/SKUForecast.jsx:1536-1537, 3117-3141 (backend/routers/forecast.py:162-177) | MASE per product | computed (Forecast_Result.mase, 2 or 3 decimals) | one product | latest stored forecast, holdout window shown ("tested on ...") | stored | yes (one product) | n.a. | |
| C19 | frontend/src/components/PendingCards.jsx:52-55 (SKUForecast.jsx:798-825) | per-product MAE (unnamed) + share of forecast | computed: "Off by about X pcs per month ... ~Y% of the forecast" | one product | picked range, default run rows (GET /dashboard/accuracy?level=product) | raw net; share divides by FORECAST, not actual | yes (one product) | n.a.-different measure | share_of_forecast is a forecast-denominator WAPE |
| C20 | SKUForecast.jsx:3147-3155; labels.js:129; DataDictionary.jsx:133-139 | "Typical miss" WAPE per product | computed "About X% of the forecast" | one product | picked range | raw, forecast denominator | yes | n.a. | DataDictionary text says card WAPE divides "by the total actual sales"; never mentions the clip rule; comment cites diagnostic_metrics.wape (sum\|a\|, negatives included) |
| C21 | backend/routers/forecast.py:162-180; backend/schemas/forecast.py:28-30 | MAPE, MASE per SKU (+ model_params WAPE, RMSE, MAE) | served: `mape` (percent), `mase`, `model_params.wape`, `holdout_metrics_served{mape,mase,wape,rmse,ma3_wape}`, `holdout_metrics_all_methods{m:{mae,rmse,mape,mase}}` | one product | Forecast_Result rows of every forecast_date; holdout = last 20%, rolling one-step | diagnostic_metrics: MAPE a>0; WAPE/RMSE/MAE every actual incl. negative (analytics/forecasting/diagnostic_metrics.py:38-75) | n.a. (API) | n.a. | MAPE carried into SKUForecast.jsx:1259 but never displayed |
| C22 | backend/routers/abc.py:219-233; frontend/src/components/ABCClassification.jsx:131-136; frontend/src/utils/reorderView.js:122-126; backend/routers/recommendations.py:691-701 | MASE per product (reason text) | computed "Not planned: forecast accuracy check not passed (MASE 1.24)" | one product | latest Forecast_Result | stored | yes | n.a. | |
| C23 | frontend/src/components/MonthlyBatchPanel.jsx:184 (scripts/cycle_feedback.py:72-89, 116-117) | WAPE one cycle | computed "Error X%, bias Y%" | every status-'ok' Forecast_Result product of the cycle ("across N products") | one month (the cycle) | **raw net**, no-row month = 0, unclipped | partly ("across N products"; never says WAPE on screen) | n.a.-different window | |
| C24 | backend/routers/dashboard.py:2276-2290; Charts.jsx:2618-2624; DataDictionary.jsx:120; labels.js:33,127 | RMSE (band) | computed band = ±1.645 x per-SKU holdout RMSE; comment literal "±159k (±15%)" around 1,085,193 pcs | MASE<1 gated SKUs | latest forecast | holdout RMSE | yes ("~90%") | n.a. | Charts.jsx:2624 literal is a stale comment |
| C25 | Charts.jsx:2645-2647 (comment) | MAPE/MASE gate counts | "19 of 132", "passes 73" | Class A 2026-09-29 | stale | | n.a. | no (stale) | comment |
| C26 | backend/routers/dashboard.py:105; backend/routers/abc.py:103 (comments) | MAPE/MASE counts | "100 of 132"; "Of the 132, 46 failed MASE < 1" | Tier A 2026-09/10 | stale | | n.a. | no (stale) | comments |
| C27 | scripts/run_lp.py:38-39 (docstring) | MAPE/MASE shares | "~15% ... mape < 20%", "~50-56% clear mase < 1.0" | bake-off Tier A | 2026-09 bake-off | | n.a. | n.a.-bake-off | |
| C28 | analytics/forecasting/challenger.py:26 | MASE bake-off | "0.854 against MA3's 0.819 ... 89 products" | bake-off cohort 89 | last 6 months, reports/MODEL_BAKEOFF_UNILEVER.md | | yes | n.a.-bake-off (Table 4.2.13 values) | |
| C29 | scripts/manuscript_figures.py:579-582, 598 | MASE bake-off Table 4.2.13 | 17 medians, e.g. ma3 (0.819, 89), hw_add12 (0.741, 62), sarima_seasonal (0.989, 49) | bake-off cohorts (89 / 62 / 49) | frozen CSV reports/model_bakeoff_unilever_tierA_allmetrics.csv | | yes | n.a.-bake-off | verified against CSV, not recomputed |
| C30 | scripts/manuscript_figures.py:780-787, 1279 | MASE stored | asserts 175, 109 below 1, median 0.827 (manuscript values) | Forecast_Result 2026-03-01 status ok | frozen docs/published_snapshot_2026-10-24/mase_rows.csv | stored | yes | n.a.-different measure; held disagreement with pin 115/0.755 | caption says "served model's rolling one-step holdout, DEC-25" |
| C31 | scripts/manuscript_figures.py:690 vs :720 | median product WAPE | ":690 'median product WAPE about 40%'"; ":720 '35.49% for this window'" | all scored, card window Mar 2025-Feb 2026 | frozen snapshot | raw (per-product) | yes | n.a.-different measure | the two captions disagree for the same window (see contradictions) |
| C32 | scripts/manuscript_figures.py:627-640 (TABLE_4_2_18) | monthly WAPE % pieces | e.g. 2025-03 20.3, 2025-11 32.4, 2025-12 58.3 | all scored that month | Mar 2025-Feb 2026, frozen snapshot | "scored as GET /dashboard forecast_accuracy scores them" (ACC_SOURCE :643): basis of the frozen scoring UNVERIFIED (card switched to clipped 2026-11-17) | yes | n.a.-monthly | |
| C33 | scripts/manuscript_figures.py:772-773; scripts/snapshot_published_figures.py:161-164, 418 | MASE stored | comment literals "109 of 175", "115 of 175"; computed from pin | Forecast_Result latest, status ok | pin docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json | stored | yes | n.a.-different measure | |
| C34 | scripts/snapshot_published_figures.py:96, 145-187 | headline WAPE (median product, pooled pcs, total pesos) | computed vs pin | as-served backtest rows | stored runs / frozen CSVs | pooled = published rule | n.a. | pooled full span = 28.866% (pinned) | --verify compares to live |
| C35 | scripts/accuracy_as_served.py:164-256, 265-345, 350-422 | MASE pass rate, per-route WAPE + median MASE, headline WAPEs | computed, written to docs/ACCURACY_AS_SERVED.md | Tier A cohort as of latest; per route | stored definition (holdout 20%); as-served backtest | per-route WAPE = sum\|a-f\|/sum\|a\| (raw, :302); headline per backtest_forecast_run.headline | yes | MASE n.a.-different; per-route WAPE n.a. (raw) | |
| C36 | analytics/forecasting/treatments.py:7 | WAPE, MASE | "pooled WAPE -3.5 pts [-7.3,-1.3] ... -2.6 [-4.4,-1.5]; MASE 0.776 -> 0.731 and 0.888 -> 0.871" | as-served backtest, all products | 2025-09..2026-02 and 2024-01..2025-08 (experiment) | experiment's | yes | n.a.-different windows/experiment | |
| C37 | analytics/forecasting/calendar.py:23-24; analytics/params.py:168-169; scripts/backtest_forecast_run.py:73; analytics/forecasting/baseline.py:174-175 | median WAPE (experiments) | 0.315->0.299 (180 products, 2025-01..2026-02); 0.318->0.305 vs 0.304; 0.268602->0.267802 (2419 rows); 0.265->0.430 | experiment cohorts | various | per-product median | yes | n.a.-different measure | historical evidence comments |
| C38 | analytics/forecasting/baseline.py:223-282; sarima.py:209-263; scripts/run_baseline_forecast.py:516-530, 658-687, 796, 920-921, 977, 1071, 1273 | MAE, RMSE, MAPE, MASE per SKU per method | computed (holdout); printed medians to console/report | Tier A forecast cohort | holdout last 20% | diagnostic_metrics | n.a. | n.a. | sarima.py is retired |
| C39 | scripts/bakeoff_to_xlsx.py:73-228; scripts/xgboost_bakeoff.py:139-145, 232; scripts/preview_router_synth.py:105; scripts/evidence/ch0*.py | MAE, RMSE, MAPE, WAPE, sMAPE, MASE | computed (bake-off / evidence / what-if) | bake-off cohorts; synthetic what-if (preview_router_synth, never served) | various | diagnostic_metrics | n.a. | n.a.-bake-off | bakeoff_to_xlsx.py:219 states "MAPE < 0.20 Project gate" (no gate uses MAPE since 2026-09-21, :39) |
| C40 | analytics/forecasting/sarima.py:16,20,54,270; tests/forecasting/test_sarima.py:6,63-68 | MAPE gate | 0.20 | n.a. | retired | | n.a. | n.a. | dead code |
| C41 | frontend/src/components/ForecastErrorSummaryCard.test.js:49-73, 96-97, 107 | WAPE, MAPE, MAE, RMSE, MASE (fixture) | 0.085, 0.319523, 0.324 (179), 0.387 (218), 0.272 (100 of 115), 4280.2, 10696.4, 115 of 175 median 0.76; asserts '8.5%','32.0%','32.4%','38.7%','4,280','10,696','27.2%' | as live card | comment: "read from live on 2026-11-17 for Mar 2025 - Feb 2026" | as card | n.a. | yes for WAPE/MAPE/plan; MAE/RMSE n.a.-different | near-zero `product_months: 120`, stock-limited 0.318, possibly_stock_limited 12 look like placeholders: UNVERIFIED as live values |
| C42 | tests/backend/test_practice_copy_label.py:148-151, 171-179 | WAPE, MAPE, MASE (fixture) | products 239, company 0.109, pooled 0.463, MAPE 0.3397 (210), entry 115/175/0.755 | fixture | window 2025-03..2026-02 | n.a. | n.a. | no (real-looking but not pinned: 239 vs 233, 33.97%/210 vs 32.42%/179) | fixture only; harmless but could be mistaken for a figure |
| C43 | tests/backend/test_entry_test.py:29-31, 42 | MASE (fixture) | 175 / 110 / 0.8731 -> 0.873 | fixture | | | n.a. | n.a. (matches neither pin nor manuscript; 110 was STATE's earlier value) | fixture |
| C44 | tests/backend/test_dashboard.py:2543-2558 | MAE, RMSE near-zero (unit) | (4998+0)/2, sqrt(4998^2/2) | synthetic rows | | raw net | n.a. | n.a. | pins raw basis of C7/C8 |
| C45 | tests/forecasting/test_mape_rule.py:27-28; test_diagnostic_metrics.py:84,121-124; test_blank_quantity.py:157,166; test_sarima.py:109-111; tests/backend/test_forecast.py:82-122 (mape 31.852, mase 0.4263, wape 0.2587) | MAE, RMSE, MAPE, MASE (unit) | synthetic | | | | n.a. | n.a. | unit tests |
| C46 | tests/invariants/test_h_error_card_populations.py:1-98 | MAPE, pooled WAPE | computed from live vs card | all / forecastable / plan | card window, default label | clipped WAPE | yes | checks C2, C3, C4, C6 | does NOT check C7/C8 (MAE/RMSE) or C9 |
| C47 | tests/invariants/test_g_constants_match_live.py:91-101 | MASE stored | parses "MASE < 1 N of M" in STATE.md vs live | Forecast_Result latest ok | live | stored | yes | n.a.-different measure | |
| C48 | backend/practice_copy.py:75-78; scripts/practice_artefacts.py:162; tests/demo/test_demo_schema.py:10; analytics/db/migrations/0052_demo_schema.sql:10 | all metric names | regex/withholding only, no values | | | | n.a. | n.a. | |
| C49 | analytics/db/schema.sql:576-588 | MAPE/MASE column notes | "20.0 means 20%", ">= 0.20" | Forecast_Result | | | n.a. | n.a. | |

### Other figure pairs where populations differ (beyond the two known)

1. Card line, C9 vs C3/C2: "115 of 175" (status-ok forecasts of 2026-03-01) sits beside 179 / 218 / 233; the 175 is never named (no noun, not "Tier A as of 2026-02").
2. HeroKpis (C17): "{passed} of {total} top sellers planned" uses the MASE pass count of all 189 latest Forecast_Result rows as "planned"; "had too little history" includes dead_sku rows.
3. Tooltip labels: ACCURACY_LABELS["typical_product_weighted"] (marts.py:1148-1150) calls the pooled WAPE "Typical product, weighted by sales", and the MAPE line calls the MAPE "(typical product)" (RangeCards.jsx:529): two measures, one name.
4. GET /dashboard `forecast_accuracy` vs GET /dashboard/accuracy: same code; the Dashboard route resolves its range with the page scope (dashboard.py:2480), so under `principal=all` its window may differ from the SKU page's (UNVERIFIED; one-line side finding).
5. No report export or separate Forecast Accuracy page exists in frontend/src; scripts/smoke_api.py checks no accuracy figure.

## B. Documentation

How this was made: read-only, tracked files only (`git ls-files`), `git grep`/`grep`/Read. No database was opened. The working tree has
STATE.md modified (8 added lines, 19-25, the "SIX METRICS" entry), and those lines were read as they are on disk. Searched: every
tracked *.md/*.json/*.txt/*.csv/*.svg under docs/ and reports/, and the root *.md files, for MAE, RMSE, MAPE, WAPE, MASE, R²/r_squared
with a number. Not counted: thresholds (MASE < 1, MAPE < 20%, "MAPE=15.0 fallback" as a bug description), R1/R2 rule and round labels,
column names with no value.

Verdict key (column "Agrees?"): **yes** = same measure, population and window as the pinned set, value equal to the precision shown;
**no** = same measure, population and window, value differs; **n.a.-measure** = a different measure (named); **n.a.-window** /
**n.a.-population** = the pinned measure on a window or population the pinned set does not cover. **STALE** = current tense, no longer true.

Pinned-set shorthand: CW = card window Mar 2025-Feb 2026, FS = full span Jan 2024-Feb 2026; all / fc (forecastable) / plan (order plan).

---

### A. STATE.md (current-state file; every line listed)

| file:line | metric | value | population | window, source run | tense | names pop.? | Agrees? | note |
|---|---|---|---|---|---|---|---|---|
| STATE.md:22-23 | R² | -0.03 (median, in-window) | fc, common set 161 | CW, run 21 | dated recon 2026-11-17 | yes | n.a.-measure (in-window/hindsight R², benchmark = product's own window mean) | The only place -0.03 is quoted in the tracked tree. Labelled correctly: "the in-window reading is not reported". Not quoted as current anywhere else (git grep). |
| STATE.md:23 | R² | 0.27 (out-of-sample) | fc, 161 | CW, run 21 | dated recon 2026-11-17 | yes | yes (0.272, 161) | |
| STATE.md:23 | R² | 0.43 vs last month's sales | fc, 161 | CW, run 21 | dated recon | yes | n.a.-measure (naive benchmark, not expanding mean) | |
| STATE.md:25 | WAPE / MAPE / MAPE | 31.95% / 233; 32.42% / 179; 27.21% / 100 | all / fc / plan | CW, run 21 | dated recon (calibration) | yes | yes, yes, yes | The only tracked place the pinned card-window figures appear besides DEPLOY row 6. MAE/RMSE/R²/MASE of the pinned set appear nowhere in tracked docs (searched 3,898 / 11,551 / 0.299 / 0.718 / 48.32 / 0.868: no hit). |
| STATE.md:63 | WAPE pesos / pooled WAPE / MAPE fc (variant) / MAPE all; near-zero MAE, RMSE | 8.5 / 32.0 / 32.4 (31.8) / 38.7; MAE 4,280, RMSE 10,696 | 233 / 233 / 179 / 218; 39 near-zero | CW, on ssm_rehearsal after March | dated recon 2026-11-17 | partly (counts in parentheses, not on each figure) | 32.0 yes; 32.4 yes; 38.7 yes; 8.5 n.a.-measure (company pesos); 31.8 n.a.-measure (stock-limited variant); MAE/RMSE n.a.-measure (near-zero 39 only) | Copy, not live; says the values equal live's. |
| STATE.md:64 | MAPE | 28.7% over 105 of 131 | Apr 2026 plan (copy LP run 11) | CW, copy | dated recon | yes | n.a.-population (a plan that exists only on the copy) | |
| STATE.md:85-87 | WAPE per category | COOKING AIDS 31.79->31.61% ... ORAL CARE 37.17->37.15 | per category | CW, live | dated 2026-11-17 | yes | n.a.-measure (per-category pooled WAPE) | |
| STATE.md:88 | WAPE pesos / pooled | 8.5% and 32.0% (were 9% and 32%) | card | CW | dated 2026-11-17 | no (233 not named on this line) | 32.0 yes; 8.5 n.a.-measure | Old rounded "9%/32%" quoted explicitly as the old display. |
| STATE.md:97 | pooled WAPE | 32.04% -> 31.95% | 2,052 product-months | CW | dated 2026-11-17 | yes (product-months) | 31.95 yes; 32.04 = old pre-clipping value, labelled as before | |
| STATE.md:98 | pooled WAPE | 36.53->36.33% (Sep 2025-Feb 2026); 27.25->27.24% (2024-01..2025-08) | card | other card ranges | dated | yes (product-months) | n.a.-window | |
| STATE.md:112-115 | MAPE planned line | 27.2% over 100 of 115 (mean 30.7%); 32.4% over 179; Sep-Feb 27.2% / 100; 2024-01..2025-08 29.1% / 87 | plan / fc | CW and two other ranges | dated 2026-11-16, current-tense for CW | yes | CW: yes, yes; other two n.a.-window | |
| STATE.md:116 | (populations) | 233 WAPE, 218 MAPE | | CW | current | yes | consistent with pin | |
| STATE.md:145 | pooled WAPE | 31.85% (procedure), 31.93% "live", 33.39% none | calendar panel without the treatments re-applied | 2025-03..2026-02 | dated recon 2026-11-16 | no | n.a.-measure (panel approximation of live; the panel multiplies before succession/fading) | **Collision**: "live 31.93%" on the same window where the card/pin says 31.95%; the text does not say why they differ. |
| STATE.md:155-156 | MAPE all / stock-limited variant | 38.7 / 40.7 / 37.9; 36.7 / 39.8 / 33.6 | all that sold (218 on CW) | CW / Sep-Feb / 2024-01..2025-08 | current (applied 2026-11-15) | no (populations not on the line) | CW 38.7 yes; others n.a.-window; variant n.a.-measure | |
| STATE.md:157 | MAPE (old card) | 34.0% / 35.2% / 32.8% | | 3 ranges | quoted as gone | no | old, superseded, labelled as such | |
| STATE.md:159-161 | MAPE floors | 37.4 / 36.5 / 36.9; 36.5/35.0/33.2; 35.5/33.6/29.9 | card rows | 3 ranges | dated | no | n.a.-measure (oracle floor) | |
| STATE.md:166 | MAPE mean / median | 1,057% / 38.7% | 218 | CW | dated 2026-11-15 | partly | median yes; mean n.a. (pin has no all-product mean) | |
| STATE.md:169 | near-zero MAE/RMSE; MAPE fc | MAE 4,280, RMSE 10,696 (39 products, 368 months); fc mean 51.7%, median 32.4% | near-zero 39 / fc 179 | CW | current | yes | MAPE fc yes (32.42, mean 51.66); MAE/RMSE n.a.-measure (near-zero only, raw net actuals) | |
| STATE.md:170 | MAPE planned / variant | mean 30.7%, median 27.2%; 31.8% | plan / fc | CW | current | partly | 27.2 yes (mean 30.71 yes); 31.8 n.a.-measure | |
| STATE.md:173 | MAPE floor fc | 32.0 / 32.5 / 27.0 | fc | 3 ranges | dated | no | n.a.-measure | |
| STATE.md:211 | WAPE pesos / pooled / MAPE | "shows 8.52 / 32.04 / 34.0% on Mar 2025 - Feb 2026" | card on the March copy | CW | dated 2026-11-13 | no | **no / old card figures** (32.04 pre-clipping; 34.0 = MAPE basis retired 2026-11-15) | Points to "Every figure: docs/DEPLOY_AND_TEST_2026-11-13.md section 3", which now carries 8.5 / 32.0 / 32.4 / 38.7: the pointer and the figures disagree. |
| STATE.md:228-231 | pooled WAPE, MASE (backtest) | 38.07->37.15, 27.86->27.53; MASE 0.731->0.674, 0.901->0.869; grain+Dec 36.33%, 27.24%, MASE 0.646, 0.869 | all products in the as-served frame | Sep 2025-Feb 2026 / 2024-01..2025-08 | dated 2026-11-12/13 | no | n.a.-window (backtest MASE on the pinned definition but other windows) | |
| STATE.md:242 | MASE pass | 115 of 175 (110 before) | Forecast_Result 2026-03 | stored holdout | current ("ON LIVE NOW") | yes | n.a.-measure (stored holdout); equals the pinned 115 | |
| STATE.md:278-283 | pooled WAPE deltas, MAPE pts, MASE | e.g. both -1.72 [-3.50,-0.14]; MASE 0.731->0.652, 0.901->0.876 | rehearsal copy ssm_spike | Sep-Feb / 2024-01..2025-08 | dated, refused change | yes | n.a.-window | |
| STATE.md:288-289 | WAPE pesos / pooled | 8.18%; 36.12% vs 36.35%; 12.96%->8.18%, cap 10.97% | ssm_spike | Sep-Feb | dated | partly | n.a.-window | |
| STATE.md:296 | MAPE (holdout) | 17 of 170 under 20%, median 39.6% | "live forecast" own 80/20 holdout | lp_run 9 era forecast | dated 2026-11-12 but phrased "Live forecast" | yes (170) | n.a.-measure (holdout MAPE) | **STALE**: the live forecast changed 2026-11-13; and 170 vs the 175 ok products is not explained (UNVERIFIED). |
| STATE.md:341 | pooled WAPE deltas; MASE | -3.47 pts, -2.63; MASE 0.776->0.731 / 0.888->0.871; MASE<1 109->110 | as-served frame | 2 windows | dated 2026-11-10 | partly | n.a.-window | |
| STATE.md:345 | MASE pass; WAPE deltas | "Calendar factor OFF: MASE<1 101 of 175 (ON 109, the pin)"; +3.05, +0.60 pts | stored / challenger | | dated 2026-11-10 | yes | n.a.-measure | "the pin" 109 was true then; the pin is now 115. |
| STATE.md:346 | WAPE, MAPE, MASE | -2.21 pts...; MAPE 26.7%->44.5%, MASE 0.714->0.752 | as-served frame | Mar-Aug 2025 vs Sep 2025-Feb 2026 | dated 2026-11-10 | no | n.a.-window | |
| STATE.md:347 | pooled WAPE, MASE | -3.5 [-7.3,-1.3], -2.6; MASE 0.776->0.731 / 0.888->0.871 | | 2 windows | dated | partly | n.a.-window | |
| STATE.md:348 | WAPE | S1 38.1% at 1 month, 26.6% at 2, 19.7% at 3; 40.8% pesos vs 37.9% pieces; ~12% totals; 10.77% vs 37.88% | S1, as-served frame | main window | dated 2026-11-10 | no | n.a.-window/measure | |
| STATE.md:349 | WAPE pesos / pooled; MASE | card CW 10.07->10.29%, 35.22->32.28%; 2023-10..2026-02 12.24->10.91%, 32.51->29.73%; MASE 110 of 175, median 0.823 | card (run 11 -> run 16) | CW / whole window | dated 2026-11-10 | no | old card figures (run 16, pre-grain, pre-clip) | Dated entry; correct for its date. |
| STATE.md:384 | WAPE pesos / pooled | "A range ending Feb 2026 still shows 10.29% and 32.28% (run 16 since 2026-11-10...)"; 11% and 37%, "Error 36.1%" | card | CW | **present tense ("still shows")** | no | **no — STALE** (card now 8.5% / 32.0% on run 21) | |
| STATE.md:415 | MASE pass | "Headline: MASE < 1 for 109 of 175" | Forecast_Result 2026-03 | stored holdout | **present tense, under "Pinned (published) figures"** | yes | n.a.-measure, but **disagrees with the pin it claims to quote (115 / 0.755)** — **STALE** | The JSON it points to holds 115. |
| STATE.md:422 | MASE count | "109 = 109 for 2026-03" | plan vs forecasts | | dated 2026-10-31 closure | yes | n.a.-measure | Dated. |

### B. CLAUDE.md, ARCHITECTURE.md, KNOWN_ISSUES.md, docs/LIMITATIONS.md, other root *.md

| file:line | metric | value | population | window, source | tense | names pop.? | Agrees? | note |
|---|---|---|---|---|---|---|---|---|
| CLAUDE.md (whole) | none | no accuracy value stated | | | | | n.a. | :144 "MAPE=15.0 fallbacks" is a description of a fixed bug, not a figure. :153 sends readers to docs/ACCURACY_AS_SERVED.md as "Accuracy figures to quote", which carries none of the pinned card-window figures, no MAPE, MAE, RMSE or R² (section C). |
| ARCHITECTURE.md:93 (DEC-23) | MASE | SARIMA mean 4.72, median 1.29; 37.1% under 1 | 89 SARIMA-comparable SKUs | 6-month walk-forward, 2026-08 | dated evidence | yes | n.a.-measure (bake-off) | |
| ARCHITECTURE.md:96 (DEC-26) | WAPE (median, short bin) | 0.265 -> 0.430 with a synthetic prefix | TSB short bin | experiment | dated evidence | yes | n.a.-measure | |
| ARCHITECTURE.md:111 (DEC-41) | median product WAPE | 0.318 -> 0.305 / 0.304 | params.py comment | "not re-measured 2026-11-02" | dated, marked unmeasured | no | n.a.-measure | |
| ARCHITECTURE.md:111 (DEC-41) | pooled WAPE | 38.07% -> 36.33% (Sep 2025-Feb 2026), 27.86% -> 27.24% (2024-01..2025-08) | as-served frame | backtest | dated record of the decision | no | n.a.-window | |
| ARCHITECTURE.md:116 (DEC-46) | MAPE/MASE shares | ~15% clear MAPE<20%; 50-56% clear MASE<1 | bake-off | 2026-09 | dated | partly | n.a.-measure | |
| ARCHITECTURE.md:116 (DEC-46) | MASE pass | "**109 of the 175 `ok` forecasts pass for cycle 2026-03 and are the plan**" | Forecast_Result 2026-03 | stored | **present tense** | yes | n.a.-measure, **STALE** (live and pin: 115 of 175; the plan is 115 rows) | STATE.md:105 says DEC-42/DEC-45's "109 / 435,988" were fixed on 2026-11-17; DEC-46's 109 was missed. |
| KNOWN_ISSUES.md:45 (A12) | MASE pass | "MASE 109 of 175 (a different 109)" | stored | 2026-10-30 | dated (STATE.md:107 keeps A12 as a dated record) | yes | n.a.-measure | |
| KNOWN_ISSUES.md:63 (P5b) | MASE count | "2026-03 = 109 against 109" | | 2026-10-31 | dated closure | yes | n.a.-measure | Today 115 = 115 (not re-read here). |
| KNOWN_ISSUES.md:61 (Q-row 9) | (provenance) | ACCURACY_AS_SERVED code version | | | dated | | n.a. | Side finding: the doc's line 3 now cites 941fadb "(uncommitted changes in ...)", the same class of problem row 9 closed. |
| docs/LIMITATIONS.md:37 | (window) | "The as-served backtest window is closed (2024-01..2026-02)" | | | current | | n.a. | No figure; window label conflicts with ACCURACY_AS_SERVED's "2023-10 to 2026-02" (section H). |
| README.md, BACKEND_GUIDE.md, COVERAGE_MAP.md, Context-from-the-data-side.md, DATABASE_ARCHITECTURE.md, ROADMAP.md, SUPABASE_SETUP.md | none | 0 accuracy figures | | | | | n.a. | BACKEND_GUIDE:257,375 name the retired 20% MAPE gate only (dated-record banner added 2026-11-17 per STATE.md:57). |

### C. docs/ACCURACY_AS_SERVED.md (the file CLAUDE.md says to quote)

Header: computed 2026-11-12 from 941fadb "(uncommitted changes in: M analytics/forecasting/calendar.py, M analytics/params.py, M scripts/run_baseline_forecast.py)"; actuals-2026-02-b31bf58d9b5e. Window "2023-10 to 2026-02", Tier A the month before each test month.

| file:line | metric | value | population | window, source | tense | names pop.? | Agrees? | note |
|---|---|---|---|---|---|---|---|---|
| :13 | median product WAPE / pooled WAPE / total WAPE pesos | 38.55% / 30.12% / 10.02% | 310 products, 4,370 product-months | 2023-10..2026-02, as served no calendar (= run 20) | current ("quote these") | yes | n.a.-measure (run 20, no calendar factor) | |
| :14 | median / pooled / pesos | 36.37% / **28.87%** / 8.70% | 310 / 4,370 | same window, calendar-adjusted (= run 21) | current | yes | pooled **yes** (FS all 28.87%); median n.a.-measure (36.37%); pesos n.a.-measure (8.7%) | Window label says 2023-10, the pin says Jan 2024 (section H). |
| :20 | MASE pass / median | 115 of 175 (65.7%), median 0.755 | Tier A 2026-02, status ok | stored holdout | current | yes | n.a.-measure (stored holdout), equals the pinned 115 / 0.755 | |
| :32-35 | WAPE pooled per route; MASE per route; MA3 columns | e.g. all routes 34.43% / MA3 37.70%; median MASE 0.755 / 0.912; short 39.88%, medium 57.49%, long 32.89% | 175 products, 965 holdout product-months | last 20% of each series | current | yes | n.a.-measure (holdout WAPE, not the backtest) | **Collision risk**: a third "pooled WAPE" (34.43%) for "the forecast", beside 28.87% and the card's 32.0%, distinguished only by the table heading. |
| :43-46 | median MASE / median product WAPE by min-history | 0.755/31.31%, 0.768/31.54%, 0.697/28.42% | 175 / 141 / 98 | holdout | current | yes | n.a.-measure | |
| :58-59 | median / pooled / pesos | run 5: 38.72 / 31.86 / 10.27; run 7: 38.28 / 31.36 / 11.08 | 300 / 3,989 | stored runs 5, 7 | dated (explained as superseded) | yes | n.a.-measure | |
| :67-70 | median / pooled / pesos | 38.66/30.61/9.95; 38.55/30.12/10.02; 39.03/30.15/10.14; 36.45/28.89/8.66 | 310 / 4,370 | sensitivities | current | yes | n.a.-measure (raw-net sensitivity 28.89 vs headline 28.87) | |
| :77 | median product WAPE | MA3 39.37% | 310 | same | current | yes | n.a.-measure | |
| (absent) | MAPE, MAE, RMSE, R², backtest MASE, card window | not in the file | | | | | | The file to quote does not hold the pinned card-window set or any pinned MAPE/MAE/RMSE/R²/backtest-MASE figure. |

### D. docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.md and .json

| file:line | metric | value | population | window, source | tense | names pop.? | Agrees? | note |
|---|---|---|---|---|---|---|---|---|
| .md:16-17 | MASE pass / median | **110 of 175 (62.9%), median 0.823** | Forecast_Result 2026-03 | stored | **current ("Figures pinned")** | yes | n.a.-measure, **STALE / contradicts its own JSON** (JSON :49-51: 115, 0.755) | Last re-pinned text is 2026-11-10. |
| .md:18 | median product WAPE | 38.55% / **37.88%** | 310 | as served / calendar | current | partly | 38.55 n.a.-measure; 37.88 **STALE** (JSON :38 = 36.37%) | |
| .md:19 | pooled WAPE | 30.12% / **29.69%** | 310 / 4,370 | as served / calendar | current | partly | 30.12 n.a.-measure (run 20); **29.69 = no, STALE** (pinned FS all = 28.87%, JSON :39 = 0.28866) | The human-readable pin and the machine pin disagree on the headline. |
| .md:20 | total WAPE pesos | 10.02% / **10.77%** | | | current | partly | n.a.-measure; 10.77 STALE (JSON 8.70%) | |
| .md:37 | pooled WAPE | 32.46% today, 31.97-33.66% after March; monthly 17.0-69.8% | Tier A decomposition basis, run 11 | 2026-10-24 | dated (the md says the table "still describes run 11") | partly | n.a.-measure (run 11) | |
| .md:40 | MASE | "MASE 109 of 175, median 0.827 ... stored ... unchanged" | stored | 2026-10-24 | dated table, but row says "unchanged" | yes | n.a.-measure; stale | |
| .json:29-31 | median / pooled / pesos | 0.38552 / 0.30124 / 0.10016 | 310 / 4,370 | as_served (run 20) | pinned | yes | n.a.-measure | |
| .json:38-40 | median / pooled / pesos | 0.36373 / **0.28866** / 0.08704 | 310 / 4,370 | as_served_calendar (run 21) | pinned | yes | pooled **yes** (the published headline); median, pesos n.a.-measure | |
| .json:48-51 | MASE | 115 of 175, 0.6571, median 0.755 | stored | 2026-03-01 | pinned | yes | n.a.-measure, equals the pin | |
| .json:96-100 | (verbatim copies of ACCURACY_AS_SERVED sections) | same as section C | | | | | as section C | |
| docs/published_snapshot_2026-10-24/mase_rows.csv | MASE per product | 175 rows (product_key, status, mase) | | | data | | n.a. (per product) | |

### E. docs/DEPLOY_AND_TEST_2026-11-13.md (the deploy sheet; describes what users see)

| file:line | metric | value | population | window, source | tense | names pop.? | Agrees? | note |
|---|---|---|---|---|---|---|---|---|
| :79 row 6 | company-total WAPE (pesos) | 8.5% | "all 233 scored products" | CW, live 2026-11-17 | current | yes | n.a.-measure (company total pesos; matches the 8.5% it is listed as) | |
| :79 row 6 | pooled product WAPE (pieces) | 32.0% | same 233 | CW | current | yes | **yes** (31.95%) | |
| :79 row 6 | MAPE fc / variant | 32.4% (31.8% leaving out stock-limited) | 179 | CW | current | yes | 32.4 **yes**; 31.8 n.a.-measure | |
| :79 row 6 | MAPE all | 38.7% | 218 that sold | CW | current | yes | **yes** (38.70%, 218) | |
| :79 row 6 | MAE / RMSE | 4,280 / 10,696 | 39 near-zero only | CW | current | yes | n.a.-measure (near-zero, raw net) | Pinned all-product MAE 3,898.1 / RMSE 11,551.3 are not on the card or in this sheet. |
| :79 row 6 | MASE pass / median | 115 of 175, median 0.76 | latest forecast | stored, "not this range" | current | yes | n.a.-measure, equals the stored pin (0.755) | Labelled as not this range: good. |
| :79 row 6 | MAPE plan line | 27.2% over 100 of 115 (vs 32.4% over 179) | plan | CW | current | yes | **yes** (27.21%, 100) | |
| :79 row 6 (after March) | all of the above; plan line 28.7% over 105 of 131 | | copy | CW | expected values | yes | as above; 28.7 n.a.-population (copy's plan) | Notes "until 2026-11-17 the two WAPEs showed 9% and 32%": old display, labelled. |

### F. docs/CHAPTER4_MOVED_FIGURES_2026-11-11.md (named in the brief; every accuracy figure)

| file:line | metric | value | population | window, source | tense | names pop.? | Agrees? | note |
|---|---|---|---|---|---|---|---|---|
| :73 | pooled WAPE; MASE | "headline pooled WAPE 30.12%, MASE below 1 for 110 of 175 (median 0.823)"; "the card's company-total and pooled WAPE" (no value) | | 2026-11-11 | dated section 3 | no | 30.12 n.a.-measure (run 20, no calendar); MASE stale for today | **Labels 30.12% (no-calendar run) "headline"**; the published headline is the calendar run's 28.87% (JSON as_served_calendar). |
| :117-126 (figure i) | monthly WAPE % | 2025-03 20.3 / 18.7 ... 2026-02 35.2 / 33.8 | Tier A monthly pooled | printed vs lp_run 8 / 9 | dated table | no | n.a.-measure (monthly pooled WAPE) | Live values since moved again (FIGURES.md:207-218 gives 21.6 ... 32.0). |
| :148-149 (figure k) | MASE pass / median | printed 109 / 0.827; live 110 / 0.823 | stored | 2026-11-11 | dated | yes | n.a.-measure | 109 / 0.827 is the held manuscript figure. |
| :215-217 | pooled WAPE, MASE | 38.07->37.15 [-1.57,-0.34]; 27.86->27.53; MASE 0.731->0.674, 0.901->0.869; 36.33% / 27.24% | as-served frame | Sep 2025-Feb 2026 / 2024-01..2025-08 | dated | no | n.a.-window | |
| :230 | MASE pass / median | 110/0.823 -> **115 of 175 / 0.755** | Tier A 2026-02 | stored | after = current | yes | n.a.-measure, equals pin | |
| :236 | company / pooled WAPE | 13.30% / 38.27% -> **7.22% / 36.53%** | 208 products, 1,078 product-months | card Sep 2025-Feb 2026 | "After" column, presented as live | yes | n.a.-window; **36.53 is pre-clipping (now 36.33%, STATE.md:98)** — STALE | |
| :237 | MAPE (Ch3 basis) | 41.0% -> **40.7%** | 192 | Sep-Feb | after | yes | n.a.-window | |
| :238 | MAPE stock-limited | 35.2% -> **39.8%** | 189 / 149 months | Sep-Feb | after | yes | n.a.-measure | |
| :240 | company / pooled | 10.23% / 27.88% -> **9.07% / 27.25%** | 270, 3,292 pm | 2024-01..2025-08 | after | yes | n.a.-window; 27.25 pre-clipping (now 27.24%) | |
| :241-242 | MAPE / variant | 34.6% -> **37.9%** (255); 32.8% -> **33.6%** | | 2024-01..2025-08 | after | yes | n.a.-window / n.a.-measure | |
| :244 | company / pooled / MAPE all | 10.29 / 32.28 / 38.2 -> **8.52% / 32.04% / 38.7%** | 233 (MAPE 218) | **CW** | after, presented as live | yes | 38.7 **yes**; **32.04 = no (pre-clipping; pin 31.95%) — STALE**; 8.52 n.a.-measure | Section 9.1 (:275) repeats "pooled 32.04% / 36.53% / 27.25%" as unchanged on live (2026-11-15): stale since 2026-11-17. |
| :245 | MAPE stock-limited | 34.0% -> **36.7%** | 217 | CW | after | yes | n.a.-measure | |
| :246 | products at 50%+ MAPE | 73/76 -> 63/74 | 183 / 237 | as-served frame | after | yes | n.a.-measure | |
| :247-248 | pooled WAPE; backtest median MASE | 36.33% [-3.43,-0.19] / 27.24%; MASE **0.646** / **0.869** | as-served frame | Sep-Feb / 2024-01..2025-08 | after | partly | n.a.-window (pinned-definition MASE, other windows) | 0.869 (2024-01..2025-08) sits next to the pinned FS 0.868 (Jan 2024-Feb 2026): near-identical numbers, different windows; easy to conflate. |
| :249 | pooled WAPE planned | 32.63%/28.47% -> **31.07% / 27.82%** | lp_run 9's 110 planned | Sep-Feb / earlier | after | yes | n.a.-population (lp_run 9's plan, not lp_run 10's) | |
| :250 | median / pooled / pesos | 37.88/29.69/10.77 -> **36.37% / 28.87% / 8.70%** | whole window | calendar run | after | partly ("whole window") | 28.87 **yes**; others n.a.-measure | |
| :251 | median / pooled / pesos | 38.55 / 30.12 / 10.02 | | no-calendar run | current | no | n.a.-measure | |
| :275 | company / pooled | "WAPE (company 8.52% / 7.22% / 9.07%, pooled 32.04% / 36.53% / 27.25%) ... are the same on live" | card | 3 ranges | present tense, 2026-11-15 | no | **pooled 32.04 = no; STALE** (pin 31.95; 36.33; 27.24 since 2026-11-17) | |
| :279 | MAPE | 34.0/35.2/32.8 -> **38.7 / 40.7 / 37.9** | | 3 ranges | after | no | CW 38.7 **yes**; others n.a.-window | |
| :280-283 | MAPE variant; floors; WAPE floor | 36.7/39.8/33.6; 37.4/36.5/36.9; 36.5/35.5, 35.0/33.6, 33.2/29.9; WAPE floor 34.53% / 26.79% | | 3 ranges | after | partly | n.a.-measure | |
| :289 | MAPE mean / median | 1,057% / 38.7% | 218 | CW | dated 2026-11-15 | yes | median **yes** | |
| :295 | MAPE mean / median | 1057.1% / 38.7% | all 218 | CW | dated | yes | median **yes** | |
| :297 | MAPE mean / median; MAE/RMSE | 51.7% / 32.4%; near-zero MAE 4280, RMSE 10696 | fc 179; 39 flagged | CW | dated | yes | MAPE **yes** (mean 51.66 yes); MAE/RMSE n.a.-measure | |
| :301 | MAPE mean / median; MAE/RMSE | 30.7% / 27.2%; flagged MAE 6870, RMSE 15994 | planned 100 (14 flagged) | CW | dated | yes | MAPE **yes**; MAE/RMSE n.a.-measure | :320 defines "planned" as 116 products (115 plan rows + legacy row 4), the pin as 115; same 100 scored, so no number differs. |
| :296, 298-300, 302-318 | MAPE mean/median; flagged MAE/RMSE | 18 sensitivity rows (2%/10% thresholds; Sep-Feb; 2024-01..2025-08) | | | dated | yes | n.a.-measure / n.a.-window | e.g. :313 2024-01..2025-08 fc 29.9% (201). |
| :322 | pooled WAPE; MAPE | launch handover: CW 32.00% -> 32.26%; median MAPE 38.7% -> 40.6%; Sep-Feb 36.43% -> 38.17%; 2024-01..2025-08 27.25% -> 30.30% | card rows | 3 ranges | dated test | partly | **baseline 32.00% matches neither the card then (32.04%) nor now (31.95%)**; Sep-Feb 36.43 matches neither 36.53 nor 36.33 — UNVERIFIED why | |
| :102-116, 127-147, 159-175 | forecasts, surplus/shortage, plan, policy | not accuracy metrics | | | | | n.a. | |

### G. Other docs/ files

| file:line | metric | value | population | window, source | tense | names pop.? | Agrees? | note |
|---|---|---|---|---|---|---|---|---|
| docs/CALENDAR_SELECTION_2026-11-16.md:11 | pooled WAPE | 31.85% procedure / **31.93% live** / 33.39% none | panel, identical product-months | 2025-03..2026-02 | dated recon | no | n.a.-measure (panel approximation; :84 says the panel multiplies before the treatments) | Same collision as STATE.md:145. |
| docs/CALENDAR_SELECTION_2026-11-16.md:17-36, 56-72 | held-out WAPE per fold, shrink grid, December WAPE (51.0/52.4/43.8; 57.1/50.2/42.9), 30.13->29.66, ceiling 26.83/31.13/29.65 | ~40 values | panel | folds T1-T3 | dated | partly | n.a.-window | |
| docs/CALENDAR_SELECTION_2026-11-16.md:84 | pooled WAPE | 28.88% against 28.87% stored | 4,370 pm | 2024-01..2026-02 | dated | yes | **yes** (28.87 stored = pin) | Here the 4,370 frame is labelled 2024-01..2026-02 (cf. section H). |
| docs/CALENDAR_SELECTION_PROTOCOL_2026-11-16.md | none (measure definitions only) | 0 | | | | | n.a. | |
| docs/CHALLENGER_FORECAST.md:60 | MASE pass | 109 of 175 (median 0.827; "equals the stored and pinned 109"); challenger 101 / 0.902 | stored protocol | 2026-11-10 | dated | yes | n.a.-measure; "pinned 109" stale today | |
| docs/CHALLENGER_FORECAST.md:61-67, 82, 114-123 | pooled / median WAPE, MASE | 41.74/42.45 (Sep-Feb), 37.49/38.76; 32.51/32.96 (2023-10..2026-02), 43.27/40.77; MASE 0.854 vs 0.819; turn table | served (run 11 era) vs challenger | 2026-11-10 | dated | yes | n.a.-window / superseded run | 32.51% is the run-11 card's whole-window pooled WAPE. |
| docs/COVERAGE_MATRIX.md:34-35, 50 | MASE pass | 109 pass, 66 fail; "109 SKUs in lp_run 4" | Forecast_Result 2026-10-20 | generated 2026-10-21 | dated (header) | yes | n.a.-measure | |
| docs/CHALLENGER_SELECTION_RULE.md, DEMO_DATA.md, TEST_PLAN.md | none | 0 values (definitions, gate text) | | | | | n.a. | |

### H. reports/: individually listed (current-tense, panel-facing, or generated now)

| file:line | metric | value | population | window, source | tense | names pop.? | Agrees? | note |
|---|---|---|---|---|---|---|---|---|
| reports/CALENDAR_GRAIN_2026-11-12.md:26 | WAPE (average) | 32.341% vs 32.343% | selection score | 2 windows averaged | dated | no | n.a.-measure | "For: the panel and the adviser". |
| reports/CALENDAR_GRAIN_2026-11-12.md:37-40 | pooled WAPE; median MASE | 38.07->36.33% (208), 27.86->27.24% (270); MASE 0.731->0.646 (192), 0.901->0.869 (188) | as-served frame | Sep-Feb / Jan 2024-Aug 2025 | "Status: LIVE" | yes | n.a.-window | |
| reports/CALENDAR_GRAIN_2026-11-12.md:41 | company WAPE (card) | 7.22% / 9.07% | 208 / 270 | card ranges | presented as live | yes | n.a.-measure | |
| reports/CALENDAR_GRAIN_2026-11-12.md:42 | pooled WAPE (card) | **36.53% / 27.25%** | 208 / 270 | Sep-Feb / earlier | presented as live | yes | n.a.-window; **pre-clipping, STALE** (36.33 / 27.24) | **Two "pooled WAPE" for the same 208 products and window, 36.33% (:37) and 36.53% (:42), with no word on why** (scoring rule: raw net vs net-negative = 0). Since 2026-11-17 both rules give 36.33%. |
| reports/CALENDAR_GRAIN_2026-11-12.md:43 | MAPE median (card) | **35.2% / 32.8%** | 183 / 237 | card ranges | presented as live | yes | n.a.-window; **STALE**: the basis was retired 2026-11-15 (now 40.7% / 37.9% headline, 39.8% / 33.6% variant) | |
| reports/CALENDAR_GRAIN_2026-11-12.md:44-46 | MAPE counts; WAPE planned; MASE pass | 31/34 of 183; 31.07%/27.82% (107/90); 110 -> 115 of 175 | | | live | yes | 115 equals the stored pin; others n.a. | |
| reports/figures/FIGURES.md:86, 160 | MASE pass / median | caption: "pinned figure 'MASE < 1 for 109 of 175'"; ":86 ...109 passed..., median MASE of 0.827" | stored | generated 2026-11-13 (6987c27) | generated, current-tense caption | yes | n.a.-measure; **caption STALE**: :163-164 in the same file say the data gives 115 / 0.755 | Chapter 4 figure output (manuscript-adjacent). |
| reports/figures/FIGURES.md:179 | median product WAPE | "about 40%" | per product | Mar 2025-Feb 2026 | caption | no | n.a.-measure | **Same file, same window, :204 says 35.49%** for the median product WAPE. |
| reports/figures/FIGURES.md:204 | median product WAPE | 35.49% "for this window, a different measure" | per product | Mar 2025-Feb 2026 | caption | partly | n.a.-measure | Captions still name the frozen snapshot CSVs as source; STATE.md:42 says h-k read live since 2026-11-17, but FIGURES.md was not regenerated (last commit 2026-11-13). |
| reports/figures/FIGURES.md:207-218 | monthly WAPE % | data 21.6, 21.6, 23.3, 37.2, 40.5, 32.6, 26.4, 40.1, 32.7, 44.6, 43.6, 32.0 vs Table 4.2.18 | Tier A monthly pooled | 2025-03..2026-02 | "Disagrees" lines (held) | no | n.a.-measure (monthly) | 2026-02 "32.0" is a monthly figure and coincides with the card's 12-month 32.0%: unrelated. |
| reports/AUDIT_2026-10-23.md:44 | WAPE; MASE | 35.2% pooled (233, CW) vs 32.46% (310, 2023-10..2026-02); MASE 109 of 175 | | 2026-10-23 | dated audit | yes | n.a. (old runs) | Already flags "two WAPEs a panel can ..." |
| reports/experiments/error_hunt_2026-11-10/results_ranked.md:1 | pooled WAPE; MASE | "S1 (served since 2026-11-10): main all 38.07 / MASE 0.731; earlier all 27.86 / **0.871**" | as-served frame | 2025-09..2026-02 / 2024-01..2025-08 | dated, "served since" now stale | yes | n.a.-window | **Same served forecast, same earlier window, CALENDAR_GRAIN:40 / STATE.md:230 give its MASE as 0.901**; product set or scale must differ (UNVERIFIED). |

### I. Historical folders and dated records under reports/ (one row per file or folder)

| file / folder | figures (approx.) | verdict |
|---|---|---|
| reports/experiment_log.csv | 1,396 rows (median/pooled WAPE, sMAPE, MASE, mase_pass_pct) | dated record of the 2026-09-02..09-22 bake-offs/routing searches, Tier A 2026-02 `single` cohorts: n.a.-measure |
| reports/experiment_log_README.md | 0 values (column definitions) | n.a. |
| reports/MA3_METRIC_RECONCILIATION.md | ~55 (MA3 MASE medians 0.795/0.838, pass shares 56.3%, 62-64%) | dated 2026-09-06, 89/119/129-SKU sets: n.a.-measure |
| reports/PRODUCTION_MODEL_DECISION.md | ~40 (MAE/RMSE win counts, MAPE means 1.70, MASE pass shares) | dated 2026-09-06, 89 SKUs rolling origin: n.a.-measure. Its MAE/RMSE are win counts, not pieces |
| reports/BAKEOFF_8020_PROTOCOL.md | ~40 | dated 2026-09-06, 80/20 single split: n.a.-measure |
| reports/MODEL_BAKEOFF_UNILEVER.md (+ model_bakeoff_*.csv, arima_/xgboost_bakeoff_*.csv, bakeoff_8020_per_sku_*.csv, model_decision_per_sku_2026-09.csv, ma3_vs_sba_a3_per_sku_2026-09.csv) | ~25 in the md; per-SKU MAE/RMSE/MAPE/MASE/sMAPE columns in 13 CSVs | dated 2026-09-01 bake-off (Table 4.2.13's source; 89 evaluable products): n.a.-measure (bake-off MASE) |
| reports/SEASONALITY_AND_BASELINES.md, ADVISER_EVIDENCE.md, DEMAND_DIAGNOSIS.md, FULL_DATA_AUDIT.md, baseline_bakeoff_vs_sarima.csv, audit_E1_full_136.csv, ma3_per_sku_tierA.csv | ~40 (SARIMA MASE 1.285, MAPE 59.4; MA3 0.795/0.838) | dated 2026-08, SARIMA era, 136/129/89 sets: n.a.-measure (PROJECT_STATE_2026-09.md:152-153 already marks them superseded) |
| reports/ADVISER_QUESTIONS_SIRCG.md | 4 (best MAPE ~33%, 13-15% under 20%, 67 of ~89 MASE<1, 19 under MAPE) | dated 2026-09 question, n.a.-measure |
| reports/PROJECT_STATE_2026-09.md | ~8 (:1136 at-the-time median 34.56%, pooled 29.63%, pesos 9.82%; :1283 "Jan 2024 - Feb 2026" 36.3%/9.5% -> 39.0%/10.7%) | dated, at-the-time cohort: n.a.-population. :1283 uses the label "Jan 2024 - Feb 2026" for a different population and run than the pinned FS |
| reports/PROJECT_DIAGNOSIS_2026-09-21.md | ~6 (46 of 119 MASE>=1; holdout WAPE 1.1623 vs 0.8648; MASE 1.47) | dated 2026-09-21: n.a. |
| reports/MANUSCRIPT_HANDOFF_2026-09-21.md | 2 ("MAPE above 1,000%") | out of scope: manuscript/chapter briefing |
| reports/BASELINE_FORECAST_RUN.md, LP_READINESS.md, GRAIN_DECISION.md, IMPLEMENTATION_PLAN_2026-09.md, DISPATCH_MESSAGES_2026-09.md, BINNING_ROUND1_2026-09.md, SYNTHETIC_DATA_AUDIT.md, CHART_DESIGN_PLAN, COLUMN_GAP_AUDIT, FORECASTING_METHOD_RECOMMENDATION, API_CONTRACTS.md (:117 example r_squared 0.41, a draft spec), DASHBOARD_RECON.md | ~45 in all | dated 2026-08/09: n.a. API_CONTRACTS' 0.41 is an illustrative payload, not a measurement |
| reports/AUDIT_360_2026-10-20.md | 2 (:141 "107 of the ok products ... MASE below 1"; :692 "+7.6% on orders") | dated 2026-10-20: n.a.-measure |
| reports/LP_CLIENT_ALIGNMENT_PLAN_2026-09-29.md, MONTHLY_BATCH_REHEARSAL_2026-11-02.md, QA_PIPELINE_2026-10-30.md, TRACKED_PERPRODUCT_FILES_2026-10-22.md | counts of gated SKUs (73, 19) or column names only | dated: n.a. |
| reports/diagnostics/model_audit_2026-10-03/ (README + 20 CSVs) | ~40 in README (34.8% / 35.9% at-the-time, 26.9% / 28.0%, pooled 29.6% / 30.2%, per-bin, per-month) | dated record 2026-10-03, at-the-time cohort (337 products, 3,503 pm) and 107-product cohort: n.a.-measure ("34.8%/35.9%" set, as the brief names it). Not quoted as current anywhere outside this folder (git grep) |
| reports/diagnostics/forecast_error_business_2026-10-03/ (README, CSVs, run_log.txt r_squared 0.376 / 0.017, cv_vs_wape.svg "r²", qc files) | ~35 (median WAPE 26.9%/29.3%, totals 8.3-10.7%) | dated 2026-10-03, 107 products, 29 months: n.a.-measure. The r² here is a CV-vs-WAPE correlation, not forecast R² |
| reports/diagnostics/lp_logic_check_2026-10-03/, surplus_bias_experiment_2026-10-03/, tier_a_refresh_2026-10-05/ (headline_at_the_time.csv), tier_a_basis_2026-10-03/, safety_stock_source_2026-10-05/, fit_diagnosis_2026-10/, fit_diagnosis_2026-10-07/, project_health_2026-09-24.csv, README.md, UNFIT_SKU_LIST.md, WHY_SOME_SKUS_ARE_UNFIT.md, speed_baseline_* | ~120 (per-SKU MASE 1.135-2.32, fit thresholds 0.9/1.1, at-the-time headlines) | dated records 2026-09-23..10-07, 132-SKU `single` cohort: n.a. |
| reports/experiments/error_hunt_2026-11-10/ (README, results_*.csv/json, results_ranked.md except :1 above) | ~600 rows | dated 2026-11-10, as-served frame on ssm_challenger, two windows, lp_run 7's 110 planned: n.a.-window |
| reports/experiments/error_reduction_2026-11-10/ (README + 6 CSV/JSON) | ~650 rows (README: MAPE 2,197% -> 1,625% etc.) | dated 2026-11-10: n.a.-window |
| reports/experiments/forecastability_2026-11-10/, horse_race_2026-11-10/ (results_error_rise.json: MAPE 26.7%->44.5%, MASE 0.714->0.752) | ~450 rows | dated 2026-11-10: n.a.-window |
| reports/experiments/target_transforms_2026-09-26/, differencing_phase2_2026-09-26/ | ~1,800 rows | personal experiments 2026-09-26 (local branch): n.a. |
| reports/experiment_artifacts/ (cells_*.csv, routing_*_per_sku_model.csv, gate_d_*.csv, synthetic_arms_*) | ~9,500 rows | dated 2026-09-21/22 search artefacts: n.a. |
| reports/evidence/ (ch01-ch10 json/csv, PREREGISTERED.csv, PREREG/RESULT_cutoff12.md: TSB 76.4%, average 73.0% MASE<1) | ~700 rows | dated chart evidence 2026-09: n.a. ("ch" = chart, not chapter) |
| reports/simulation/synthetic_2026-10/ (summary.md median MASE 0.685/0.712; examples.md per-product MASE) | ~10 | labelled simulation, never an accuracy claim: n.a. |
| reports/lp_runs, reports/diagnostics/lp_rerun_* logs | 1 | dated: n.a. |

### J. Out of scope (manuscript / chapter drafts; counted, not inventoried)

| file | metric figures |
|---|---|
| docs/CH4-5_EDITS_2026-10-22.md | 0 (one "MASE (forecast error score)" label) |
| docs/CH4-5_EDITS_2026-10-22_corrected.md | ~10 (:321 pooled WAPE 32.94% / 32.49%, pooled MAPE 1,054.98% / 1,078.89%, worst month 7,091% / 8,292%, withdrawn 459.55% / 29.35%; :344 109 / 0.827) |
| docs/MANUSCRIPT_CORRECTIONS_2026-10-22.md | 3 (:86 109 of 175, 62.3%, 0.827) |
| docs/MANUSCRIPT_WORKED_CALCULATIONS.md | 1 (:88 one product's MASE 0.429) |
| docs/MANUSCRIPT_TABLE_DATA_2026-10-30.md, docs/CHAPTER4_CODE_FIGURES.json | 0 |
| reports/MANUSCRIPT_HANDOFF_2026-09-21.md | 2 |
| docs/MANUSCRIPT_HELD_CHECKS.json | excluded by the brief (72 held statements) |

### K. Flags

**1. Stale current-tense claims (should change when the pinned set is committed)**
- STATE.md:415 "Headline: MASE < 1 for 109 of 175" under "Pinned (published) figures": the pin is 115 / 0.755.
- ARCHITECTURE.md:116 (DEC-46) "109 of the 175 ok forecasts pass for cycle 2026-03 and are the plan": live 115, plan 115.
- docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.md:16-20: 110 / 0.823, calendar 37.88% / 29.69% / 10.77%; its own JSON says 115 / 0.755, 36.37% / 28.87% / 8.70%. The human-readable pin is two re-pins behind.
- STATE.md:384 "A range ending Feb 2026 still shows 10.29% and 32.28%": the card shows 8.5% / 32.0%.
- docs/CHAPTER4_MOVED_FIGURES_2026-11-11.md:244 and :275 (pooled 32.04% / 36.53% / 27.25% "the same on live") and :236, :240: pre-clipping card values; now 31.95% / 36.33% / 27.24%.
- reports/CALENDAR_GRAIN_2026-11-12.md:42-43 (status "LIVE", for the panel): card pooled 36.53% / 27.25% (pre-clipping) and card MAPE 35.2% / 32.8% (basis retired 2026-11-15).
- reports/figures/FIGURES.md:160 caption "pinned figure 'MASE < 1 for 109 of 175'" (the same file's :163 says the data gives 115).
- STATE.md:296 "Live forecast ... 17 of 170 under 20%, median 39.6%": the forecast of lp_run 9's day; 170 vs 175 unexplained.
- STATE.md:211 "shows 8.52 / 32.04 / 34.0%" with "Every figure: docs/DEPLOY_AND_TEST_2026-11-13.md section 3", which now gives 8.5 / 32.0 / 32.4 / 38.7.

**2. Same measure name, different population or window, not said in the text**
- "Pooled WAPE" for the forecast takes four values in the doc set without a shared label: 28.87% (FS, ACCURACY_AS_SERVED headline / JSON), 31.95-32.0% (CW, card / DEPLOY row 6), 34.43% (ACCURACY_AS_SERVED:35, the holdout last 20% of 175 products), 30.12% (run 20, called "headline" in CHAPTER4_MOVED:73). The documents name their windows, but CHAPTER4_MOVED:73 calls the no-calendar 30.12% "headline pooled WAPE" while the published headline is the calendar run's 28.866%.
- CALENDAR_GRAIN:37 vs :42: 36.33% and 36.53% for the same 208 products and window, both "pooled WAPE", the scoring-rule difference not stated.
- STATE.md:145 and CALENDAR_SELECTION:11 call 31.93% "live" on 2025-03..2026-02; the card/pin give 31.95% for that window (panel approximation, not said).
- Median product WAPE on Mar 2025-Feb 2026: "about 40%" (FIGURES.md:179) and 35.49% (FIGURES.md:204) in the same file.
- Backtest MASE, earlier window 2024-01..2025-08, the served forecast before the grain change: 0.871 (error_hunt results_ranked.md:1, STATE.md:341/347 "0.888->0.871") vs 0.901 (CALENDAR_GRAIN:40, STATE.md:230, CHAPTER4_MOVED:216). UNVERIFIED whether the product set (188?) or the scale differs.
- Backtest MASE 0.869 (2024-01..2025-08, CALENDAR_GRAIN:40, CHAPTER4_MOVED:216/248) sits next to the pinned FS MASE 0.868 (Jan 2024-Feb 2026): different windows, nearly the same number.
- CHAPTER4_MOVED:322 baselines 32.00% (CW) and 36.43% (Sep-Feb) match no card value of any date (32.04 / 31.95; 36.53 / 36.33). UNVERIFIED.
- "Planned" population: CHAPTER4_MOVED:320 = 116 products (115 + legacy row 4); the pin = 115 plan products. Same 100 scored, so no figure differs.

**3. Window label of the 4,370-row as-served frame**
- "2023-10 to 2026-02": ACCURACY_AS_SERVED.md:7, the run label quoted in the brief, CHALLENGER_FORECAST:66, AUDIT_2026-10-23:44.
- "2024-01..2026-02" / "Jan 2024-Feb 2026": docs/LIMITATIONS.md:37, CALENDAR_SELECTION:7/84, error_hunt README:9, and the pinned set's "Full span".
- STATE.md:247 explains that the backtest runs from 2023-10 and the decomposition from 2024-01, but both labels are attached to the same 310 products / 4,370 product-months. Which months the 4,370 actually cover is UNVERIFIED from the docs (settled by `SELECT min(month), max(month), count(*) FROM mart.accuracy_mart WHERE run = 21`, read-only).

**4. Old card figures still quoted:** 32.04% (STATE.md:97 and :211, CHAPTER4_MOVED:244/:275); "9%/32%" (STATE.md:88, DEPLOY:79, both labelled as the old display); 34.0% / 35.2% / 32.8% MAPE (STATE.md:157 labelled as gone; CALENDAR_GRAIN:43 not labelled); 10.29% / 32.28% (STATE.md:349 dated, :384 present tense).

**5. R² "-0.03":** quoted once, STATE.md:23 (working-tree lines, uncommitted), as the in-window/hindsight reading, explicitly "not reported". Not quoted as current anywhere. The other "-0.03" hits (PRODUCTION_MODEL_DECISION:271, error_hunt README:54, results_ranked:6/16) are WAPE/MASE differences, not R².

**6. Missing from the docs a reader is sent to:** none of the pinned MAE (3,898.1 / 3,881.6 / 3,351.5; 4,020.5 / 4,108.9 / 4,169.4), RMSE, R², backtest MASE (0.718 / 0.722 / 0.626; 0.868 / 0.943 / 0.822), full-span MAPE (48.32 / 36.62 / 28.96) or the full-span fc/plan WAPEs (26.90 / 27.52) appear in any tracked doc. ACCURACY_AS_SERVED.md (the doc CLAUDE.md:153 says to quote) holds only the FS pooled WAPE 28.87% and the stored MASE 115 / 0.755 from the pinned set.

**7. Frontend (not a doc, checked because users read it):** `git grep` of frontend/src for metric names next to a number found only code comments and format code (RangeCards.jsx:294, SKUForecast.jsx:1178/1535/3128, labels.js:33/127, Charts.jsx:2624/2645). The card's figures come from the API, so nothing on the pages hardcodes an accuracy value. Not checked: backend response text strings.
