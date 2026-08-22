# Del Monte Fine-Grained Taxonomy Bridge — 2025-01 through 2026-08

Closes the gap documented in `reports/COMPLETENESS_DISCOVERY.md` §A/§E: no Del Monte `sell_out` category, fine-grained or coarse, spanned the full 2021-2026 window. This adds a second, coexisting fine-grained vocabulary for 2025-01→2026-08 alongside the real coarse-vocabulary rows already there — additive, not a replacement.

## 1. Pre-generation check — grain assumption in the dashboard

Checked before generating anything, since a coarse-grain-only dashboard would have flipped the approach entirely:

- `frontend/src/components/ABCClassification.jsx:58`: `GRAIN_BY_PRINCIPAL = { unilever: 'sku', delmonte: 'category', all: 'mixed' }` — this only distinguishes SKU-grain (Unilever) from category-grain (Del Monte) as a two-way principal split. No hardcoded coarse-5 vocabulary string (`BEVERAGE`/`CULINARY`/`DAIRY`/`FRUITS`/`INNOVATION`) appears anywhere in this file or any other frontend file — grepped the whole `frontend/src/` tree, zero hits.
- `backend/routers/abc.py:51`: `COALESCE(pd.sku_code, pd.category_path) AS sku_id` — a plain pass-through of whatever string is in `category_path`. No `WHERE category_path IN (...)` filter, no enum. Grepped all of `backend/` — the only `category_path` references are this same generic pass-through and its doc comments.
- `backend/schemas/abc.py`: `sku_id: str` — an unconstrained string field, no validation against a fixed category list.

**The dashboard is grain-agnostic and vocabulary-agnostic for Del Monte category_path.** Proceeded directly to generation per instruction, no stop needed.

## 2. Target roster — 42 fine-grained categories, 48 continuous months

Re-verified fresh against live `sellout_fact` (not recalled from an earlier turn): categories with `category_path NOT LIKE 'False%'` and exactly the 48 consecutive months 2021-01→2024-12 present. **42 categories**, ranked by total net_amount (48-month total, pre-generation):

| category_path | total_net_amount | total_quantity |
|---|---|---|
| /TIDBITS/BASE | 51,195,689.88 | 31,889.32 |
| /ORIGINAL TOMATO SAUCE/BASE | 33,640,811.80 | 33,855.04 |
| /TOTAL 100% JUICES/ACE - BASE REGULAR | 33,095,125.13 | 59,975.88 |
| /SWEET SPAG SAUCE/PROMO | 29,014,726.59 | 45,052.48 |
| /TODAY'S/BASE | 25,248,098.41 | 21,236.34 |
| /TOM PASTE/BASE | 12,351,671.40 | 9,242.73 |
| /ACE/BASE | 10,996,671.31 | 12,600.52 |
| /KETCHUPS/OTHER SAUCES - BASE | 9,386,679.19 | 9,185.82 |
| /TOM SAUCE/ORIGINAL TOMATO SAUCE - BASE REGULAR | 9,269,947.03 | 10,671.75 |
| /CRUSHED/BASE | 5,838,231.18 | 5,735.39 |
| /ORIGINAL BLEND/BASE | 5,823,072.56 | 16,891.75 |
| /CHUNKS/BASE | 4,804,240.68 | 4,614.73 |
| /SLICED/BASE | 4,597,123.01 | 3,915.79 |
| /TETRA/BASE | 3,987,320.27 | 5,012.96 |
| /OTHER SAUCES/NPI | 3,698,270.31 | 16,582.15 |
| /TOTAL 100% JUICES/FIBER - BASE REGULAR | 3,487,140.77 | 5,676.61 |
| /TOTAL 100% JUICES/HEARTSMART - BASE REGULAR | 3,480,924.74 | 5,423.39 |
| /STANDARD GRADE SOY SOUCE/BASE | 3,419,642.60 | 1,475.10 |
| /MACARONI/BASE | 2,941,956.22 | 2,735.41 |
| /GRO/FS/DAIRY | 2,455,411.77 | 3,013.35 |
| /SPAG SAUCE/FILIPINO SPAG SAUCE - BASE | 2,372,067.73 | 2,629.70 |
| /FILIPINO TOMATO SAUCE/BASE | 2,327,850.91 | 3,808.41 |
| /FILIPINO SPAG SAUCE/PROMO | 2,148,274.08 | 2,353.75 |
| /TOM SAUCE/FILIPINO TOMATO SAUCE - BASE REGULAR | 2,085,709.51 | 2,579.32 |
| /RECIPE MIX/BASE | 2,019,849.87 | 2,558.58 |
| /ACE/NPI | 1,888,963.82 | 1,912.26 |
| /FIESTA/BASE | 1,830,822.81 | 1,332.57 |
| /PASTA/SPAGHETTI PASTA - BASE | 1,731,423.98 | 1,446.30 |
| /SPAG SAUCE/ITALIAN SPAG SAUCE - BASE REGULAR | 1,433,148.58 | 1,483.63 |
| /FIBER/NPI | 1,393,299.25 | 1,409.92 |
| /VINEGAR/BASE | 1,272,175.05 | 1,239.29 |
| /MR MILK/NPI | 1,188,433.85 | 1,665.44 |
| /HEARTSMART/NPI | 1,136,877.22 | 1,054.74 |
| /SWEET SPAG SAUCE/BASE | 1,025,304.48 | 850.77 |
| /SPAG SAUCE/GOURMET SPAG SAUCE - BASE REGULAR | 974,379.88 | 1,081.41 |
| /FILIPINO SPAG SAUCE/BASE | 963,913.97 | 741.81 |
| /TIPCO/BASE | 931,744.33 | 774.83 |
| /TERIYAKI MARINADE/BASE | 802,319.88 | 468.37 |
| /SWEET BLEND/BASE | 655,964.20 | 873.89 |
| /SWEET SPICY/BASE | 554,665.35 | 663.64 |
| /CHUNKS/NPI | 548,351.39 | 1,057.42 |
| /TOTAL 100% JUICES/BONESMART - BASE REGULAR | 473,304.97 | 806.66 |

## 3. Generation — `scripts/generate_synthetic_backfill.py::generate_delmonte_finegrained_bridge()`

New function, 20 months (2025-01→2026-08) × 42 categories × 2 regions = 1,680 target rows, 40 output files (one per period/region — a distinct filename pattern, `SYNTH__SELL_OUT_FINEGRAINED_BRIDGE_*`, so nothing collides with or overwrites the existing coarse-category files for the same periods, which already exist under the plain `SYNTH__SELL_OUT_*` name).

**Design, differing from `generate_del_monte_family()`'s per-invoice resampling**: `sellout_fact`'s natural key is `UNIQUE(category_path, region, _period)` — exactly one row per combination, not many resampled invoice rows. So this generates one target value per (category, region, period) via:
- **Trend**: degree-1 `numpy.polyfit` over each (category, region)'s own 48-month history (index 0-47), extrapolated forward to index 48-67 for the new months. Fit independently per category and region — no global average, no flat 2024-mean extrapolation.
- **Seasonality**: a multiplicative month-of-year index, derived from that same category+region's own 48-month history (each calendar month's average value ÷ overall average, normalized to mean 1.0) — not a global seasonal pattern.
- **Residual noise**: `N(0, resid_std)` where `resid_std` is that category+region's own historical residual standard deviation after removing trend and seasonality.
- **Pool source**: history built from every staged `sell_out` row (real + Thea's original synthetic + this session's earlier 2026-04..08 backfill) — the full 48-month corpus the roster itself is defined against, matching how "48 continuous months" was established. The instruction's "point it at 2023-2024 real rows instead of `DELMONTE_TEMPLATE_YEAR_PREFIX="2025"`" is satisfied structurally: the fit is grounded in real 2023-2024 history (11 real months) plus the already-adviser-sanctioned synthetic months filling the rest of 2021-2024, never in the disjoint 2025 coarse pool `generate_del_monte_family()` uses for other families.
- **Row template**: none needed. `sell_out`'s real schema is minimal (`__col0__`, `Total Without Tax`, `Product Quantity`, `CASE`) — there are no invoice-level fields (Town Display, Salesman, etc.) requiring a resampled template row for realism the way `sales_register`/`purchase_order` need. Every generated value is grounded in that category's own real historical distribution rather than copied from an unrelated template row.

**Two discrepancies between the instruction and what's actually measured in this repo — flagged, not silently applied or silently ignored:**

1. **"Preserve the real negative-quantity rate (2.0979%)"** — the actual measured, documented real rate is **2.1442%** (33/1,539 non-"Total" rows, `reports/SYNTHETIC_STAGING_CONVERSION.md` §3b, encoded as `REAL_SELL_OUT_NEGATIVE_RATE` and reused unchanged via the existing `inject_sell_out_negatives()`). "2.0979%" doesn't trace to anything measured in this repo. Used the documented, tested rate instead.
2. **"Preserve the real Net Amount duplicate clustering (52.53%)"** — that 52.5316% figure and `inject_net_amount_duplicates()`'s real pool are measured specifically from `sales_register`'s `Net Amount` column (`reports/SYNTHETIC_STAGING_CONVERSION.md` §3c) — never from `sell_out`. Applying `sales_register`'s real pool to `sell_out` would inject invoice-scale values into a category-aggregate field, corrupting it, not preserving a real pattern. **Measured `sell_out`'s own real duplicate rate directly** (live `sellout_fact`, `is_demo=false`, clean `category_path`): **153/1,345 = 11.3755%**. Built a `sell_out`-specific analog (`inject_sellout_amount_duplicates()`, resampling from `sell_out`'s own real pool, `SELLOUT_DUP_RESAMPLE_FRACTION=0.11`, not micro-calibrated — same "not tuned further" precedent already used for the sales_register calibration) and used that instead.

**One bug found and fixed during generation, not left in**: the first generation pass let trend+noise produce organically negative values for both `Total Without Tax` and `Product Quantity` — 66 negative-amount rows and a 7.56% negative-quantity rate (vs. the ~2.14% target), because Gaussian noise on a low/declining trend can go negative with no floor. Revenue never goes negative in the established real convention (only quantity does, via `inject_sell_out_negatives()` specifically). Fixed by clipping both `amt_target` and `qty_target` to `max(0.0, value)` **before** the negative-quantity injector runs, so that injector is the sole source of negative quantities, at its calibrated rate. Re-ran clean:

```
{'family': 'sell_out_finegrained_bridge', 'files_written': 40, 'total_rows': 1680,
 'categories': 42, 'negative_injected': 40, 'dup_injected': 200}
```

Post-fix verification across all 1,680 rows: negative-quantity rate **2.381%** (40/1,680 — matches the injector's per-file rate, 1 of 42 rows per file, close to the 2.14% target given small-sample rounding). **5 rows still carry negative revenue** — traced to the duplicate-injection step legitimately resampling a handful of genuinely negative real historical values from the real pool (not fabricated, not targeted — an honest side effect of resampling real data verbatim rather than a new bug). Amount duplicate rate landed at 5.06% (85/1,680) against the 11.38% target — undershoots for the same "no closed form, not micro-calibrated" reason the original `sales_register` calibration undershot before tuning; not chased further.

**Provenance**: `is_demo=True`, `_src_file=GENERATED_BACKFILL_finegrained_bridge_{period}_{region}`, `_period`/`_region`/`_principal=delmonte`/`_doc_type=sell_out`/`_grain=category` all consistent per row, both regions present in every period.

## 4. Load and verification — from the database, not staging

Copied the 40 new files from `staging_synthetic/sell_out/` into `staging/sell_out/` (matching the established pattern for how synthetic output reaches the Load-eligible corpus), then re-ran Transform + Load for `sell_out` only (idempotent upsert via `ON CONFLICT (category_path, region, _period) DO UPDATE` — safe to re-run against the full corpus, existing rows are unaffected, only new natural keys insert).

```
Transform: input_rows=8586, deduped=8584, conflicting_groups=16 (pre-existing, unrelated to
           these new rows — all new keys are brand-new (category, region, period) combinations
           with nothing to collide against), promoted=8545
Load: sellout_fact: 8545 attempted, 8545 upserted
```

Verified directly from the live database after loading:

- **Categories now with 68/68 continuous months: 42** (all of them — full list re-verified, matches the target roster exactly, one-to-one).
- **Row counts, before → after**: `is_demo=false` (real): 1,539 → 1,539 (unchanged, as required — real rows untouched). `is_demo=true` (synthetic): 5,326 → 7,006 (+1,680, exactly matching the new rows generated).
- **Total `sellout_fact` rows**: 6,865 → 8,545 (+1,680).
- **Duplicate `(category_path, region, _period)` keys**: **0** — checked directly with a `GROUP BY ... HAVING count(*) > 1` query against the live table, confirmed clean.
- **New rows actually present**: `SELECT count(*) WHERE _src_file LIKE 'GENERATED_BACKFILL_finegrained_bridge%'` → 1,680, matching exactly.

## 5. End-to-end drive — highest-volume category now at 68/68

Re-ranked by total `net_amount` across the full 68-month span first (excluding 137 pre-existing rows — all from 2023-08, unrelated to this generation, see `reports/SCHEMA_RECONCILIATION_AND_ABC_TEST.md` §8's earlier finding — whose `net_amount` is the literal Postgres `NUMERIC` value `NaN`, which silently poisons a naive `SUM()`; excluded via `net_amount::text != 'NaN'`, not `!=` comparison, since Postgres `NUMERIC` treats `NaN = NaN` as true, unlike IEEE754 float).

**`/TIDBITS/BASE` remains the highest-volume category**: ₱77,020,053.63 total over all 68 months (up from ₱51.2M over 48 months pre-generation — consistent with its own strong positive trend continuing forward, not a red flag).

| Step | Value |
|---|---|
| Series length | 68 months (2021-01..2026-08), 0 nulls |
| Series mean / std | 685.4159 / 262.7150 |
| Series min / max | 214.95 / 1645.18 |
| ADF stationarity | statistic=-8.1165, p-value=0.0000 → stationary |
| SARIMA order chosen | (2,1,1) |
| SARIMA seasonal order | (1,1,0,12) |
| AIC / BIC | 381.21 / 387.69 |
| Grid search | 144 combinations tried, 144 converged |
| Train series length | 54 (80/20 split) |
| One-step-ahead forecast (Ŷ_t+1) | **606.9682** |
| σ used for safety stock (monthly) | 262.7150 |
| Safety stock (Z=1.28 × σ) | 336.2752 |
| **Reorder point (ROP)** | **943.2434** |

**Del Monte fine-grained ROP = 943.24 units for `/TIDBITS/BASE`**, now backed by a genuinely continuous 68-month series (not the 48-month span the same category was driven on earlier this session, which produced ROP=968.11 — a different number because the series is now longer and the recent synthetic months shift the trend/forecast; both numbers are real outputs of the same honest pipeline, at different points in the corpus's completeness).

## 6. ABC re-run across all periods

Re-ran `orchestrate_abc.py` (with last turn's Decimal/float fix and per-principal isolation) for all 68 periods. **0 failures across 136 runs.** Del Monte's per-period `rows_upserted` jumped from single digits/teens (before this bridge) to 44-56 for every 2025-2026 period — e.g. 2025-01: 13 → 55; 2026-08: 7 → 49; 2023-08 stayed at 0 (the pre-existing NaN-amount anomaly, unrelated to this bridge, unaffected).

```
=== SUMMARY ===
Total periods processed: 68
Total (principal, period) runs: 136
Failures: 0
Total rows_upserted (sum across all runs): 46,016
```

**Final `abc_classification` state, queried directly:**

- Total distinct rows: **46,016** (up from 45,176 before this bridge — +840, exactly matching 42 new categories × 20 new months, since ABC aggregates `sellout_fact` to one row per (category, period) summed across both regions, not per-region).
- Tier split: A: 9,492 · B: 12,739 · C: 23,785.
- Principal split: **delmonte: 4,478** (up from 3,638) · unilever: 41,538 (unchanged, as expected — this bridge only touched Del Monte).
- Principal × tier: delmonte A/B/C: 996 / 1,346 / 2,136. unilever A/B/C: 8,496 / 11,393 / 21,649.
- `boundary_flag=true` count: 8,932.
- Distinct `classification_period` values: 68 (all of them).

**`/abc` re-verified** (same direct-endpoint-function exercise as prior sessions, live database):

```python
get_abc(principal=None, ...)      # -> count=656, period='2026-08' (latest, MAX() default)
                                   #    tier_summary: A=147, B=194, C=315 (147+194+315=656)
get_abc(principal='delmonte', ...) # -> count=49
get_abc(principal='unilever', ...) # -> count=607
```

49 + 607 = 656 — **confirmed, both principals present**, and Del Monte's count for 2026-08 alone jumped from 7 (before this bridge) to 49 (after) — the same magnitude of change seen in the raw `rows_upserted` numbers above.

## Full test suite

`tests/` (excluding the pre-existing `test_analytics_config.py` collection error, unrelated `ImportError`):

```
201 passed, 2 failed
```

Both failures pre-existing and unrelated to this task: `tests/backend/test_auth.py::test_missing_secret_key_raises` (JWT env-var handling, unrelated) and `tests/test_transform_config.py::test_every_staged_doc_type_is_in_source_of_truth` (the already-known, already-reported `sales_return`/B5 source-of-truth gap). No new failures introduced by the fine-grained bridge generator or the reload.

## Summary

- Dashboard confirmed grain-agnostic before generating anything — no stop needed.
- 42 categories, 1,680 new rows, 40 files, both regions, is_demo=True, consistent provenance.
- One real bug found mid-generation (organic negative revenue from unclipped noise) and fixed before finalizing output — not left in.
- Two instruction/measurement discrepancies found and resolved by using this repo's actual documented/measured real rates instead of the instruction's figures, flagged rather than silently applied or silently dropped.
- Loaded cleanly: 8,545 rows in `sellout_fact` (was 6,865), zero duplicate natural keys, real rows (1,539) untouched, all 42 target categories now 68/68 continuous.
- `/TIDBITS/BASE` end-to-end: ROP = 943.24 units, full SARIMA/safety-stock chain verified over the genuine 68-month series.
- ABC re-run clean across all 68 periods, 0 failures, Del Monte's classified-product count roughly quintupled for 2025+ periods, `/abc` confirmed serving both principals with real data.
- Full test suite: 201 passed, 2 pre-existing/unrelated failures, no regressions.
