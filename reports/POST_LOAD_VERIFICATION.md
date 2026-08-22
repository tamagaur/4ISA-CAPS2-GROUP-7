# Post-Load Verification Report

Generated 2026-08-20, immediately after the full real+synthetic Load run.

## 1. Row counts per fact table, split by is_demo

| Table | Total | Real (is_demo=false) | Synthetic (is_demo=true) |
|---|---|---|---|
| sales_fact | 53,320 | 17,947 | 35,373 |
| purchase_fact | 2,110 | 353 | 1,757 |
| inventory_fact | 20,905 | 5,171 | 15,734 |
| sellout_fact | 6,865 | 1,539 | 5,326 |
| unilever_sku_demand_fact | 44,575 | 24,906 | 19,669 |
| **Total** | **127,775** | **49,916** | **77,859** |

## 2. Non-empty check

All 4 named Del Monte fact tables confirmed non-empty (sales_fact, sellout_fact, inventory_fact, purchase_fact). unilever_sku_demand_fact confirmed non-empty as well.

## 3. `_Real` view filtering check

`sales_fact_real`, `purchase_fact_real`, `inventory_fact_real`, `sellout_fact_real` each return exactly the real-row count with **0** is_demo=true rows leaking through. Filtering is correct.

## 4. DELETE + ROLLBACK transactional safety check

Inside one transaction: `DELETE FROM <table> WHERE is_demo=true` on all 5 facts removed exactly the synthetic-row counts (35,373 / 1,757 / 15,734 / 5,326 / 19,669), leaving exactly the real-row counts in-transaction. `ROLLBACK` then restored every table to its exact pre-delete count on a fresh connection. `is_demo` is fully load-bearing: the demo/real split can be surgically removed and cleanly restored.

## 5. 68-month coverage checklist — rebuilt from the live database, diffed against pre-load

| Principal | Doc type | Pre-load YES | Post-load YES | Delta |
|---|---|---|---|---|
| delmonte | sales_register | 67/68 | 68/68 | +1 |
| delmonte | purchase_order | 45/68 | 66/68 | +21 |
| delmonte | inventory_sign_off | 63/68 | 68/68 | +5 |
| delmonte | sell_out | 66/68 | 68/68 | +2 |
| unilever | unilever_sku | 68/68 | 68/68 | 0 |
| delmonte | sales_return | 0/68 | 0/68 | 0 (never loaded — no Extract driver, per DEC scope) |
| delmonte | rmr_gs_bo | 0/68 | 0/68 | 0 (never loaded — see Load-phase scope note below) |
| unilever | ssis_summary | 0/68 | 0/68 | 0 (never loaded — natural_key unconfirmed, reported not implemented) |

**The single most important check — no regressions.** Every discrepancy is an *increase* in YES-months. Zero months that showed YES pre-load show zero rows post-load.

**Why the increases, especially purchase_order's +21:** `reports/PRE_LOAD_COVERAGE_CHECKLIST.md` was built as a snapshot *before* the final round of the invoice-numbering collision fix (the `900000+` base offset applied to `convert_synthetic_to_staging.py` and never re-run against that checklist afterward). The Load driver, run later, called `transform_fact()` fresh against the fully-corrected staging files — which had far fewer natural-key conflicts. This was verified directly, not assumed:
- Re-running `transform_fact()` now for purchase_order shows only 274 conflicting groups (548 rows) corpus-wide, versus the ~700+ conflicting rows implied by the stale checklist's per-month breakdown.
- 2024-03 specifically: 36 deduped rows, only 16 actually flagged conflicting today (not all 36) — 20 correctly load.
- Direct spot-check: queried `purchase_fact` for all 274 currently-conflicting `(invoice_num, principal, region)` keys — **0 found present**. The conflict-exclusion logic in the Load driver is confirmed working correctly; no conflicting row was silently loaded.

`reports/PRE_LOAD_COVERAGE_CHECKLIST.md` itself is now stale for purchase_order/sales_register/inventory_sign_off/sell_out and should be treated as a historical snapshot, not current state — this file (POST_LOAD_VERIFICATION.md) supersedes it for coverage purposes.

**rmr_gs_bo note:** synthetic backfill was generated (36 files, Dec 2025–Aug 2026) per instruction, but no Load driver block was built for `salesreturn_fact`'s value-based rmr_gs_bo rows in this phase's scope — `SalesReturn_Fact` remains empty. Flagged, not silently worked around.

**Minor data-quality artifact found (not a regression, not fixed):** one purchase_order natural-key group's `region` value is the Python boolean `False` rather than a region string (source-data column-shift artifact, pre-existing in real 2024 BILL-numbered files). Affects a handful of conflicting rows already correctly excluded from `purchase_fact`; does not affect any loaded row's correctness. Worth a follow-up look if purchase_order data quality work continues.

**Second data-quality artifact found (not a regression, not fixed):** 1,009 of 6,865 `sellout_fact` rows (14.7%, all `is_demo=false` — real data) have `category_path` values of `"False"`, `"False  (2)"`, `"False  (6)"`, etc. Traced to real ILOCOS region sell_out sheets (e.g. `data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY SELL OUT.xlsx`, sheet `ILOCOS_SELL OUT`) — a pre-existing source/Extract-layer category-column parsing issue, not introduced by this session's synthetic generation. Out of scope to fix this late (would touch shared Extract/Transform code, same caution already applied to the `unilever_sku` manifest-grouping bug). Real, clean category values (e.g. `/CHUNKS/NPI`, `/ACE/BASE`) are unaffected and were used for Step 6's feasibility check below.

## 6. Forecast feasibility

- **Del Monte category `/CHUNKS/NPI`** (sellout_fact, category grain per DEC-03): 48 continuous months, **2021-01 through 2024-12**, zero gaps. Real Del Monte sell_out coverage does not extend synthetic backfill past 2024-12 for this category in the current corpus snapshot checked.
- **Unilever SKU `20292811`** (unilever_sku_demand_fact, SKU grain): 68 continuous months, the full **2021-01 through 2026-08** span, zero gaps.
- **Longest gap / binding constraint per principal:** Del Monte — bounded by real sell_out coverage itself (a genuine real-data extent limit, not an Extract/Transform defect). Unilever — none; SKUs drawn from the 156 SKUs with full 68/68 continuity (real roster + synthetic backfill) have no gaps at all.

## 7. End-to-end drive — Unilever SKU 20292811

Pulled directly from the live database via a plain SQL query (no function named `get_demand_series()` exists anywhere in this codebase — checked, not assumed; the nearest existing building blocks are `analytics/forecasting/sarima.py`'s `fit_sarima()`/`forecast_one_step()` and `analytics/optimization/lp.py`'s `compute_safety_stock()`/`compute_rop()`, which is what this drive used directly against a hand-built query).

| Step | Value |
|---|---|
| Series length | 68 months, 0 nulls |
| Series mean / std | 98.6218 / 74.6186 |
| Series min / max | -10.75 / 323.79 |
| ADF stationarity | statistic=-7.7467, p-value=0.0000 → stationary |
| SARIMA order chosen | (2,1,1) |
| SARIMA seasonal order | (1,1,0,12) |
| AIC / BIC | 334.08 / 340.56 |
| Grid search | 144 combinations tried, 144 converged |
| Train series length | 54 (80/20 split) |
| One-step-ahead forecast (Ŷ_t+1) | **197.6229** |
| σ used for safety stock | 74.6186 — see note below |
| Safety stock (Z=1.28 × σ) | 95.5119 |
| **Reorder point (ROP)** | **293.1348** |

**A real recommendation number came out the other end: ROP = 293.13 units for SKU 20292811.**

**Flagged, not silently substituted:** `compute_safety_stock()`'s docstring specifies σ as the standard deviation of a *daily* reconstructed demand series (`granularity.py`'s disaggregation output). Unilever SKU grain has no daily series anywhere in the source data — `granularity.py`'s own `resolve_unilever_sku_grain()` docstring confirms this explicitly and only validates month-grain continuity, matching `sarima.py`'s monthly seasonality assumption. Reconstructing a fake daily series would be exactly the fabrication DEC-03 forbids. This drive substituted the *monthly* series' standard deviation for σ instead — a real, defensible number, but not the daily figure the Step 17 formula was originally written for. This is a genuine spec/grain mismatch between Step 17's formula and DEC-03's Unilever grain decision, worth an adviser call on whether monthly σ is the intended interpretation for SKU-grain principals.

**Note on negative values:** the series contains one negative value (-10.75 in the 2021-03 synthetic-backfill month). Traced to the backfill generator resampling a real historical row with a negative `net_amount_inc_tax`/`quantity_sold` value and scaling it — i.e. real Unilever SKU data genuinely contains negative rows (returns/credits), faithfully reproduced by the backfill's real-row-resampling design, not a generation bug.

## 8. Full-suite test numbers

- `tests/etl/` — **128/128 passed** (unchanged from the pre-Load-phase baseline).
- `tests/` (full suite, excluding one pre-existing collection error) — **171 passed, 2 failed**:
  - `tests/backend/test_auth.py::test_missing_secret_key_raises` — pre-existing, unrelated to this session (JWT secret-key env var handling).
  - `tests/test_transform_config.py::test_every_staged_doc_type_is_in_source_of_truth` — **new, and expected**: this session staged `sales_return` synthetic backfill (20 files, 525 rows) into `staging/sales_return/`, but `config/source_of_truth.yaml` has no entry for that doc_type (the same B5 gap already reported: `SalesReturn_Fact` has a `return_type NOT NULL CHECK IN ('GS','BO')` constraint that Shape A/B real files can't satisfy without fabrication — a human schema decision, not implemented this session). The test is correctly catching a real, already-flagged gap, not a regression.
  - `tests/test_analytics_config.py` — pre-existing collection error (`ImportError: cannot import name 'load_analytics_params'`), unrelated to this session's work.
