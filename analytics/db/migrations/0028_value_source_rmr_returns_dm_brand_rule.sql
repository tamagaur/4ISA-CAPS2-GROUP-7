-- analytics/db/migrations/0028_value_source_rmr_returns_dm_brand_rule.sql
--
-- Provenance columns for three Del Monte data fixes (Yuan, 2026-09-28; applied by
-- scripts/apply_dm_fixes_to_public.py batches 3, 4 and 6). All additive.
--
-- 1. Inventory_Fact.valuation_source
--    The Feb-2023 Ilocos and Mar-2023 Pangasinan sign-off sheets carry Cost but no Valuation
--    column (209 real rows). Valuation is set to Cost there - on all 4,936 real Del Monte rows
--    carrying both, Valuation = Cost exactly - and marked 'derived_cost' so it is never read as
--    an SSM-reported figure. NULL = the value is the source's own.
--
-- 2. SalesReturn_Fact: source, _row_ordinal, invoice_date, customer_name
--    No monthly sales-return file exists for Oct and Nov 2025. Their return lines are loaded from
--    the RMR GS & BO export's GS and BO sheets (the ONE PAGER sheet is the union of the two and
--    is not loaded), tagged source = 'rmr'. NULL = the monthly sales-return file.
--    An RMR line has no Invoice Num, so the existing key (return_slip_num, principal, region,
--    invoice_num) never fires on it; its own key is the partial unique index below:
--    file + sheet (GS/BO) + source row + date + customer + amount.
--    invoice_date holds the source's "Invoice Date" (the original sale date, NOT the return date;
--    return_date stays NULL, as on every real row - config/column_maps/sales_return.yaml).
--
--    DEDUPE RULE, for when a proper Oct/Nov 2025 sales-return file arrives: that file is the
--    system of record. Every source = 'rmr' row whose (principal, region, return_slip_num,
--    return_type) matches a row of that file is deleted; if the matched rows' net_amount differ,
--    both go to etl_quarantine for review instead of either being kept. RMR rows with no match
--    stay. RMR lines with no Return Slip # are never loaded (etl_quarantine) - this rule needs
--    the slip.
--
-- 3. Product_Dimension.brand_source: allow 'dm_name_first_token_rule'
--    Del Monte SKU brand from the product name's first token through
--    config/alias_tables/delmonte_brand.csv - the same shape as Unilever's D11 rule (0026).
--
-- The _Real views are SELECT * expanded when created, so the two affected ones are re-created
-- to pick up the new columns (appended at the end), as 0027 did.

BEGIN;

ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS valuation_source TEXT;
ALTER TABLE Inventory_Fact DROP CONSTRAINT IF EXISTS inventory_fact_valuation_source_check;
ALTER TABLE Inventory_Fact ADD CONSTRAINT inventory_fact_valuation_source_check
    CHECK (valuation_source IS NULL OR valuation_source IN ('derived_cost'));
COMMENT ON COLUMN Inventory_Fact.valuation_source IS
    'NULL: valuation is the source''s own figure. derived_cost: the sheet had no Valuation column and valuation was set to cost (Valuation = Cost on every real Del Monte row carrying both).';

ALTER TABLE SalesReturn_Fact ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE SalesReturn_Fact ADD COLUMN IF NOT EXISTS _row_ordinal BIGINT;
ALTER TABLE SalesReturn_Fact ADD COLUMN IF NOT EXISTS invoice_date DATE;
ALTER TABLE SalesReturn_Fact ADD COLUMN IF NOT EXISTS customer_name TEXT;
ALTER TABLE SalesReturn_Fact DROP CONSTRAINT IF EXISTS salesreturn_fact_source_check;
ALTER TABLE SalesReturn_Fact ADD CONSTRAINT salesreturn_fact_source_check
    CHECK (source IS NULL OR source IN ('rmr'));
CREATE UNIQUE INDEX IF NOT EXISTS uq_salesreturn_fact_rmr_line
    ON SalesReturn_Fact (_src_file, _src_sheet, _row_ordinal, invoice_date, customer_name, net_amount)
    WHERE source = 'rmr';
COMMENT ON COLUMN SalesReturn_Fact.source IS
    'NULL: the monthly sales-return file (system of record). rmr: a GS/BO line of the RMR GS & BO export, loaded only for a month with no sales-return file; superseded by that file if it arrives (dedupe rule in migration 0028).';
COMMENT ON COLUMN SalesReturn_Fact.invoice_date IS
    'The source''s "Invoice Date" - the original sale date, not the return date. Set on source = ''rmr'' rows, where it is part of the line key.';

ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_brand_source_check;
ALTER TABLE Product_Dimension
    ADD CONSTRAINT product_dimension_brand_source_check
    CHECK (brand_source IS NULL OR brand_source IN ('soh_first_token_rule', 'demand_first_token_rule', 'dm_name_first_token_rule'));

CREATE OR REPLACE VIEW Inventory_Fact_Real AS
SELECT * FROM Inventory_Fact WHERE is_demo = false;

CREATE OR REPLACE VIEW SalesReturn_Fact_Real AS
SELECT * FROM SalesReturn_Fact WHERE is_demo = false;

COMMIT;

-- Rollback (not run, kept for review; the CHECK step fails while any row holds the new value):
-- BEGIN;
-- DROP VIEW IF EXISTS Inventory_Fact_Real, SalesReturn_Fact_Real;
-- DROP INDEX IF EXISTS uq_salesreturn_fact_rmr_line;
-- ALTER TABLE Inventory_Fact DROP COLUMN IF EXISTS valuation_source;
-- ALTER TABLE SalesReturn_Fact DROP COLUMN IF EXISTS source, DROP COLUMN IF EXISTS _row_ordinal,
--     DROP COLUMN IF EXISTS invoice_date, DROP COLUMN IF EXISTS customer_name;
-- ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_brand_source_check;
-- ALTER TABLE Product_Dimension ADD CONSTRAINT product_dimension_brand_source_check
--     CHECK (brand_source IS NULL OR brand_source IN ('soh_first_token_rule', 'demand_first_token_rule'));
-- then re-create the two views exactly as analytics/db/schema.sql declares them.
-- COMMIT;
