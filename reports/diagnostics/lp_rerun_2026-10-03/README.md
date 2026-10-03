# LP rerun: March 2026 order plan at 103%, from the opening stock count (2026-10-03)

The order plan for cycle 2026-03 (March 2026) was solved again, this time from the stock count that **opens** March:
Unilever's count for February 2026, taken **2 March 2026**. The previous plan (30 September 2026, allocation 105%) had
used the latest count, taken **6 April 2026**. That is the stock left after March's sales, so the old plan counted
March's demand twice (`reports/diagnostics/lp_logic_check_2026-10-03/README.md`, issue 1; DEC-32 in `ARCHITECTURE.md`).

**Terms.** LP = linear programming, the order optimizer (`scripts/run_lp.py`). Need = forecast + target stock − stock
on hand, never below 0. Short = need − order, when the supplier allocation can't fund the whole need. Allocation 103% =
the planned products' 2025 sales in pieces × 103% ÷ 12, per month. SS = safety stock. Class A (Tier A) is **as of
2026-02** (ABC method `single`, 132 Unilever products). Pesos are at the stock file's last purchase price per piece
(`unit_cost_per_case` ÷ pack size, `run_lp`'s own cost), the same price for both runs. They are cost, not sales value.

## What was done (2026-10-03, UTC)

| step | result |
|---|---|
| Code | `b8d934b` (stock-timing fix) merged into `kelvin-etl` as `e6991b5` |
| Tests on the merged tree, live database + `data/raw` | 1,247 passed, 10 skipped (9 need a fills scratch schema, 1 "fix later"), 0 failed. Frontend `npm run build` exit 0 |
| Old rows saved first, read-only | `before_30sep_105pct.csv`: the 74 rows of cycle 2026-03 (73 pending + 1 accepted). `decided_by` (an account email) is left out; the backup keeps it |
| Backup, read-only | `backups/full_backup_20261003T080251Z` in the shared folder (gitignored): `public`, 29 tables, 289,512 rows, every file re-checked against the database, RESULT PASS |
| Migration 0039 | applied 08:07:48 by the runner (`run_canonical_load --schema public --target-public --schema-only`); only 0039 was pending |
| LP run | `python scripts/run_lp.py --allocation-pct 103` at 08:08:41: **`lp_run` row 1**, 73 rows refreshed, 0 decided rows changed, no rows deleted. Log: `run_lp_2026-03_103pct.log` |
| API, read-only | `scripts/smoke_api.py`: 13 of 13 routes PASS on the live data |

## Migration 0039: every stock count records the month it opens

| check (`Inventory_Fact`, after the apply) | expected | result |
|---|---|---|
| `demand_period` filled, all equal to `_period` + 1 | 60,873 | 60,873; 0 differ |
| `days_offset` filled (Unilever rows only) | 39,177 | 39,177 (27,282 real + 11,895 generated); Del Monte 0 of 21,696 |
| real Unilever `days_offset`: 1 / 2 / 3 / 6 days | 17,338 / 5,506 / 3,653 / 785 rows | same |
| trigger `trg_inventory_fact_count_month` | present, enabled | present, enabled |

**Trigger test** (one transaction, rolled back). It inserted a Unilever row (period 2026-02, counted 2026-03-02) and a
Del Monte row, both passing the wrong values 'WRONG' / 999. The trigger set them to `2026-03` / 2 days and `2026-01` /
NULL. Changing the Unilever row's `_period` to 2026-01 gave `2026-02` / 30 days. After the rollback the table still held
60,873 rows and no test rows.

**Spot check: five real Unilever counts against the date in their own workbook.** An SSIS file's count date is the
date in its stock sheet's name (`analytics/etl/extract/ssis_soh.py:100`).

| period | workbook sheet | date in the sheet name | stored count date | `demand_period` | `days_offset` | rows |
|---|---|---|---|---|---|---|
| 2023-06 | `SOH(JULY 3, 2023)` | 2023-07-03 | 2023-07-03 | 2023-07 | 3 | 793 |
| 2025-12 | `SOH(JANUARY 05, 2025)` | 2025-01-05 | **2026-01-01** | 2026-01 | 1 | 775 |
| 2026-01 | `SOH(FEBRUARY 03, 2026)` | 2026-02-03 | 2026-02-03 | 2026-02 | 3 | 747 |
| 2026-02 | `SOH(MARCH 02, 2026)` | 2026-03-02 | 2026-03-02 | 2026-03 | 2 | 812 |
| 2026-03 | `SOH(APRIL 06, 2026)` | 2026-04-06 | 2026-04-06 | 2026-04 | 6 | 785 |

Four of five match the workbook. The December 2025 sheet names a date 11 months before its own month ends. The
loader's date guard (rule R4, `ssis_soh.py:266-283`) therefore stored month end + 1 day, 2026-01-01. That count's date
is derived, not the file's own. The year is probably a typo for 5 January 2026 (UNVERIFIED). It doesn't affect this
plan.

## The two plans side by side (cycle 2026-03, Unilever, 73 products)

| measure | 30 Sep 2026 plan, 105% | **3 Oct 2026 plan, 103%** |
|---|---|---|
| stock count used | period 2026-03, **counted 6 Apr 2026** (the latest count; that run predates `lp_run`, so this is from the code it ran, `STOCK_AT_LATEST_SQL`) | period 2026-02, **counted 2 Mar 2026** (recorded in `lp_run` 1) |
| `lp_run` id | none (its 73 rows had `lp_run_key` NULL) | **1** (code `e6991b5`); all 73 pending rows carry it |
| products planned | 73 | 73 |
| stock on hand, 73 products (pieces) | 759,258 | 2,093,786 |
| total need (pieces) | 1,255,471 | 325,468 |
| monthly allocation ceiling (pieces) | 1,216,540 (binds) | 1,193,368 (does not bind) |
| **total order (pieces)** | **1,216,540** | **325,468** |
| **total order (₱, at cost)** | **₱14,007,128** | **₱6,964,217** |
| **short: products / pieces** | **40 / 38,931** | **0 / 0** |
| products ordering 0 (already above target) | 6 | 31 |
| **Class A below SS, as the dashboard card reads it** (latest count, 6 Apr 2026) | **35 of 70** | **35 of 70** |
| Class A below SS against the opening count (2 Mar 2026) | 6 of 72 | 6 of 72 |
| safety stock / target stock, 73 products (pieces) | 485,541 / 884,856 | same; 0.0 difference on every product |

How to read it:
- **Only the stock and the allocation changed.** Safety stock and target stock are identical for every product
  (largest difference 0.0 pieces). They come from the forecast and the sales history, not from stock on hand.
- **Order:** 55 products order less, 15 order more, 3 are unchanged.
- **The 30 Sep plan was capped by its allocation.** It ordered exactly its 105% ceiling (1,216,540 pieces), so 40
  products ended short. On the 2 March count the need is 325,468 pieces, under the 103% ceiling, so nothing is short.
- **Class A below SS is the same in both columns** because safety stock didn't change and the card measures stock,
  not the order. The dashboard card stays on the latest count (6 Apr 2026, decision 2 of 2026-10-03), so it still reads
  35 of 70. Against the 2 March count it is 6 of 72. The comparable totals differ (70 vs 72) because 3 products are
  missing from the 6 April count and 1 from the 2 March one; the dashboard excludes a product with no stock row.
- **The Reorder page now judges each row against the 2 March count:** 7 critical (below safety stock), 5 urgent
  (below target), 61 planned. Read from `GET /recommendations` after the run.
- Short and need for the 30 Sep plan were recomputed from its stored orders and targets, the cycle's forecasts
  (`Forecast_Result`, last written 2026-09-21 10:08, before both runs) and the 6 April count. A product missing from a
  Unilever count is 0 on hand, as `run_lp` reads it.

**Read the 3 Oct plan with these notes** (recorded in `lp_run` 1, `inputs.notes`):
1. The 2 March 2026 count is about twice the counts either side (`backend/data_notes.py`). It is **accepted for
   planning, pending SSM confirmation** (decided 2026-10-03). Unilever has no receipt records, so the stock balance
   can't confirm it or rule it out (`lp_logic_check_2026-10-03` §5).
2. Stock counts are from the Ilocos Sur warehouse workbook; per-product sales are La Union only. Whether the two
   territories match is UNVERIFIED.

**Untouched rows.**
- The accepted row: MASTER CLEANSER ANT-ACNE/PIMPLE 144X70ML (20292811), 1,331.24 pieces, accepted
  2026-08-24 05:49. It is still accepted, still generated 2026-08-23 08:43, and its `lp_run_key` is still NULL.
- 179 pending rows in 33 older cycles (2023-05 to 2026-02) stay as they were. The app withholds them, as before.
- One product is not in the 2 March count, so it is planned as 0 on hand: KNORR SIN ORIG+SINORIG 48(6+1)X11G
  (64971078), order 6,821 pieces. Unilever's count lists no zero-stock items.

## Files

| file | contents |
|---|---|
| `before_30sep_105pct.csv` | the 74 rows of cycle 2026-03 before the rerun (read-only export), product name first |
| `plan_2026-03_103pct.csv` | `run_lp --csv`: per product forecast, stock used and its count date, safety stock, target, need, order, short, cost per piece |
| `run_lp_2026-03_103pct.log` | the run's log |
| `comparison_per_product.csv` / `comparison_totals.json` | the side-by-side table above, per product and in total |
| `compare_runs.py` | builds the comparison from the two CSVs plus read-only queries |
| `verify_0039.py` | `pre` / `post` checks for migration 0039 (read-only) and `trigger-test` (rolled back) |

Reproduce from the repository root: `python reports/diagnostics/lp_rerun_2026-10-03/verify_0039.py post` and
`python reports/diagnostics/lp_rerun_2026-10-03/compare_runs.py`. Both read the live database, so they differ after any
later load or LP run.
