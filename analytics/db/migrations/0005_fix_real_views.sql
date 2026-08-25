-- analytics/db/migrations/0005_fix_real_views.sql
--
-- Restores every *_Real view to a strict `WHERE is_demo = false`.
--
-- Commit 4df2501 ("Fix SARIMA date and data corruption; Add synthetic
-- inventory and SKU mapping scripts; Fix Del Monte forecast actuals")
-- silently changed Sales_Fact_Real, Purchase_Fact_Real, Inventory_Fact_Real,
-- SellOut_Fact_Real, and SalesReturn_Fact_Real to `WHERE is_demo = false
-- OR principal = 'delmonte'` (Inventory_Fact_Real also got an unconditional
-- `OR principal = 'unilever' AND is_demo = true`, making it filter nothing
-- for either principal). For Del Monte that predicate is always true, so
-- every one of these views stopped excluding synthetic (is_demo=true) rows
-- for Del Monte entirely — exactly the leak the *_Real convention exists to
-- prevent (see schema.sql's own note at the top of the view block: "must
-- never see demo data").
--
-- ALREADY APPLIED live on Supabase by hand (confirmed via pg_get_viewdef
-- against the running instance — every view below already matches this
-- file's definition). This migration exists only because no committed
-- migration ever recorded that fix, and analytics/db/schema.sql's inline
-- CREATE VIEW block (lines 633-649) still had the buggy OR-clauses until
-- this same pass corrected it — see that file's diff alongside this one.
-- Re-running this migration against the live DB is a no-op confirmation,
-- not a behavior change.
--
-- Idempotent: CREATE OR REPLACE VIEW, safe to re-run.

BEGIN;

CREATE OR REPLACE VIEW Sales_Fact_Real AS
SELECT * FROM Sales_Fact WHERE is_demo = false;

CREATE OR REPLACE VIEW Purchase_Fact_Real AS
SELECT * FROM Purchase_Fact WHERE is_demo = false;

CREATE OR REPLACE VIEW Inventory_Fact_Real AS
SELECT * FROM Inventory_Fact WHERE is_demo = false;

CREATE OR REPLACE VIEW SellOut_Fact_Real AS
SELECT * FROM SellOut_Fact WHERE is_demo = false;

CREATE OR REPLACE VIEW Unilever_SKU_Demand_Fact_Real AS
SELECT * FROM Unilever_SKU_Demand_Fact WHERE is_demo = false;

CREATE OR REPLACE VIEW SalesReturn_Fact_Real AS
SELECT * FROM SalesReturn_Fact WHERE is_demo = false;

COMMIT;

-- Rollback (not run, kept for review — reintroduces the leak, never run this):
-- BEGIN;
-- CREATE OR REPLACE VIEW Sales_Fact_Real AS
-- SELECT * FROM Sales_Fact WHERE is_demo = false OR principal = 'delmonte';
-- CREATE OR REPLACE VIEW Purchase_Fact_Real AS
-- SELECT * FROM Purchase_Fact WHERE is_demo = false OR principal = 'delmonte';
-- CREATE OR REPLACE VIEW Inventory_Fact_Real AS
-- SELECT * FROM Inventory_Fact WHERE is_demo = false OR principal = 'delmonte' OR (principal = 'unilever' AND is_demo = true);
-- CREATE OR REPLACE VIEW SellOut_Fact_Real AS
-- SELECT * FROM SellOut_Fact WHERE is_demo = false OR principal = 'delmonte';
-- CREATE OR REPLACE VIEW SalesReturn_Fact_Real AS
-- SELECT * FROM SalesReturn_Fact WHERE is_demo = false OR principal = 'delmonte';
-- COMMIT;
