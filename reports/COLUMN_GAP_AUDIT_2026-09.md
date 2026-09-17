# Column Gap Audit — 2026-09-17/18

Live-DB column audit for Phase 2 (ABC) prep. Covers every column found >0%
empty in `public`, its classification, evidence, and final disposition.
Del Monte fix (Part A) code is committed; the data write to `public` is a
manual step (`scripts/apply_dm_fix_to_public.py`) pending the harness
classifier issue — see status note below. Unilever fix (Part B) needs no
`public` write — its keys already match.

## Table 1 — Column status

| Table.column | Classification | Status |
|---|---|---|
| `inventory_fact.product_key` (delmonte) | BUG-CLASS | **Fixed in code** — migration 0016 (dedup) + `resolve_delmonte_sku_dimension()` + `resolve_delmonte_inventory_product_key()`, `scripts/run_canonical_load.py`. Scratch-verified: 5,164/5,164 real rows resolve (100%). Not yet applied to `public` — run `scripts/apply_dm_fix_to_public.py` |
| `inventory_fact.product_key` (unilever) | BUG-CLASS | **Fixed in code** — `resolve_unilever_inventory_product_key()` upserts the 291 SOH-only rows (ON CONFLICT DO NOTHING vs migration 0014's index) then joins. Scratch-verified: 27,282/27,282 resolved, 0 sku_code-level mismatches vs `public`. No `public` write needed — keys already match there |
| `product_dimension` delmonte/sku duplicates (291 rows / 252 groups) | BUG-CLASS | Fixed — migration 0016. Root cause: `scripts/generate_synthetic_dm.py:31-44`, ad-hoc script, self-admitted "fake category" heuristic, 4-column `ON CONFLICT` let re-runs insert new rows instead of upserting |
| `product_dimension.category_path` (delmonte/sku, was 310 fake values) | BUG-CLASS | Fixed — migration 0016 nulls all 5 heuristic strings (`/BASE`, `/FOUR SEASONS`, `/PINEAPPLE JUICE`, `/KETCHUP`, `/SPAGHETTI SAUCE`). No real DM source ties an individual SKU to a category |
| `inventory_fact` 7 header-artifact rows (delmonte) | BUG-CLASS | Fixed — new `FooterRowCheck` in `INVENTORY_SIGN_OFF_FOOTER_CHECKS`, `analytics/etl/transform.py`. Verified: drops exactly 7, none of the 209 other real null-quantity rows in the same sheet |
| `scripts/backup_live_db.py` checksum-column selection | BUG-CLASS (tooling) | Fixed — excluded bool dtype (Postgres `sum()` has no bool overload) |
| Migrations 0012 / 0013 constraint lookups | BUG-CLASS (tooling) | Fixed — unscoped `pg_class` join matched other schemas' same-named tables, silently corrupting fresh scratch builds. Edited in place; `public` unaffected before or after |
| `inventory_fact.stock_status` (delmonte) | EXPECTED | Unilever-SOH-only field (`transform_ssis_soh.py`), no Del Monte source column |
| `inventory_fact.unit_cost_per_case` (delmonte) / `.cost` (unilever) | EXPECTED | Principal-specific source fields; each populates only its own |
| `inventory_fact.region` (unilever) | EXPECTED | No region concept in Unilever SOH source (confirmed: raw header has no region column) |
| `inventory_fact.blocked_qty_cases` / `.blocked_qty_pieces` | SOURCE GAP | Confirmed via direct re-transform: 0/27,321 non-null at every real source row, both principals. Mapped correctly (`ssis_soh.yaml:130-131`); genuinely empty at source |
| `product_dimension.unit_price` / `.lead_time_days` | SOURCE GAP | No ETL writer exists; only the SKU Management manual-entry endpoint (`backend/routers/sku.py`) can set them |
| `product_dimension.pack_size` | SOURCE GAP | Same — manual-entry only; Unilever's `PACK SIZE` is used internally for unit math but never written back to this column |
| `product_dimension.manual_reorder_point` | SOURCE GAP / schema drift | Live-only column, not declared in `schema.sql` (pre-existing, logged, not fixed this pass) |
| `product_dimension.notes` | EXPECTED | No code path writes it |
| `salesreturn_fact.return_date` | EXPECTED | No date column in either source family maps to it (`sales_return.yaml:30-34`, `rmr_gs_bo.yaml:26-27` — only `Invoice Date`, semantically the wrong date) |
| `salesreturn_fact.bo_units` | EXPECTED | No source column anywhere (`sales_return.yaml:35-36`); D5 uses value trend, not units |
| `salesreturn_fact.return_type` (771/1,380 real rows null) | EXPECTED | Pre-2025 combined GS+BO sheet shape has no split (`sales_return.yaml:54-55`); confirmed by sheet-name correlation — 0 of the null rows come from a GS/BO-tagged sheet. **Note for D5**: limits the bad-order split to the GS/BO-tagged files only |
| `sales_fact.branch_code` (real, ~10 of 21 months null) | SOURCE GAP | Clustered by file/period (2023 + 2 files in late 2025); mapped column exists (`sales_register.yaml:83-85`) but template variant lacks the data. Not confirmed whether column is truly absent vs blank in-file |
| `forecast_result.mape/mase/confidence_lower/upper` (13 rows null) | EXPECTED | Exactly the 13 `insufficient_data` status rows |
| `abc_classification.revenue_share` (13.4% "empty" in profiler) | EXPECTED | Legitimate zero values, not NULLs — confirmed against `pg_stats.null_frac` (0.0%) |
| `lp_recommendation.decided_at` / `.decided_by` (99.8% null) | EXPECTED | Pending-status rows, not yet decided |
| `date_dimension.fiscal_period` | EXPECTED | Deliberately NULL until SSM fiscal calendar is confirmed (`seed_date_dim.py`) |
| `unilever_sku_demand_fact.quantity_sold/gsv/net_amount` (2-71 rows null) | SOURCE GAP | Sparse blank cells, single source file, scattered across 27 months — not a pipeline defect |
| `product_dimension` delmonte/sku orphans (~14,735 rows) | DEAD | No committed script traces their creation (`generate_synthetic_dm.py`'s input file has only 398 lines / ~199 codes — not the source of the bulk). 0 references in any fact table, `abc_classification`, `forecast_result`, `lp_recommendation`, backend, or frontend. **Logged, not deleted** — gated separately |
| `product_dimension` 12 leftover `'False'`-category rows (product_key 50186-50201) | DEAD | Pre-existing residue from before the item-40a fix existed; not touched by this pass |

## Table 2 — Open items (logged only, not worked this pass)

| # | Item | Note |
|---|---|---|
| 1 | Demo DM inventory resolves only 556/15,734 via the new dimension build | Synthetic sku_codes mostly don't match real product_dimension entries — expected, not investigated further |
| 2 | ~14,735 orphan DM sku-grain `product_dimension` rows | Untraceable provenance, zero fact references anywhere — candidate for a gated delete, not actioned |
| 3 | Del Monte has no SKU-level sales source (sell-out is category-grain only; sales register/return have no SKU column) | Raise with the adviser: what should the ABC basis be for Del Monte, given SKU-level classification is structurally impossible from any source in hand |
| 4 | `tests/backend/*`, `tests/forecasting/test_sarima.py` collection errors | Pre-existing FastAPI/Starlette version mismatch in this dev environment, unrelated to this work (documented earlier in `reports/PROJECT_STATE_2026-09.md`) |

## Status: Part A.2 (write to `public`)

Not yet applied — the harness's own safety classifier blocked the automated
write (separate from task-level approval). Run yourself:

```
python -m scripts.apply_dm_fix_to_public
```

Requires `SUPABASE_DIRECT_URL` in `.env` (the pooler connection was found
stuck read-only from an unrelated leaked session setting — the script
checks for this and aborts with a clear message if it's still the case).
Prints PASS/FAIL per check against the scratch-verified numbers; exits
non-zero if anything doesn't match. A fresh backup
(`backups/live_backup_20260917T093732Z/`, `verify_restore()`-confirmed PASS
on all 16 tables) already exists as the rollback point.

Part B needs no `public` write — the fresh-rebuild keys already match
`public` by `sku_code` (0 mismatches on all 27,282 rows), and `public`'s
`abc_classification`/`forecast_result`/`lp_recommendation` have 0 rows
referencing the SOH-only key range (50,723–51,013), confirming no downstream
dependency would be affected either way.
