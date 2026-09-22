-- analytics/db/migrations/0027_invoice_quantities_and_sellout_tax_flag.sql
--
-- Adds columns for three source columns the canonical load was dropping
-- (reports/dropped_columns_2026-09-21.csv, items X2-X4; approved by Yuan
-- 2026-09-22):
--   Sales_Fact.quantity_cases / quantity_pieces       <- sales register "Total CAS" / "Total PCS"
--   SalesReturn_Fact.quantity_cases / quantity_pieces <- sales return GS/BO "Total CAS" / "Total PCS"
--   SellOut_Fact.net_amount_tax_inclusive             <- which amount column net_amount came from
--
-- The quantities are invoice totals across mixed products, reported as two
-- separate counts. Neither file has a SKU or pack-size column, so they are
-- never combined: SalesReturn_Fact.bo_units stays NULL (a bad-order return
-- is marked by return_type = 'BO' only).
--
-- net_amount_tax_inclusive: TRUE where the sell-out sheet's only amount was
-- "Total With Tax" (the two August 2023 sheets), FALSE where it came from
-- "Total Without Tax", NULL where neither was present.
--
-- No CHECK constraints on the new columns (Yuan, 2026-09-22). Staged range
-- when added: sales register cases 0..3600, pieces 0..289; sales return
-- cases 0..110, pieces 0..179; no negatives.
--
-- The _Real views are SELECT * and were expanded when created, so they are
-- re-created here to pick up the new columns (appended at the end).

BEGIN;

ALTER TABLE Sales_Fact ADD COLUMN IF NOT EXISTS quantity_cases NUMERIC(14,2);
ALTER TABLE Sales_Fact ADD COLUMN IF NOT EXISTS quantity_pieces NUMERIC(14,2);
ALTER TABLE SalesReturn_Fact ADD COLUMN IF NOT EXISTS quantity_cases NUMERIC(14,2);
ALTER TABLE SalesReturn_Fact ADD COLUMN IF NOT EXISTS quantity_pieces NUMERIC(14,2);
ALTER TABLE SellOut_Fact ADD COLUMN IF NOT EXISTS net_amount_tax_inclusive BOOLEAN;

COMMENT ON COLUMN Sales_Fact.quantity_cases IS
    'invoice-level total across mixed products; not a SKU quantity; cases and pieces are not additive.';
COMMENT ON COLUMN Sales_Fact.quantity_pieces IS
    'invoice-level total across mixed products; not a SKU quantity; cases and pieces are not additive.';
COMMENT ON COLUMN SalesReturn_Fact.quantity_cases IS
    'invoice-level total across mixed products; not a SKU quantity; cases and pieces are not additive.';
COMMENT ON COLUMN SalesReturn_Fact.quantity_pieces IS
    'invoice-level total across mixed products; not a SKU quantity; cases and pieces are not additive.';
COMMENT ON COLUMN SellOut_Fact.net_amount_tax_inclusive IS
    'TRUE: net_amount is the source''s "Total With Tax" (its only amount column). FALSE: "Total Without Tax". NULL: neither present.';

CREATE OR REPLACE VIEW Sales_Fact_Real AS
SELECT * FROM Sales_Fact WHERE is_demo = false;

CREATE OR REPLACE VIEW SalesReturn_Fact_Real AS
SELECT * FROM SalesReturn_Fact WHERE is_demo = false;

CREATE OR REPLACE VIEW SellOut_Fact_Real AS
SELECT * FROM SellOut_Fact WHERE is_demo = false;

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DROP VIEW IF EXISTS Sales_Fact_Real, SalesReturn_Fact_Real, SellOut_Fact_Real;
-- ALTER TABLE Sales_Fact DROP COLUMN IF EXISTS quantity_cases, DROP COLUMN IF EXISTS quantity_pieces;
-- ALTER TABLE SalesReturn_Fact DROP COLUMN IF EXISTS quantity_cases, DROP COLUMN IF EXISTS quantity_pieces;
-- ALTER TABLE SellOut_Fact DROP COLUMN IF EXISTS net_amount_tax_inclusive;
-- then re-create the three views exactly as analytics/db/schema.sql declares them.
-- COMMIT;
