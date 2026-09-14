-- analytics/db/migrations/0014_product_dimension_unilever_sku_partial_key.sql
--
-- Fixes root cause #4 of the 2026-09-15 cutover incident
-- (reports/PROJECT_STATE_2026-09.md §10): scripts/run_canonical_load.py's
-- _product_fk_spec("sku") used to match/insert against the table-wide
-- UNIQUE (principal, grain, sku_code, category_path) key (migration 0013).
-- That key goes stale for Unilever the moment
-- run_category_brand_backfill() runs once - it flips every Unilever
-- SKU-grain row's category_path from NULL to a real value
-- (2,098/2,098 rows, confirmed 2026-09-15), while the FK-resolution code
-- still looks for category_path IS NULL (its static_values assumption).
-- Every subsequent resolution attempt then treats an existing SKU as new
-- and re-inserts it. Confirmed by reproducing the exact 1,807-row batch
-- insert against public in a rolled-back transaction: 1,807 rows accepted
-- as "new" by Postgres, not 0.
--
-- Fix: narrow the natural key used by that one FactPlanItem
-- (sales_unilever_sku_demand, FACT_PLAN's only caller of
-- _product_fk_spec("sku")) to (principal, grain, sku_code) - stable
-- columns nothing ever mutates post-load. Verified safe for Unilever only:
-- 0 of 2,098 Unilever SKU-grain rows share a sku_code in the pre-incident
-- backup (backups/live_backup_20260914T151217Z/product_dimension.parquet),
-- so sku_code alone already uniquely identifies the row - category_path
-- was never actually load-bearing for uniqueness there.
--
-- Explicitly NOT applied table-wide or to Del Monte: 252 Del Monte
-- sku_codes in the same backup legitimately span multiple category_path
-- values (e.g. '9DBL58406' -> '/BASE' and '/FOUR SEASONS' are two
-- distinct real rows) - collapsing those to a 3-column key would silently
-- merge genuinely different products. Del Monte's SKU-grain rows were
-- loaded outside scripts/run_canonical_load.py entirely (pre-canonical-
-- load era) and this migration does not touch them. The existing 4-column
-- UNIQUE NULLS NOT DISTINCT constraint from migration 0013 is untouched
-- and still protects the whole table, Del Monte included.
--
-- A PARTIAL unique index is required (not a plain table-wide one) because
-- this predicate only holds for one principal/grain slice: a bare
-- UNIQUE (principal, grain, sku_code) would immediately reject Del Monte's
-- legitimate multi-category-per-sku_code rows on creation. Postgres
-- requires the INSERT's ON CONFLICT clause to repeat this same predicate
-- verbatim to infer this index as the conflict target - see
-- _product_fk_spec("sku")'s conflict_index_where and
-- resolve_dimension_fk()'s on_conflict_do_nothing(index_where=...)
-- (analytics/etl/load.py).

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS product_dimension_unilever_sku_key_idx
    ON Product_Dimension (principal, grain, sku_code)
    WHERE principal = 'unilever' AND grain = 'sku';

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DROP INDEX IF EXISTS product_dimension_unilever_sku_key_idx;
-- COMMIT;
