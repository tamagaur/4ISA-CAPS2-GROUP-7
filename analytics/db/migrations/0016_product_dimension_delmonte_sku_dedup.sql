-- analytics/db/migrations/0016_product_dimension_delmonte_sku_dedup.sql
--
-- Fixes the 291-row Del Monte sku-grain Product_Dimension duplication found
-- during the 2026-09 column-gap audit (reports/COLUMN_GAP_AUDIT_2026-09.md).
-- 252 sku_codes had 2-3 rows each, differing only in category_path.
--
-- Root cause, traced to code (not a canonical-loader defect - confirmed
-- scripts/run_canonical_load.py's _product_fk_spec("sku") is never invoked
-- for principal='delmonte'; FACT_PLAN's only grain="sku" FactPlanItem is
-- Unilever-locked): scripts/generate_synthetic_dm.py:25-44, an ad-hoc,
-- non-canonical, pre-canonical-load-era script, inserted these rows with
-- `ON CONFLICT (principal, grain, sku_code, category_path) DO NOTHING` and
-- its own docstring (line 31-32) calling category_path a "fake category ...
-- Simple heuristic ... extract[ed] from the SKU description" (a hardcoded
-- keyword ladder, line 40-44: default '/BASE', else '/FOUR SEASONS' /
-- '/PINEAPPLE JUICE' / '/KETCHUP' / '/SPAGHETTI SAUCE' by substring match).
-- Because that ON CONFLICT key includes category_path, re-running the
-- script (or running it against sku_codes whose description text changed)
-- inserted new rows instead of upserting.
--
-- This CORRECTS migration 0014's comment (lines 26-29), which asserted
-- these 252 sku_codes "legitimately span multiple category_path values"
-- and cited '9DBL58406' as an example of "two distinct real rows" - that
-- premise does not hold. No Del Monte source workbook maps an individual
-- SKU to a category (category only exists at sellout_fact's region x
-- period x category grain); every non-null category_path value on this
-- grain (310/15,339 rows, confirmed) is one of generate_synthetic_dm.py's
-- 5 heuristic strings, including the 2/252 groups whose lowest-product_key
-- row already had a non-null category (both '/BASE', the heuristic's own
-- default fallback). None of the 291 duplicate-extra rows are referenced by
-- any fact table's product_key (checked: inventory_fact, sellout_fact,
-- unilever_sku_demand_fact, abc_classification, forecast_result all zero),
-- so this loses nothing real.
--
-- Verified before writing this migration (public, read-only queries,
-- 2026-09-17): 291 extra rows across 252 delmonte sku_codes; 250/252
-- groups' MIN(product_key) row has NULL category_path; 310 total
-- category_path-populated delmonte/sku rows, all 5 heuristic strings
-- accounted for, 0 exceptions.
--
-- Sequence per Yuan: backup (backups/live_backup_20260916T190021Z/,
-- verify_restore()-tested PASS on all 16 tables) -> this migration against
-- a scratch schema first (--dry-run equivalent) -> Yuan's approval -> public.

BEGIN;

-- Step 1: keep the lowest product_key per (principal, sku_code), drop the
-- rest. Explicitly scoped to delmonte/sku (unilever already has 0
-- duplicates per migration 0014's own verification) so this cannot touch
-- any other grain or principal.
DELETE FROM Product_Dimension d
WHERE d.principal = 'delmonte'
  AND d.grain = 'sku'
  AND d.sku_code IS NOT NULL
  AND d.product_key <> (
    SELECT MIN(d2.product_key)
    FROM Product_Dimension d2
    WHERE d2.principal = d.principal
      AND d2.grain = d.grain
      AND d2.sku_code = d.sku_code
  );

-- Step 2: null out the heuristic-fake category_path on every surviving
-- delmonte/sku row (not just the former duplicates - 19 single-row
-- sku_codes also carry one of the 5 heuristic values and are equally
-- fabricated). Scoped to the exact 5 known heuristic strings, not a bare
-- "set everything NULL", so this errors loudly (0 rows touched) instead of
-- silently over-clearing if the data shape ever changes before this runs.
UPDATE Product_Dimension
SET category_path = NULL
WHERE principal = 'delmonte'
  AND grain = 'sku'
  AND category_path IN ('/BASE', '/FOUR SEASONS', '/PINEAPPLE JUICE', '/KETCHUP', '/SPAGHETTI SAUCE');

-- Step 3: make this class of duplicate structurally impossible going
-- forward. Partial (not table-wide) because Product_Dimension's
-- grain='category' rows have sku_code IS NULL by design (static_values in
-- _product_fk_spec("category")) and must stay excluded.
CREATE UNIQUE INDEX IF NOT EXISTS product_dimension_sku_key_idx
    ON Product_Dimension (principal, sku_code)
    WHERE sku_code IS NOT NULL;

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DROP INDEX IF EXISTS product_dimension_sku_key_idx;
-- COMMIT;
-- (The DELETE and category_path UPDATE have no generic reverse statement -
-- restore backups/live_backup_20260916T190021Z/product_dimension.parquet
-- via scripts/backup_live_db.py's restore_over_public() if this must be
-- undone.)
