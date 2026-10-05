# Tier A on the 12-month basis + full refresh (2026-10-05)

**Decision, PENDING TA CONFIRMATION (DEC-37):** Unilever Tier A = products making 80% of revenue over the last 12 months, plus products first sold within those 12 months that are Class A on the last 3 months. Rule and measurements: `kelvin/tier-a-basis` f753f4e README §7. Del Monte is unchanged (its tiers stay on the single month).

**The basis is a setting:** `analytics/params.py` `TIER_A_BASIS = "t12m_new"`. To switch back, set it to `"single"` and re-run the steps in "What ran" from the forecast step on. The single-month runs are still in the table and still written.

Applied to the live database after backup `backups/full_backup_20261005T061733Z` (PASS). Branch `kelvin/tier-a-12m`, which also merges `kelvin/blank-qty-fix` (e78748c: a blank quantity is a missing month, never 0).

Terms: Tier A / Class A = the top products that together make 80% of revenue. LP = the order optimizer (`scripts/run_lp.py`). MASE = forecast error against a naive forecast; under 1.0 means the forecast beat it, and only those products are planned. WAPE = total absolute error ÷ total actual sales.

## 1. Tier A as of 2026-02, old vs new

| | Old: Feb 2026 alone (`single`) | New: 12 months + new (`t12m_new`) |
|---|---|---|
| Products in Tier A | 132 | **189** (175 on 12 months + 14 added as new) |
| Products classified (any class) | 710 | 1,091 |
| Revenue covered, Feb 2026 (₱28.06M) | ₱22.44M (80.0%) | ₱23.06M (82.2%) |
| Revenue covered, Mar 2025 – Feb 2026 (₱392.66M) | ₱265.86M (67.7%) | **₱318.02M (81.0%)** |
| In both lists / old only / new only | 123 / 9 / 66 | |

Source: `tiers.json` (`measure.py tiers`). Revenue = real sales, a month where returns exceeded sales counted as 0. The 189 and the 14 added products are the same products as the f753f4e report's; the list size also matches that report in all 14 months Jan 2025 – Feb 2026 (checked read-only before any write). `t12m_new` runs exist for 2023-12 to 2026-02 (27 months; earlier months have no full 12-month window).

## 2. Forecast coverage (cycle 2026-03, forecast run 4; run 1 kept)

| Status | Old run 1 (132) | New run 4 (189) |
|---|---|---|
| Forecast served (`ok`) | 119 | **175** |
| … short history, 3-month average | | 36 |
| … medium history, TSB | | 34 |
| … long history, XGBoost + 3-month average | | 104 (+1 long product served by the 3-month average because a guard fired) |
| Under 3 sales months: provisional average, no accuracy score | 13 | 9 |
| Dead (no sale in the last 6 months): 0, no order | 0 | 5 |
| `ok` and MASE under 1.0 (eligible for the LP) | 73 | 97 |

**Gate check:** every product with 3 or more sales months got a forecast, except the 5 dead products, which the existing dead-SKU rule sets to 0. These are the same 5 the f753f4e report §8 listed in advance. 3 of the 189 have a blank-quantity month, now read as missing.

Source: `state_before.json`, `state_after.json`, `plan_and_flags.json`.

## 3. March 2026 plan, run 1 vs run 2 (both at 103%, both from the count of 2 Mar 2026, accepted pending SSM confirmation)

| | `lp_run` 1 (3 Oct, old list) | **`lp_run` 2 (5 Oct, new list)** |
|---|---|---|
| Products planned | 73 | **97** |
| Order, pieces | 325,468 | **356,254** |
| Order, pesos at cost | ₱6,964,217 | **₱7,017,551** |
| Short: products / pieces | 0 / 0 | **0 / 0** |
| Products ordering 0 (already above target) | 31 | 38 |
| Safety stock, pieces | 485,541 | 529,279 |
| Target stock, pieces | 884,856 | 930,602 |
| Stock on hand of the planned products, pieces | 2,093,786 | 2,147,475 |
| Products not in the count (counted as 0) | 1 | 6 |

- 68 products are in both plans, 5 only in run 1, 29 only in run 2.
- The 29 new products order 65,623 pieces (₱1,157,292).
- The 68 common products order 290,631 pieces, against 293,511 in run 1. Their safety stock is unchanged (0 of 68 differ). 50 of their forecasts moved, because the XGBoost model now trains on 189 products instead of 132; 27 orders changed.
- The 5 pending rows of products no longer in the pool were saved and retired (`--retire-stale-pending`), so the cycle holds one plan: 97 pending (run 2) + the 1 accepted row, untouched. The `lp_run` 1 record is kept; its plan is `reports/diagnostics/lp_rerun_2026-10-03/plan_2026-03_103pct.csv`.
- `lp_run` 2's code version reads `bbd8abf…+dirty`: the run was made before the two small fixes in 213e5a3 (search-path guard, segment endpoint) were committed. Neither touches the LP.

Pesos are at cost (stock file unit cost ÷ pack size), not sales value. LP inputs are still the placeholders in `analytics/params.py`, not SSM's figures.

## 4. Review flags (cycle 2026-03)

| | Before (132) | After (189) |
|---|---|---|
| Flagged "review before ordering" | 15 | **51** |
| Not flagged | 104 | 129 |
| Not assessed (under 3 sales months) | 13 | 9 |
| Flagged and in the plan | 7 | 17 |

Of the 51: 29 by the collapse rule, 37 by a 3+ month over-forecast run (15 by both); 5 are the dead products; 36 are products that were not in the old Tier A. The 12-month list keeps fading products for a while (f753f4e §6), and those are the ones the collapse rule catches.

## 5. Accuracy at the time (no look-ahead), new list

Each test month uses the Tier A list of the month before, and a model trained on that list only (same method as stored forecast run 2). `at_the_time.py` → `headline_at_the_time.csv`.

| List | Test months | Products | Product-months | **Median product WAPE** (3-month average) | **Company total WAPE, pesos** | Pooled WAPE, pieces |
|---|---|---|---|---|---|---|
| **New (12 months + new)** | Jan 2024 – Feb 2026 | 302 | 4,121 | **39.0%** (38.7%) | **10.7%** | 32.3% |
| Old (single month), same months | Jan 2024 – Feb 2026 | 324 | 3,157 | 36.3% (37.4%) | 9.5% | 29.5% |
| Old (single month), full window | Oct 2023 – Feb 2026 | 337 | 3,500 | 34.7% (35.9%) | 9.8% | 29.5% |

- **The new list forecasts slightly worse:** 39.0% against 36.3% per product on the same months, and 10.7% against 9.5% at company total. It holds each product longer, including slower and fading ones, so it scores about 30% more product-months.
- On the new list the served models and the plain 3-month average tie (39.0% vs 38.7%).
- The new list's window starts Jan 2024 because its first run is Dec 2023.
- The old list's full-window row is 34.7%, not the 34.8% / 34.6% on record, because this run includes the blank-quantity fix (blank months are skipped, not scored as 0). Stored forecast runs 2 and 3 were not rewritten and still hold the pre-fix forecasts.

## What ran (in order, live `public`)

| Step | Command | Result |
|---|---|---|
| Backup | `scripts.backup_everything` | `full_backup_20261005T061733Z`, PASS |
| Migration 0044 | `run_canonical_load --schema public --target-public --schema-only` | `t12m_new` allowed on 3 tables, `abc_classification.added_as_new` |
| Tier A | `orchestrate_abc --period 2023-12..2026-02 --method t12m_new --principal unilever --schema public` | 27 runs; 2026-02 = 189 Class A |
| Forecasts | `run_baseline_forecast.py --write` | 189 rows, kept as forecast run 4; the 9 old-only rows left `forecast_result` (still in run 1) |
| Segmentation | `orchestrate_segment --schema public --cohort-period 2026-02` (all 6 schemes) | 189 traits, 1,134 bin rows; the 132-product single-month run is kept |
| Safety stock + LP | `run_lp.py --allocation-pct 103 --retire-stale-pending` | `lp_run` 2, 97 rows (safety stock is computed inside this run) |
| Review flags | `compute_review_flags --write` | 189 rows (replaced 132) |
| Marts | `analytics.marts --refresh`, then `rehearse_marts --check-only --schema mart` | refreshed, PASS |

## Open points

| Item | For |
|---|---|
| The basis itself is pending TA confirmation (DEC-37) | TA |
| Coverage gate read as met with 5 dead products at 0; say if these should be handled differently | Yuan |
| `stability_v1` bins read "churn" for all 189: its cut-offs count Tier A months out of 38, and the new basis has 27 runs. No new cut-off was invented. Not used by the forecast router | Yuan |
| Stored backtests (forecast runs 2 and 3) are still on the single-month list and pre-date the blank-quantity fix; the dashboard's accuracy card reads them. Rewriting them on the new list needs a decision | Yuan |
| Old run and old Tier A wording in the frontend ("single month" labels) not reviewed | Maika / Audrey |
| Preview (generated) months still rank Tier A on the single month, stamped with the new basis so they display | — |

## Files

| File | What |
|---|---|
| `measure.py` | read-only: Tier A old vs new, cycle snapshot, before/after counts |
| `at_the_time.py` | read-only: at-the-time backtest on both lists |
| `tiers.json`, `state_before.json`, `state_after.json`, `plan_and_flags.json`, `headline_at_the_time.csv` | the numbers above (totals only) |
| `local/` (git-ignored) | per-product plan, logs, the 5 retired rows, the 9 removed forecast rows, the cycle's rows before run 2 |
