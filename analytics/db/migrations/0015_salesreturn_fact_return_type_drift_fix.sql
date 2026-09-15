-- analytics/db/migrations/0015_salesreturn_fact_return_type_drift_fix.sql
--
-- Fixes live-only schema drift found 2026-09-16 diagnosing the cutover's
-- salesreturn_fact row-count MISMATCH (1,630 expected / 865 actual):
-- live public.SalesReturn_Fact.return_type carried a NOT NULL constraint
-- that schema.sql never declared (schema.sql:278 -
-- `return_type TEXT CHECK (return_type IS NULL OR return_type IN ('GS', 'BO'))`,
-- nullable by design - return_type is legitimately NULL for ~55% of the
-- real corpus, sheets that don't distinguish GS/BO, per migration 0011's
-- own analysis) and no migration (0011 included) ever added. It was
-- excluding 789 rows (771 real) at load time via
-- _drop_rows_violating_other_not_null() (scripts/run_canonical_load.py) -
-- confirmed via direct reproduction: return_type was the ONLY null column
-- in every one of those 789 rows.
--
-- Root cause: CREATE TABLE IF NOT EXISTS (schema.sql's own pattern) never
-- touches an already-existing table's column constraints. This table was
-- first created ad-hoc, before this canonical schema/migration history
-- existed, with return_type NOT NULL baked in - every later schema.sql/
-- migration apply silently left that live-only constraint in place,
-- masked by IF NOT EXISTS, never actually reconciled against what the
-- code declared. Confirmed via a full information_schema NOT NULL sweep
-- (public vs. a fresh schema.sql+migrations build) that this was the only
-- instance of the same drift class besides the already-known
-- manual_reorder_point (a live-only column with no schema.sql entry at
-- all - a different kind of drift, not addressed by this migration).

BEGIN;

ALTER TABLE SalesReturn_Fact ALTER COLUMN return_type DROP NOT NULL;

COMMIT;

-- Rollback (not run, kept for review - re-adds the drift, do not use
-- except to reproduce the pre-fix state for testing):
-- BEGIN;
-- ALTER TABLE SalesReturn_Fact ALTER COLUMN return_type SET NOT NULL;
-- COMMIT;
