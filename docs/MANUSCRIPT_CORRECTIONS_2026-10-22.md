# Manuscript corrections, Chapters 4 and 5 (2026-10-22)

How to read the "Basis" column: **Computed** = I ran a query or a command today and the figure is in this repo or the database. **Given** = the value comes from the fact-check list in the task; I could reproduce it where the Why column says so, otherwise I could not check it because the draft and the fact-check file (`local/FACTCHECK_Ch4-5_2026-10-22.md`) are not in the repo. **Needs draft** = the "current value in draft" is not available to me; fill it in from the manuscript.

Plan figures below are the current plan as GET /recommendations serves it (cycle 2026-03, Unilever, `lp_run` 5), measured by `local/measure_plan_2026-10-22.py` on both the join path and the planning mart (they agree). Before = 110 rows, After = 109 rows.

## 1. Corrections

| # | Section / table | Current value in draft | Corrected value | Why | Basis |
|---|---|---|---|---|---|
| 1 | Order plan: rows (Tables 4.2.19 to 4.2.21 scope) | 110 | **109** | Row 4 (SKIN CARE, Tier C, accepted 24 Aug 2026, no LP run, no current forecast) was counted. A decided row is plan only when an LP run produced it. The row is still in the table, only excluded from the plan reads. | Computed |
| 2 | Products ordering | 74 | **73** | Same row; it ordered 1,331.24 pieces. | Computed |
| 3 | Total pieces ordered | 432,774 | **431,443** (431,443.01 stored) | 432,774.25 less 1,331.24. Matches the LP's own printout (`need 431,443 / order 431,443`). | Computed |
| 4 | Total safety stock | 557,617 (110 rows) | **557,612** (557,611.70 stored, 109 rows) | 557,617.36 less 5.66. **557,612 belongs to the 109-row current plan and to the LP run's own total; 557,617 belongs to the 110-row set that included the orphan.** Use 557,612 everywhere in the plan tables. | Computed |
| 5 | Plan by urgency: CRITICAL | 19 | **18** | The orphan was CRITICAL. URGENT stays 5, PLANNED stays 86. | Computed |
| 6 | Plan by tier | A 109, C 1 | **A 109** | The Tier C row was the orphan. "Tier A, forecast ok, MASE < 1" tables are now true for every counted row. | Computed |
| 7 | Plan by category (rows) | SKIN CARE 1 | **SKIN CARE 0 (row removed)** | Orphan was the only SKIN CARE row. Others unchanged: FABRIC CLEANING 25, HAIR CARE 28, FABRIC ENHANCERS 8, DEODORANTS & FRAGRANCES 14, COOKING AIDS 19, ORAL CARE 4, CONDIMENTS 7, SKIN CLEANSING 4 (sum 109). | Computed |
| 8 | Plan by status | 109 pending, 1 accepted | **109 pending, 0 accepted** | Same row. | Computed |
| 9 | Rounding note under the order tables | none | Add: "Quantities are stored to two decimals and shown rounded to whole pieces; a column total is the rounded sum of the unrounded rows, so it can differ by 1 from the sum of the displayed rows." Measured: orders 431,443.01 (rows rounded to nearest also sum to 431,443); safety stock 557,611.70 shows as 557,612 while the same rows rounded one by one sum to 557,611 in Python or 557,612 in SQL. Rounding every row **up** would add 37 to 57 pieces (orders 431,480; safety stock 557,669), so tables built that way would not total to 1. | Computed. I could not check whether the draft's tables round up or to nearest. |
| 10 | "9 of the 12 months" | 9 | **8** | Over-forecast (more pieces over than under) in Tier A, 2025-03 to 2026-02, from `mart.error_decomposition`: June, July, August, September, November, December 2025, January, February 2026 = 8 (in pesos it is 7). The "9" is not reproduced on this window. | Given; 8 reproduced for pieces. Check the draft's window and unit. |
| 11 | Table 4.2.4, year-over-year column (Unilever, net pesos, 2025-03..2026-02 against 2024-03..2025-02) | Column headed or read as "same products" | **It is not.** The published column compares the whole category each year (products added or dropped change it). The matched-product column compares only products with a sales row in both years. Relabel the published column "all products" and add the matched column, or switch to matched. Figures below. | Computed (`local/yoy_table_2026-10-22.txt`, from `mart.sales_mart_real`). The two published and two matched values you gave are reproduced exactly. |
| 12 | Table 4.2.4 values | see table 2 | see table 2 | | Computed |
| 13 | Reference Guide term count | not available | **Not verified** | There is no Reference Guide in the repo (searched frontend, docs, reports). | Needs draft |
| 14 | Route counts | not available | **49 of 59 routes require sign-in; 10 are public** | Walk of the app by `tests/backend/test_permissions.py`: 59 method/path pairs; 10 public (`/health`, `/status`, `/auth/login`, `/auth/login/verify`, `/auth/login/setup`, `/auth/login/setup/confirm`, `/auth/forgot-password` GET and POST, `/auth/set-password`, `/auth/link-info`); 38 need a named permission, 11 need sign-in only. The old pin said 58 (before `/status`). | Computed |
| 15 | Page count | 11 | **10** | `frontend/src/App.jsx` and `Sidebar.jsx`: 9 sidebar pages (Dashboard, SKU Forecast, Category Trends, SKU Management, ABC Classification, Reorder Recommendations, Audit Log, Data Management, User Management) plus the profile page = 10. Counting the admin-only Pending Preview route gives 11; the three sign-in pages (login, forgot password, set password) are separate. State which is meant. | Given; code counts shown, which page was counted as the 11th is not determined |
| 16 | Test counts | 1,694 passed, 8 failed, 18 skipped (before) | **See section 4** | After today's fixes. | Computed |
| 17 | `ACCURACY_AS_SERVED.md` code version to cite | `3cfee40` | **`8ddf82d`** | The document says it was computed from `3cfee40` with uncommitted changes to `scripts/run_baseline_forecast.py`. Those changes are the 3 lines committed in `8ddf82d`, which also holds the document. Cite `8ddf82d`. | Computed (`git show 8ddf82d --stat`) |
| 18 | Revenue shares sum to 100% | 100% | **99.6%** | Unilever, 2025-03..2026-02: the ten named categories (COOKING AIDS 24.7, HAIR CARE 23.1, FABRIC CLEANING 20.4, CONDIMENTS 15.6, DEODORANTS & FRAGRANCES 6.2, FABRIC ENHANCERS 3.6, SKIN CARE 2.5, ORAL CARE 1.9, SKIN CLEANSING 1.3, HOME & HYGIENE 0.5) add to 99.6; OTHER FOODS, UNCLASSIFIED, MINI MEALS, SCRATCH COOKING AIDS and DRESSINGS carry the other 0.4. | Computed. Consistent with the draft only if its table lists those ten; draft not seen. |
| 19 | "203.8 MB" | 203.8 MB | **203.8 MiB** (= 213.7 MB) | 203.8 x 1,048,576 = 213.7 million bytes. The measurement itself is not in the repo. Today's database is 266.3 MiB (not comparable). | Given; unit conversion computed |
| 20 | "Products sold" counts | count of rows | Say what is counted. Unilever, 2025-03..2026-02: **8,735 product-month rows** (524 are zero or negative, 8,211 positive); **1,172 products** have a row, **1,091** have at least one positive month, **1,082** are net positive over the 12 months. | Rows include zero and negative months (returns exceed sales), so a row count overstates products sold. | Computed |
| 21 | Procurement cost default | 25.00, "the median of the planned products" | **33.48**; "median cost per piece (unit cost per case / pack size) of the 101 planned SKUs of cycle 2026-03 that appear in the Feb 2026 stock count; 36.16 over all 109 plan prices. Applied to no product this cycle: all 109 have a stock-file price." | 25.00 was the median for an older 73-SKU cycle (24.55). Changed in `analytics/params.py`; no order changes. | Computed |
| 22 | Warehouse capacity | 3,800,000 pieces, "the most stock held (January 2025)" | **3,816,842 pieces**, "the most stock Unilever's counts show at one time (the 2025-01 count, taken 3 Feb 2025)". State that it is a floor on the true capacity, not a measured limit. | The maximum is 3,816,842. The 2026-02 whole-warehouse count (2 Mar 2026, 3,800,930) already exceeded 3,800,000. The LP applies the limit to the planned products only (2,663,949 pieces of stock plus orders), so it did not bind. | Computed |
| 23 | Claim: "1,991,339 staged rows across all document families, no rejected record" | 1,991,339 | **2,026,061 staged rows, 1,286 sheets, 8 families, 0 rejected at extraction; 6 sheets (1,113 rows) fail their checksum, 1,192 have none** | Saved manifest `staging/_manifest.json` (14 Sep 2026). 1,991,339 is not reproduced. | Computed. Log: `reports/CLAIM_CHECK_2026-10-22.md` |
| 24 | Claim: 53.4-second cold start | 53.4 s | **64.1 s** (one measurement, 4 Oct 2026, after 16 idle minutes) | Only documented cold start (`render_cold.jsonl`). | Computed |
| 25 | Claim: "21 requests", "more than 260 calls" | 21; >260 | Remove, or cite **318 requests, 257 returned 200** from the local speed log | No log supports either number. | Computed |
| 26 | Claim: "9 of 9 tokens refused" | 9 of 9 | **42 of 42**: 7 kinds of invalid token on 6 protected endpoints, all HTTP 401 | Regenerated by running the permission tests. | Computed |
| 27 | Claim: "35 candidates" in the routing test | 35 | **36** candidate models in each of 3 history-length bins (`cells_all.csv`); the 35 is phase 1 of the separate target-transform programme (50 + 35 + 77 = 162) | | Computed |
| 28 | Date dimension (any sentence giving the calendar's range) | ends 2026-12-31 | **ends 2028-12-31** (migration 0065, 731 rows added, 2,191 existing rows unchanged) | Needed so a January 2027 stock sheet's early-January date can be loaded. | Computed |

## 2. Table 4.2.4, year-over-year by category

Unilever net pesos, 2025-03 to 2026-02 against 2024-03 to 2025-02. "All products" is the published basis; "matched" counts only products with a sales row in both years.

| Category | Products 2025-26 | Products 2024-25 | Matched | As published (all products) | Matched products |
|---|---|---|---|---|---|
| COOKING AIDS | 73 | 50 | 50 | +22.1% | **+1.5%** |
| HAIR CARE | 211 | 195 | 140 | -0.9% | -9.4% |
| FABRIC CLEANING | 216 | 184 | 137 | -8.3% | **-10.6%** |
| CONDIMENTS | 90 | 65 | 64 | +13.5% | +7.6% |
| DEODORANTS & FRAGRANCES | 124 | 100 | 85 | -4.2% | +4.2% |
| FABRIC ENHANCERS | 86 | 46 | 42 | -4.5% | -55.1% |
| SKIN CARE | 130 | 119 | 100 | +9.7% | +11.6% |
| ORAL CARE | 46 | 30 | 25 | -6.2% | -19.6% |
| SKIN CLEANSING | 63 | 52 | 49 | +16.2% | +12.1% |
| HOME & HYGIENE | 27 | 24 | 22 | +0.4% | -3.6% |
| OTHER FOODS | 2 | 2 | 2 | +25.8% | +25.8% |
| UNCLASSIFIED | 87 | 119 | 53 | -25.3% | -23.0% |
| MINI MEALS | 1 | 1 | 1 | +339.6% | +339.6% |
| SCRATCH COOKING AIDS | 3 | 17 | 3 | -100.0% | -100.6% |
| DRESSINGS | 13 | 38 | 13 | -100.1% | -100.5% |

The last two rows are products that stopped selling and one with negative net sales; they are not meaningful growth rates. The size of the gap between the two columns (FABRIC ENHANCERS: 86 products this year against 46 last year) is the reason the "same products" label is wrong for the published column.

## 3. Figures that did NOT change

| Figure | Value | How I know |
|---|---|---|
| Order quantity, safety stock and target stock of each of the 109 products | identical | Dry-run of `scripts.run_lp` before and after the Part C changes: 0 of 109 rows differ in order, safety stock or target stock. |
| Total pieces to order | 431,443 | Same dry run, both before and after (the 432,774 on the 110-row page was the orphan being added in). |
| Per-product forecasts, MASE, ABC tiers (Tier A as of 2026-02: 189 products on `t12m_new`) | unchanged | No forecast, ABC or segmentation code or data was touched. |
| As-served accuracy in `docs/ACCURACY_AS_SERVED.md` (109 of 175 with MASE < 1, 62.3%, median MASE 0.827; per-route table) | unchanged | Document not regenerated; only the version to cite changes (row 17). |
| URGENT 5 and PLANNED 86 in the plan by urgency; all category row counts except SKIN CARE | unchanged | Before/after measurement above. |
| Calendar factor | ON | Not touched. |
| Rows in every fact table | unchanged | Only `date_dimension` gained rows (migration 0065). Backup `backups/tables_20261022T120255Z` (`date_dimension`, `schema_migrations`, row counts verified). |

## 4. Test counts

| | Passed | Failed | Skipped |
|---|---|---|---|
| Before (this session, `python -m pytest tests`) | 1,694 | 8 | 18 |
| After | 1,704 | 1 (the unfixed real defect) | 18 |

The 8 failures before: 5 stale pins or test doubles (route count 58 to 59; two parameters unpinned; a patched function that now takes a second argument; two segmentation tests missing a patch for `_fetch_total_periods`) and 3 database-contract tests. Of those 3: `test_marts` (stale test, the Pareto SQL gained a `{sales_mart}` placeholder) and `test_planning_mart` (stale harness, the endpoint now adds its period labels after the mart read) were fixed; `test_abc_schema_contract` is a **real defect** (the ORM model lacks the live column `added_as_new`) and was left unfixed.
