-- analytics/db/migrations/0017_abc_classification_method_run_id.sql
--
-- Phase 2 ABC re-check (reports/ABC_PHASE2_2026-09.md): adds method/run_id
-- to ABC_Classification so the 'single' (that month's revenue) and 't3m'
-- (trailing 3 months) classification bases can coexist per
-- (product_key, classification_period) instead of overwriting each other.
--
-- run_id is an audit/version tag for the orchestration run that produced a
-- row (see analytics/classification/orchestrate_abc.py's _upsert_abc_
-- classification), not part of the natural key - re-running the same
-- (product_key, period, method) overwrites in place, run_id just records
-- which run last wrote it, same as computed_at.
--
-- Existing rows (all method='single' by construction, no t3m has ever been
-- written) get method='single' and a fixed backfill run_id.
--
-- Backup taken before running: ssm_abc_phase2.abc_classification_backup_20260917
-- (CREATE TABLE ... AS SELECT * FROM public.abc_classification).

BEGIN;

ALTER TABLE ABC_Classification
    ADD COLUMN IF NOT EXISTS method TEXT NOT NULL DEFAULT 'single' CHECK (method IN ('single', 't3m')),
    ADD COLUMN IF NOT EXISTS run_id TEXT NOT NULL DEFAULT 'legacy_pre_0017';

-- Backfill for any row that existed before the DEFAULT was in effect
-- (IF NOT EXISTS above already applies the DEFAULT to existing rows on
-- ADD COLUMN, this UPDATE is a no-op safety net, not required logic).
UPDATE ABC_Classification SET method = 'single' WHERE method IS NULL;
UPDATE ABC_Classification SET run_id = 'legacy_pre_0017' WHERE run_id IS NULL;

-- Natural key widens from (product_key, classification_period) to include
-- method, since single and t3m now legitimately coexist for the same
-- product_key/period.
ALTER TABLE ABC_Classification DROP CONSTRAINT IF EXISTS abc_classification_product_key_classification_period_key;
ALTER TABLE ABC_Classification ADD CONSTRAINT abc_classification_product_key_period_method_key
    UNIQUE (product_key, classification_period, method);

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE ABC_Classification DROP CONSTRAINT IF EXISTS abc_classification_product_key_period_method_key;
-- ALTER TABLE ABC_Classification ADD CONSTRAINT abc_classification_product_key_classification_period_key
--     UNIQUE (product_key, classification_period);
-- ALTER TABLE ABC_Classification DROP COLUMN IF EXISTS method;
-- ALTER TABLE ABC_Classification DROP COLUMN IF EXISTS run_id;
-- COMMIT;
