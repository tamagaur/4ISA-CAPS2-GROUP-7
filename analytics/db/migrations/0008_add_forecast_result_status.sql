-- analytics/db/migrations/0008_add_forecast_result_status.sql
--
-- Adds Forecast_Result.status so scripts/run_sarima.py can stop fabricating
-- mape = 15.0 ("Mock passing MAPE") for SKUs it never actually evaluated
-- (insufficient history, or a fit that raised an exception). NULL mape
-- alone can't distinguish "insufficient data" from "fit failed" from
-- "dead SKU" from "the guard clamped an exploded forecast" — status makes
-- that explicit instead.
--
-- Follows the existing status-column convention on LP_Recommendation
-- (schema.sql: status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
-- ('pending','accepted','dismissed'))).
--
-- NOT YET APPLIED to Supabase as of writing this file — run this by hand
-- (Supabase SQL editor or psql against SUPABASE_DB_URL). schema.sql's
-- from-scratch definition has been updated to match.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, safe to re-run.

BEGIN;

ALTER TABLE Forecast_Result ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ok'
    CHECK (status IN ('ok', 'insufficient_data', 'dead_sku', 'fit_failed', 'unreliable'));

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE Forecast_Result DROP COLUMN IF EXISTS status;
-- COMMIT;
