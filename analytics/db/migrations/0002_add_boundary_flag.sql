-- analytics/db/migrations/0002_add_boundary_flag.sql
--
-- Adds ABC_Classification.boundary_flag (backlog #43: "SKUs sitting near
-- a tier boundary flagged so reclassification is anticipated").
--
-- Origin: this was introduced on the 4ISA-Capstone-Group-7/SSM-DSD
-- (group7) fork's kelvin-etl branch as schema.sql's own comment plus a
-- one-line raw ALTER, never as a tracked migration file:
--   ALTER TABLE ABC_Classification ADD COLUMN IF NOT EXISTS boundary_flag BOOLEAN NOT NULL DEFAULT FALSE;
-- That branch had no visibility into this project's live Supabase
-- instance (confirmed: analytics/classification/orchestrate_abc.py's own
-- docstring says "Not yet run against a live database as of this
-- writing"), so the ALTER was never applied anywhere. Folded into a
-- proper migration here, same tracked-migration discipline as
-- 0001_add_is_demo.sql, so both schema changes are recorded the same way
-- rather than one living only as a comment.
--
-- Verified against the live database before writing this file: all 6
-- fact tables already have is_demo (0001 applied), abc_classification
-- exists with 0 rows and does NOT yet have boundary_flag.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, safe to re-run.

BEGIN;

ALTER TABLE ABC_Classification ADD COLUMN IF NOT EXISTS boundary_flag BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE ABC_Classification DROP COLUMN IF EXISTS boundary_flag;
-- COMMIT;
