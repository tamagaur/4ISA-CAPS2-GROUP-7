-- analytics/db/migrations/0002_add_sku_management_fields.sql
--
-- Adds the columns GET/POST/PATCH /sku (backend/routers/sku.py) needs to
-- manage SKU master data for real, replacing SKUManagement.jsx's hardcoded
-- UNILEVER_SKUS/DELMONTE_CATEGORIES arrays. schema.sql's from-scratch
-- Product_Dimension definition has been updated to match; this file is the
-- incremental ALTER path for a database that's already running.
--
-- NOT YET APPLIED to Supabase — run this by hand (Supabase SQL editor or
-- psql against SUPABASE_DB_URL) before deploying backend/routers/sku.py.
--
-- Safety: every ADD COLUMN either allows NULL or has a DEFAULT, so existing
-- Product_Dimension rows backfill cleanly with no separate UPDATE needed.

BEGIN;

ALTER TABLE Product_Dimension ADD COLUMN IF NOT EXISTS unit_price NUMERIC(14,2);
ALTER TABLE Product_Dimension ADD COLUMN IF NOT EXISTS lead_time_days INTEGER;
ALTER TABLE Product_Dimension ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'DISABLED'));
ALTER TABLE Product_Dimension ADD COLUMN IF NOT EXISTS notes TEXT;

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE Product_Dimension DROP COLUMN IF EXISTS notes;
-- ALTER TABLE Product_Dimension DROP COLUMN IF EXISTS status;
-- ALTER TABLE Product_Dimension DROP COLUMN IF EXISTS lead_time_days;
-- ALTER TABLE Product_Dimension DROP COLUMN IF EXISTS unit_price;
-- COMMIT;
