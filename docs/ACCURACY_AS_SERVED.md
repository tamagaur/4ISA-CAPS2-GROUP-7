# Forecast accuracy, as served

Computed 2026-11-12 from code version `941fadb` (uncommitted changes in: M analytics/forecasting/calendar.py,  M analytics/params.py,  M scripts/run_baseline_forecast.py) by `scripts/accuracy_as_served.py`. Quote the **as served** rows, and quote them together with this version.

Actuals version `actuals-2026-02-b31bf58d9b5e`: Unilever per-SKU sales through 2026-02, 24,906 rows (analytics/actuals_version.py). A figure here is tied to that data; recompute after a month loads and it is a different figure.

Window 2023-10 to 2026-02, Unilever Tier A the month before each test month (basis `t12m_new`), one month ahead, the router as the live forecast runs it. Latest demand month: 2026-02.

## Headline (quote these)

| Run | Median product WAPE | Pooled WAPE (pieces) | Total WAPE (pesos) | Surplus share of miss (pesos) | Surplus share of miss (pieces) | Products | Product-months |
|---|---|---|---|---|---|---|---|
| **As served** (no calendar factor) | 38.55% | 30.12% | 10.02% | 56.40% | 56.99% | 310 | 4,370 |
| **As served, calendar-adjusted** (the run 7 equivalent) | 36.37% | 28.87% | 8.70% | 52.95% | 53.44% | 310 | 4,370 |

*As served* means: months after a product's last sale are scored (a forecast of 0 against 0 counts); the dead-SKU rule is applied as the live forecast applies it (6 months, positive sales only, returns and blanks are not sales); a net-negative month is 0 in both the history and the actual; a blank-quantity month is not scored. Total WAPE (pesos) is the WAPE of the monthly peso totals over products with a price; surplus share of miss is (over-forecast miss) / (total miss), in the unit named. Median product WAPE is over products whose scored actuals are not all 0 (15 of 310 products have an undefined WAPE in the plain run, 15 in the calendar run).

## MASE pass rate (quote this one number)

**115 of 175** Unilever Tier A products (as of 2026-02, basis `t12m_new`) have MASE < 1 (65.7%); median MASE 0.755. The cohort is 189 products, 175 with status ok; 175 have a defined MASE (0 undefined).

Definition (Hyndman & Koehler 2006, non-seasonal), the same call that writes `Forecast_Result.mase` (`run_baseline_forecast.served_forecasts`): MASE = MAE / scale. MAE is the served model's rolling one-step error over the last 20% of the product's own series (median 6 months, blank-quantity months not scored). The scale is the mean absolute lag-1 difference, mean |y(t) - y(t-1)|, of the first 80% of that series only (in-sample naive, training months). Calendar-adjusted, as the live forecast is served. The gate (MASE < 1, `analytics.params.MASE_GATE`) is unchanged.

Cross-check: `Forecast_Result` for 2026-03-01 stores 115 of 175 for the same cohort. Since the recomputation trains XGBoost on the runner's own pool (2026-11-11), every product's MASE equals the stored one (175 of 175 to three decimals, measured 2026-11-12); the pass count is what to quote. A rolling-origin MASE over the whole as-served window (scale taken before each product's first scored month) is a different protocol with a different count and is not quoted.

## Per route (stored MASE definition)

Same 175 products and the same scored product-months as the MASE figure above (the last 20% of each product's series, rolling one step, calendar-adjusted as served). Route = the bin the router assigns the product today (short / medium / long history). WAPE is pooled over the route's scored product-months: sum |actual - forecast| / sum |actual|. MASE is the median over the route's products, with each product's own scale. The MA3 columns score the plain 3-month moving average on exactly the same rows; it is not calendar-adjusted, so on rows where MA3 is the served model the two differ by the calendar factor alone.

| Route | Served model(s) | Products | Scored product-months | WAPE, selected | WAPE, MA3 | Median MASE, selected | Median MASE, MA3 | MASE < 1, selected | MASE < 1, MA3 |
|---|---|---|---|---|---|---|---|---|---|
| short | ma3 36 | 36 | 68 | 39.88% | 44.46% | 0.738 | 0.707 | 24 of 36 | 22 of 36 |
| medium | tsb 34 | 34 | 137 | 57.49% | 67.22% | 1.056 | 1.186 | 15 of 34 | 11 of 34 |
| long | xgb_ma3_avg 104, ma3 1 | 105 | 760 | 32.89% | 35.75% | 0.733 | 0.904 | 76 of 105 | 63 of 105 |
| all routes | xgb_ma3_avg 104, ma3 37, tsb 34 | 175 | 965 | 34.43% | 37.70% | 0.755 | 0.912 | 115 of 175 | 96 of 175 |

## Minimum-history inclusion

Rule, fixed before the results were read: a product is evaluated only if it has at least N scored months, N = 3, 6 or 12. "Scored months" = the months its MASE is computed over (the table above). The filter reads the month count only; no MASE, WAPE or pass/fail value enters it. The last four columns describe what each threshold removes, to show whether the removal is lopsided.

| Minimum scored months | Included | Excluded | MASE < 1 (included) | Share | Median MASE | Median product WAPE | Excluded: MASE < 1 | Excluded: median MASE | Excluded by route | Excluded: scored months |
|---|---|---|---|---|---|---|---|---|---|---|
| none (unfiltered) | 175 | 0 | 115 of 175 | 65.7% | 0.755 | 31.31% | - | - | - | - |
| >= 3 | 141 | 34 | 91 of 141 | 64.5% | 0.768 | 31.54% | 24 of 34 | 0.699 | short 34 | 1-2 |
| >= 6 | 98 | 77 | 73 of 98 | 74.5% | 0.697 | 28.42% | 42 of 77 | 0.837 | medium 34, short 34, long 9 | 1-5 |
| >= 12 | 0 | 175 | - | - | - | - | all 175 | 0.755 | long 105, short 36, medium 34 | 1-8 |

- N = 3: removes 34 of 175 products by month count alone (routes: short 34); of those, 24 (70.6%) have MASE < 1 and their median MASE is 0.699; the pass rate of the products kept is 64.5% against 65.7% unfiltered.
- N = 6: removes 77 of 175 products by month count alone (routes: medium 34, short 34, long 9); of those, 42 (54.5%) have MASE < 1 and their median MASE is 0.837; the pass rate of the products kept is 74.5% against 65.7% unfiltered.
- N = 12: removes 175 of 175 products by month count alone (routes: long 105, short 36, medium 34); of those, 115 (65.7%) have MASE < 1 and their median MASE is 0.755; no product is left.

The exclusion is by month count only. A threshold that removes products of one route removes them because that route has short holdouts, which is not independent of how they score; read the excluded columns before quoting a filtered figure.

## What the old figure was, and why it moved

| Run | Median product WAPE | Pooled WAPE (pieces) | Total WAPE (pesos) | Surplus share of miss (pesos) | Surplus share of miss (pieces) | Products | Product-months |
|---|---|---|---|---|---|---|---|
| Stored run 5 (`414cd352`), scored as the accuracy mart scores it | 38.72% | 31.86% | 10.27% | 57.35% | 60.06% | 300 | 3,989 |
| Stored run 7 (`34985eb3`), calendar-adjusted, same scoring | 38.28% | 31.36% | 11.08% | 57.82% | 60.62% | 300 | 3,989 |

Run 5 reproduces the 38.72% median quoted before. It predates c0b2727 (net-negative months as 0, positive-sales dead test) and it never scored a month with no sales row, and it applies no dead-SKU rule. It is not a replay of today's serving code.

Where the as-served number comes from, step by step on the same product-months (plain run):

| Run | Median product WAPE | Pooled WAPE (pieces) | Total WAPE (pesos) | Surplus share of miss (pesos) | Surplus share of miss (pieces) | Products | Product-months |
|---|---|---|---|---|---|---|---|
| As served, **dead rule off** (router's own number) | 38.66% | 30.61% | 9.95% | 57.06% | 57.68% | 310 | 4,370 |
| As served (dead rule on) | 38.55% | 30.12% | 10.02% | 56.40% | 56.99% | 310 | 4,370 |
| Sensitivity: as served, scored against **raw net quantity** (returns stay negative) | 39.03% | 30.15% | 10.14% | 56.57% | 57.04% | 310 | 4,370 |
| Sensitivity: as served, **calendar-adjusted**, raw net quantity | 36.45% | 28.89% | 8.66% | 53.14% | 53.49% | 310 | 4,370 |

The dead-SKU rule fired on 90 of 4,370 scored product-months (plain run) and 90 in the calendar run. Product-months not scored: 64 with fewer than 3 sales months (the live forecast serves a provisional average, not a forecast), 11 with a blank actual.

## Limits of these numbers

- The cohort changes every month (Tier A the month before), so the product count is for the whole window, not for Tier A as of 2026-02 (189 products).
- The MA3 benchmark on the same product-months has a median product WAPE of 39.37% (served: plain 38.55%, calendar 36.37%); MA3 is never calendar-adjusted. The served models are not shown to beat MA3 here, and the calendar factor raises the median error on these months.
- Dead-SKU rule: months-with-history gate and window are the live runner's (`DEAD_SKU_MONTHS` = 6); this script does not change them.
- The dashboard card reads these forecasts from `mart.accuracy_mart` (runs stored by `--write-run`), which scores each month against the sales mart's raw net quantity: a net-negative month stays negative there, where this document floors it to 0. Over the full window the card therefore equals the **raw net quantity** sensitivity row above, not the headline row (median, total WAPE in pesos and surplus share in pesos agree to the rounding shown; the card's pooled pieces WAPE divides by net actual pieces, not absolute, so it differs in the second decimal). A shorter date range on the card is a different window.
- Per product-month rows are in the git-ignored `local/accuracy_as_served_rows.csv`.
