# SIMULATION — real + 2021–22 placeholder data; not served, not used in the LP or in accuracy claims

**Scope.** Del Monte has no product-level sales, so it is not forecast. Product-level simulation and fit diagnosis are Unilever-only; Del Monte gets the category-level and coverage view.

Read-only run, 2026-10-02 (`run_simulation.py` beside this file). Nothing here is served, written to `forecast_result`, used by the LP, or usable as an accuracy claim: the 2021-22 rows are placeholder data (`is_demo = true`) standing in for files SSM has not delivered.

## A. Unilever - Tier A as of 2026-02 (132 SKUs)

| check | result |
|---|---|
| REAL run reproduces live `forecast_result` (2026-03-01): status, method, forecast_value | 132/132 |
| REAL run reproduces stored MASE (`ok` rows) | 119/119 |

Placeholder rows used: 2021-01..2022-12 only, for 40 of the 132 SKUs (the 2026-03..08 gap rows are excluded). Same router and settings in both runs. Both runs are scored on the same months and the same scale: common window 2025-09..2026-02 for 107 SKUs, the stored 20% split for 12 short-bin SKUs the common window cannot score; MASE scale always from the REAL months. Verdict: fit < 0.9 <= borderline < 1.1 <= not fit (reports/diagnostics/README.md).

| measure | REAL | SIMULATION |
|---|---|---|
| median MASE (119 scored SKUs) | 0.685 | 0.712 |
| fit / borderline / not fit | 79 / 12 / 28 | 80 / 12 / 27 |
| total 2026-03 forecast, units (132 SKUs) | 1,866,259 | 1,852,727 |

| change (REAL -> SIM) | SKUs |
|---|---|
| bin changes | 0 of 132 |
| served model changes | 0 of 132 |
| verdict changes | 2 of 119 |
| MASE better / worse / same (4 dp) | 27 / 44 / 48 |
| status changes (insufficient / ok) | 0 |
| 2026-03 forecast changes (ok SKUs) | 71, median abs change 0.7% |

Bin, REAL (rows) x SIMULATION (columns):

| REAL \ SIM | insufficient | long | medium | short |
|---|---|---|---|---|
| insufficient | 13 | 0 | 0 | 0 |
| long | 0 | 72 | 0 | 0 |
| medium | 0 | 0 | 17 | 0 |
| short | 0 | 0 | 0 | 30 |

Verdict, REAL (rows) x SIMULATION (columns):

| REAL \ SIM | fit | borderline | not fit |
|---|---|---|---|
| fit | 79 | 0 | 0 |
| borderline | 1 | 11 | 0 |
| not fit | 0 | 1 | 27 |

Where the change comes from (scored SKUs, REAL bin x whether the SKU has placeholder rows):

| REAL bin | placeholder rows | SKUs | MASE better / worse / same | median MASE REAL -> SIM |
|---|---|---|---|---|
| long | no | 32 | 6 / 26 / 0 | 0.592 -> 0.608 |
| long | yes | 40 | 21 / 18 / 1 | 0.720 -> 0.750 |
| medium | no | 17 | 0 / 0 / 17 | 1.109 -> 1.109 |
| short | no | 30 | 0 / 0 / 30 | 0.532 -> 0.532 |

**What changes, in one line:** the MASE moves only for SKUs served by XGBoost+MA3 (71 SKUs move, all served by xgb_ma3_avg), because the global XGBoost model trains on every Tier A series, so placeholder rows change it for all long-bin SKUs, including those with no placeholder rows of their own. MA3 and TSB use only the SKU's own history, and none of their SKUs gets placeholder rows, so they are unchanged.

Examples: `examples.md`. Per SKU: `unilever_per_sku.csv`. Per SKU and month, both runs: `series.csv`.

## B. Del Monte - category level, descriptive

No product-level sales exist for Del Monte, so nothing is forecast; this is coverage and category revenue only. Real rows are `is_demo = false`; placeholder rows dated 2021-22 are the only ones added.

| table | real months | real range | + placeholder 2021-22 | placeholder gap months 2023-01..2026-02 (not used) | placeholder 2026-03+ (not used) |
|---|---|---|---|---|---|
| sales_fact | 20 | 2023-01..2025-12 | 24 | 18 | 6 |
| sellout_fact | 17 | 2023-01..2025-12 | 24 | 21 | 6 |
| purchase_fact | 10 | 2023-09..2025-12 | 24 | 27 | 6 |
| salesreturn_fact | 20 | 2023-01..2025-12 | 24 | 0 | 5 |
| inventory_fact | 17 | 2023-01..2025-12 | 24 | 21 | 6 |

**Category revenue shares and ABC tiers** (whole window, SellOut_Fact net_amount, `classify_abc`'s 0.80/0.95 cut points). The live Del Monte ABC is computed one month at a time (method `single`), so adding 2021-22 cannot change any 2023+ period's tier; the whole-window view below is where it shows.

| measure | real only | real + 2021-22 |
|---|---|---|
| categories with positive revenue | 85 | 86 |
| tiers A / B / C | 9 / 21 / 55 | 13 / 22 / 51 |
| top 5 categories (share %) | CULINARY 20.1; BEVERAGE 11.2; FRUITS 9.9; UNCLASSIFIED 9.5; /TIDBITS/BASE 7.9 | /TIDBITS/BASE 11.6; UNCLASSIFIED 10.9; CULINARY 9.9; /TOTAL 100% JUICES/ACE - BASE REGULAR 8.1; /ORIGINAL TOMATO SAUCE/BASE 7.4 |

Categories present only in the placeholder rows: 1. Categories in both whose tier changes: 9. Median absolute share shift: 0.07 percentage points. Excluded for non-positive total revenue: 2 (real) / 2 (with placeholder).

**Month-of-year index** (mean of that month's totals over the years present / mean of all monthly totals):

| source | months real | months with 2021-22 | month-of-year missing in real | peak (real -> with) | trough (real -> with) | largest shift |
|---|---|---|---|---|---|---|
| sales_fact net_amount | 20 | 44 | [7] | 12 -> 12 | 02 -> 02 | 0.07 (month 01) |
| sellout_fact net_amount | 17 | 41 | [7, 10] | 12 -> 12 | 02 -> 10 | 0.82 (month 12) |

**What changes, in one line:** category shares and tiers move (9 tiers change, A 9 -> 13), because 79 of the 80 placeholder categories (99.7% of their revenue) carry pre-2025 category names and 0 carry 2025+ names. Real data has 82 pre-2025 names and 5 from 2025 (0 shared: the January 2025 taxonomy break, still awaiting the adviser's ruling), so whole-window weight shifts toward the old names. The sales-register index barely moves (median shift 0.02): its placeholder rows are real rows resampled from the nearest month-of-year (scripts/build_synthetic_v2_clean_pool.py, dm_sales), so they repeat the real pattern and add no seasonal evidence. The sell-out index moves more (largest shift 0.82, month 12) because sell-out has only 17 real months.

Per category / month: `delmonte_category.csv`.
