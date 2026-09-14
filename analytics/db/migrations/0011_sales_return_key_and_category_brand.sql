-- analytics/db/migrations/0011_sales_return_key_and_category_brand.sql
--
-- Schema/DDL only, per the 0010 precedent — data backfills are NOT embedded
-- here as inline SQL (not reviewable/practical as giant VALUES lists). This
-- migration adds columns/constraints; scripts/run_canonical_load.py (Phase
-- 1d, not yet written) is what actually populates category_path/brand and
-- their new *_source columns during Load, reusing the direct-match +
-- keyword-fallback logic already validated in Phase 0
-- (reports/PROJECT_STATE_2026-09.md §8). NOT run against the live DB yet —
-- drafted for review (Yuan, 2026-09-11), matching Phase 1's "no DB writes"
-- constraint for this session.
--
-- 1. SalesReturn_Fact key: drop return_type, add invoice_num.
--
-- Tested against real data 2026-09-11 (reports/PHASE1_EXECUTION_PLAN_2026-09.md
-- step 2c, item 21) before this was written, per Yuan's instruction to
-- verify rather than assume: ran both candidates against the real, clean
-- 1,383-row sales_return corpus.
--   (a) DROP return_type from the key entirely: 1 colliding group, 3 rows.
--   (b) COALESCE(return_type, '') in the key: 1 colliding group, 3 rows.
-- Identical result - return_type adds no discriminating power beyond what
-- invoice_num already provides once invoice_num is in the key (it wasn't,
-- until source_of_truth.yaml was widened 2026-09-11 - see that file's
-- sales_return.both comment). The one collision in both cases was 3
-- genuinely blank rows (no slip, no invoice, no amount, no date - not
-- real returns), now excluded before dedup by
-- transform.exclude_sales_return_header_rows()'s third check (added
-- 2026-09-11, same commit as this migration).
--
-- Chose (a) - DROP, not COALESCE - because it's empirically equivalent and
-- simpler DDL (a plain UNIQUE constraint, no expression index). This also
-- recovers the pre-2025 `data`-shaped sheets: those rows never populated
-- return_type at all (~55% of the real corpus, confirmed structural, not
-- an anomaly - schema.sql's own prior comment on this table already
-- flagged the gap, just never verified against real data before now),
-- so today those ~765 real rows are individually quarantined by
-- transform.dedup_facts()'s null-key handling purely because return_type
-- is null on them. Once this migration lands and the loader passes the
-- new 4-column key, those rows resolve normally instead - re-verified
-- 2026-09-11: with return_type dropped from the key, real quarantine count
-- drops from 773 to 8 (only rows genuinely missing return_slip_num or
-- invoice_num), conflict groups stay 0.
--
-- Old constraint name confirmed live (read-only query, 2026-09-11):
-- salesreturn_fact_return_slip_num_principal_region_return_ty_key.
--
-- 2/3. Product_Dimension.category_path_source / brand_source.
--
-- Requested by Yuan (2026-09-11): record HOW each SKU's category_path/brand
-- was populated, not just the value, so the 79% direct / fallback /
-- UNCLASSIFIED split (and "brand came from a committed rule, not ad-hoc")
-- is queryable afterward instead of recomputed by re-running the backfill
-- logic and diffing. Both nullable (a row not yet processed by the loader
-- has NULL, distinguishable from "processed, genuinely unclassifiable").
--
-- 4. Inventory_Fact.quantity_on_hand unit comment.
--
-- transform_ssis_soh.py:226 loads this from `stock_qty_cases` - it has
-- always been cases, but no column carried that fact explicitly before now
-- (plan doc §1c). Comment only, no data/type change - existing values are
-- already correct, just previously undocumented in the schema itself.

BEGIN;

-- 1
-- Postgres has no ADD CONSTRAINT IF NOT EXISTS - unlike every ADD COLUMN
-- below, a bare ADD CONSTRAINT is not idempotent and raises DuplicateTable
-- on a second run against a schema that already has it (caught 2026-09-14,
-- the first time this migration was re-applied to an already-migrated
-- ssm_canonical - the scratch-drop rollback fired correctly, confirming
-- that design still works, but re-running the FULL migration set from
-- scratch on top of prior progress is a normal, expected case for a
-- scratch schema, so this needed fixing here, not worked around in the
-- loader). Guarded with a catalog check, matching the ADD COLUMN IF NOT
-- EXISTS idiom used everywhere else in this file.
DO $$
BEGIN
    ALTER TABLE SalesReturn_Fact
        DROP CONSTRAINT IF EXISTS salesreturn_fact_return_slip_num_principal_region_return_ty_key;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'salesreturn_fact_slip_principal_region_invoice_key'
          AND conrelid = 'SalesReturn_Fact'::regclass
    ) THEN
        ALTER TABLE SalesReturn_Fact
            ADD CONSTRAINT salesreturn_fact_slip_principal_region_invoice_key
            UNIQUE (return_slip_num, principal, region, invoice_num);
    END IF;
END $$;

-- 2
ALTER TABLE Product_Dimension ADD COLUMN IF NOT EXISTS category_path_source TEXT
    CHECK (category_path_source IS NULL OR category_path_source IN
        ('direct_soh_match', 'keyword_rule', 'unclassified'));
COMMENT ON COLUMN Product_Dimension.category_path_source IS
    'How category_path was populated for this row: direct_soh_match (most-recent SOH snapshot CATEGORY DESC, ~79% of Unilever demand SKUs), keyword_rule (description-keyword fallback at confidence >= 0.6, validated out-of-sample at 97.4% accuracy), unclassified (failed both - category_path is the literal string ''UNCLASSIFIED'', not NULL), or NULL (not yet processed by the loader / not applicable for this row''s grain). See reports/PROJECT_STATE_2026-09.md §8.';

-- 3
ALTER TABLE Product_Dimension ADD COLUMN IF NOT EXISTS brand_source TEXT
    CHECK (brand_source IS NULL OR brand_source IN ('soh_first_token_rule'));
COMMENT ON COLUMN Product_Dimension.brand_source IS
    'How brand was populated: soh_first_token_rule (first whitespace-delimited token of the SOH article_description, normalized through a committed alias table, config/alias_tables/unilever_brand.csv) or NULL (not yet processed / not applicable). Previously written by no code at all - this makes the source reproducible and auditable, not ad hoc.';

-- 4
COMMENT ON COLUMN Inventory_Fact.quantity_on_hand IS
    'UNIT: CASES, not pieces. Loaded from stock_qty_cases (transform_ssis_soh.py). Consumers needing pieces must multiply by Product_Dimension.pack_size - confirmed done in dashboard.py and the trapped-capital calc; verify any new consumer does the same.';

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE Product_Dimension DROP COLUMN IF EXISTS brand_source;
-- ALTER TABLE Product_Dimension DROP COLUMN IF EXISTS category_path_source;
-- ALTER TABLE SalesReturn_Fact
--     DROP CONSTRAINT IF EXISTS salesreturn_fact_slip_principal_region_invoice_key;
-- ALTER TABLE SalesReturn_Fact
--     ADD CONSTRAINT salesreturn_fact_return_slip_num_principal_region_return_ty_key
--     UNIQUE (return_slip_num, principal, region, return_type);
-- COMMENT ON COLUMN Inventory_Fact.quantity_on_hand IS NULL;
-- COMMIT;
