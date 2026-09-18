-- analytics/db/migrations/0013_product_dimension_nulls_not_distinct.sql
--
-- Fixes root cause #2 of the 2026-09-15 cutover incident
-- (reports/PROJECT_STATE_2026-09.md §10): Product_Dimension's
-- UNIQUE (principal, grain, sku_code, category_path) constraint is
-- structurally inert for the exact rows it exists to protect.
-- sku_code IS NULL for every category-grain row and category_path IS
-- NULL for every SKU-grain row (by design - schema.sql's own column
-- comments), and standard SQL UNIQUE semantics treat NULL as never
-- equal to NULL - so two rows sharing the same real natural-key parts
-- were never actually detected as duplicates by Postgres, regardless of
-- what analytics/etl/load.py::resolve_dimension_fk()'s ON CONFLICT
-- clause targeted. Confirmed directly (2026-09-15): a repeat INSERT for
-- an existing SKU, sequence state notwithstanding, succeeded as a brand
-- new row instead of being skipped - this is what let the incident
-- silently duplicate 1,807 Unilever SKU rows before a same-batch
-- collision on a Del Monte category finally raised a hard error.
--
-- Fix (PostgreSQL 17.6 confirmed live - NULLS NOT DISTINCT has been
-- available since PG15, Yuan's preferred fix when available): rebuild
-- the same constraint as UNIQUE NULLS NOT DISTINCT. Two NULLs in the
-- same column now compare as equal for uniqueness purposes ONLY for
-- this constraint - every other NULL-comparison in the database (WHERE
-- clauses, joins, other constraints) is completely unaffected, this is
-- purely an index-level distinctness rule. The existing ON CONFLICT
-- (principal, grain, sku_code, category_path) DO NOTHING clause in
-- load.py needs NO code change - inference matches on the column list,
-- which is unchanged; only the distinctness semantics of the underlying
-- index changed.
--
-- Does NOT touch the data itself - NULL stays NULL in sku_code/
-- category_path, never replaced with a sentinel string (that would
-- break every downstream query that filters/groups on these columns
-- expecting a real NULL, e.g. "SELECT ... WHERE sku_code IS NULL" for
-- category-grain rows).

BEGIN;

-- FIXED 2026-09-17 (found while doing the item-1/item-3 scratch dry-run for
-- the column-gap audit, unrelated to that work's actual scope): both
-- lookups below used to join pg_class ON relname = 'product_dimension'
-- with NO schema/namespace qualification - on a server where other
-- schemas also have a table literally named product_dimension (this
-- project always has at least ssm_canonical / ssm_precutover_diag lying
-- around per reports/PROJECT_STATE_2026-09.md), that query matches EVERY
-- schema's product_dimension at once. Reproduced directly: applying this
-- migration to a brand-new scratch schema while ssm_canonical's
-- product_dimension still carried an old-style (non-NULLS-NOT-DISTINCT)
-- constraint made check_name resolve to a name that also existed (same
-- auto-generated name, different table) on the NEW schema - the
-- unqualified `ALTER TABLE Product_Dimension DROP CONSTRAINT %I` then
-- dropped the brand-new schema's own just-created NULLS NOT DISTINCT
-- constraint instead, and the ADD branch's own unscoped EXISTS check found
-- some OTHER schema's NND constraint and concluded (wrongly) that this
-- schema didn't need one added. Net effect: every from-scratch scratch
-- build silently ended up with NO unique constraint at all on
-- product_dimension - never caught before because no prior full rebuild
-- had exercised the grain='category' insert path this deep in one run.
-- Fix: 'product_dimension'::regclass resolves via search_path to the ONE
-- table actually in scope for this session (the schema
-- ensure_scratch_schema() set via SET LOCAL search_path just before this
-- file runs), never another schema's table of the same name. Safe to edit
-- this already-applied-to-public migration in place (not a new migration
-- number): public's own constraint was already correct NND before and
-- after this fix (this bug only manifests when 2+ product_dimension
-- tables coexist across schemas, which was never public's situation), and
-- the DO block's logic is idempotent either way - this changes future
-- re-applications to fresh scratch schemas, not anything that already
-- happened to public.

DO $$
DECLARE
    check_name TEXT;
BEGIN
    SELECT con.conname INTO check_name
    FROM pg_constraint con
    WHERE con.conrelid = 'product_dimension'::regclass
      AND con.contype = 'u'
      AND pg_get_constraintdef(con.oid) LIKE 'UNIQUE (principal, grain, sku_code, category_path)%'
      AND pg_get_constraintdef(con.oid) NOT LIKE '%NULLS NOT DISTINCT%';

    IF check_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE Product_Dimension DROP CONSTRAINT %I', check_name);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint con
        WHERE con.conrelid = 'product_dimension'::regclass
          AND con.contype = 'u'
          AND pg_get_constraintdef(con.oid) LIKE '%NULLS NOT DISTINCT%'
    ) THEN
        ALTER TABLE Product_Dimension
            ADD CONSTRAINT product_dimension_principal_grain_sku_code_category_path_key
            UNIQUE NULLS NOT DISTINCT (principal, grain, sku_code, category_path);
    END IF;
END $$;

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_principal_grain_sku_code_category_path_key;
-- ALTER TABLE Product_Dimension ADD CONSTRAINT product_dimension_principal_grain_sku_code_category_path_key
--     UNIQUE (principal, grain, sku_code, category_path);
-- COMMIT;
