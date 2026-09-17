-- analytics/db/migrations/0012_sellout_source_defect_category.sql
--
-- Widens Product_Dimension.category_path_source's CHECK to allow a 4th
-- value, 'source_file_defect', distinct from 'unclassified'.
--
-- Found 2026-09-14 (Phase 1d full sweep, item 40a): SellOut_Fact's leading
-- category column (__col0__ -> category_path) holds the literal text
-- "False" / "False  (N)" for 194 real rows (staged), across 22 distinct
-- (region, _period) combinations, Jan 2023 - Feb 2024. Confirmed via raw
-- Excel inspection (data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/
-- 2024 FEBRUARY SELL OUT.xlsx, ILOCOS_SELL OUT sheet, rows 64+) that this
-- is genuinely baked into SSM's own source file - a broken formula/lookup
-- in their Sell Out template, not a pipeline defect. The real category
-- label is not recoverable from the row itself.
--
-- Yuan's ruling (2026-09-14): same treatment as Unilever's 380 no-SOH-
-- match SKUs - category_path -> the literal string 'UNCLASSIFIED',
-- revenue preserved (summed per (region, _period, is_demo), see
-- analytics/etl/transform.py::relabel_sellout_source_defect_categories()).
-- But NOT the same category_path_source value: 'unclassified' already
-- means "we checked, no SOH match exists" (a Unilever-only mechanism that
-- doesn't even apply to Del Monte's category grain) - collapsing this
-- into the same bucket would hide that these 22 groups are a CONFIRMED
-- SOURCE-FILE DEFECT, not an absence-of-data case, the moment anyone
-- queries category_path_source to understand why a row is unclassified.
-- Kept as its own value for that reason - one more allowed string is
-- cheaper than losing queryable provenance the column exists to provide
-- (see migration 0011's original comment on why category_path_source was
-- added in the first place).

BEGIN;

-- FIXED 2026-09-17 (same bug class found and fixed in migration 0013 while
-- doing the column-gap audit's scratch dry-run — see that migration's
-- comment for the full repro): the pg_class join below was unscoped by
-- schema, so on a server with other product_dimension-named tables in
-- other schemas (ssm_canonical / ssm_precutover_diag, always present per
-- reports/PROJECT_STATE_2026-09.md), it could resolve check_name from a
-- DIFFERENT schema's constraint while the unqualified DROP/ADD below still
-- (correctly) target the current schema's table via search_path — a
-- confusing but not immediately-breaking version of the same defect for
-- THIS migration specifically (the unconditional ADD at the end self-heals
-- the current schema either way), but still wrong to leave since it can
-- spuriously touch/attempt to drop an unrelated schema's constraint.
-- Same fix as 0013: 'product_dimension'::regclass resolves via search_path
-- to the one table actually in scope. Safe to edit in place for the same
-- reason as 0013 (idempotent, public's own result is unaffected).

DO $$
DECLARE
    check_name TEXT;
BEGIN
    SELECT con.conname INTO check_name
    FROM pg_constraint con
    WHERE con.conrelid = 'product_dimension'::regclass
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) ILIKE '%category_path_source%';

    IF check_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE Product_Dimension DROP CONSTRAINT %I', check_name);
    END IF;

    ALTER TABLE Product_Dimension ADD CONSTRAINT product_dimension_category_path_source_check
        CHECK (category_path_source IS NULL OR category_path_source IN
            ('direct_soh_match', 'keyword_rule', 'unclassified', 'source_file_defect'));
END $$;

COMMENT ON COLUMN Product_Dimension.category_path_source IS
    'How category_path was populated for this row: direct_soh_match (most-recent SOH snapshot CATEGORY DESC, ~79% of Unilever demand SKUs), keyword_rule (description-keyword fallback at confidence >= 0.6, validated out-of-sample at 97.4% accuracy), unclassified (failed both - category_path is the literal string ''UNCLASSIFIED'', not NULL - Unilever grain=sku only), source_file_defect (Del Monte grain=category rows whose source Sell Out file held a broken-lookup artifact instead of a real category label - category_path is also the literal string ''UNCLASSIFIED'', revenue preserved via a per-(region,_period) sum, see PHASE1_EXECUTION_PLAN_2026-09.md item 40a), or NULL (not yet processed by the loader / not applicable for this row''s grain). See reports/PROJECT_STATE_2026-09.md §8.';

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_category_path_source_check;
-- ALTER TABLE Product_Dimension ADD CONSTRAINT product_dimension_category_path_source_check
--     CHECK (category_path_source IS NULL OR category_path_source IN
--         ('direct_soh_match', 'keyword_rule', 'unclassified'));
-- COMMIT;
