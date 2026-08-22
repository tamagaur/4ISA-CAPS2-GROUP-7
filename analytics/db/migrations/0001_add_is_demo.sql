-- analytics/db/migrations/0001_add_is_demo.sql
--
-- Phase 4 (2026-08) — make is_demo load-bearing.
--
-- APPLIED to Supabase (2026-08-20, this session). 77,859 synthetic rows
-- across 5 fact tables were loaded (Sales_Fact, Purchase_Fact,
-- Inventory_Fact, SellOut_Fact, Unilever_SKU_Demand_Fact), alongside
-- 49,916 real rows, and verified: every _Real view returns 0 is_demo=true
-- rows, and a transactional DELETE WHERE is_demo=true + ROLLBACK test
-- confirmed the split is surgical (see reports/POST_LOAD_VERIFICATION.md).
-- schema.sql has been updated to match this file's full scope on a
-- from-scratch build; this file is the equivalent incremental ALTER path
-- for a database that's already running, kept idempotent so re-running it
-- against the live DB (which already has every object below) is a no-op.
--
-- Context: is_demo is baked into every row of the adviser-sanctioned
-- synthetic demo corpus (data/raw/Synthetic Data/, 374 files, plus this
-- session's backfill - see reports/SYNTHETIC_DATA_AUDIT.md) but until
-- this migration, no table had anywhere to put it and no query could
-- filter on it. Without this, there is no way to purge synthetic rows
-- once SSM delivers real files to replace them.
--
-- Safety: DEFAULT false means every row that predates this column (all
-- real, since nothing synthetic had been loaded before this session)
-- keeps is_demo = false automatically when the column is added. Postgres
-- backfills the DEFAULT for all existing rows as part of ALTER TABLE -
-- no separate UPDATE statement needed, and nothing here can accidentally
-- mark a real row as demo data.
--
-- Verified against the live database this session: a real row's INSERT
-- never specifies is_demo at all, because analytics/etl/load.py's
-- load_to_supabase() only includes DataFrame columns that exist in BOTH
-- the DataFrame and the target table (df_columns = [c for c in
-- df.columns if c in table_columns]) - real Extract output never
-- produces an is_demo raw column (no real source file has that header),
-- so Transform's apply_column_map() leaves the canonical is_demo field
-- absent from a real row's DataFrame entirely. The resulting
-- INSERT/upsert statement omits the column, and Postgres applies this
-- DEFAULT, not application code. Confirmed both by code inspection and
-- by the live load: is_demo=false counts (49,916) exactly match real row
-- counts across all 5 fact tables, with zero drift.

BEGIN;

ALTER TABLE Sales_Fact               ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE Purchase_Fact            ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE Inventory_Fact           ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE SellOut_Fact             ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT false;

-- Added live, ad hoc, during this session's Load phase - folded into
-- this migration now so the tracked file matches what's actually applied.
ALTER TABLE Unilever_SKU_Demand_Fact ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE SalesReturn_Fact         ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT false;

CREATE OR REPLACE VIEW Sales_Fact_Real               AS SELECT * FROM Sales_Fact               WHERE is_demo = false;
CREATE OR REPLACE VIEW Purchase_Fact_Real            AS SELECT * FROM Purchase_Fact            WHERE is_demo = false;
CREATE OR REPLACE VIEW Inventory_Fact_Real           AS SELECT * FROM Inventory_Fact           WHERE is_demo = false;
CREATE OR REPLACE VIEW SellOut_Fact_Real             AS SELECT * FROM SellOut_Fact             WHERE is_demo = false;
CREATE OR REPLACE VIEW Unilever_SKU_Demand_Fact_Real AS SELECT * FROM Unilever_SKU_Demand_Fact WHERE is_demo = false;
CREATE OR REPLACE VIEW SalesReturn_Fact_Real         AS SELECT * FROM SalesReturn_Fact         WHERE is_demo = false;

-- Inventory_Fact schema drift fix - added live, ad hoc, during this
-- session's Load phase (the live table predated these two columns being
-- added to schema.sql's from-scratch definition). Folded in here for the
-- same reason as the two is_demo ALTERs above: this file should describe
-- exactly what's live, not just the original 4-table is_demo scope.
ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS _period TEXT;
ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS quantity_pieces NUMERIC(14,2);

-- Supplier_Dimension seed - added live, ad hoc, during this session's
-- Load phase (Purchase_Fact's supplier_key FK needs a row to resolve
-- against; resolve_dimension_fk() can't insert-or-lookup here because
-- supplier_name is NOT NULL but outside the natural key used for the
-- lookup - see reports/POST_LOAD_VERIFICATION.md's load-driver notes).
-- ON CONFLICT (principal) is safe: principal is UNIQUE, matching how
-- the live one-time seed script performed this same insert.
INSERT INTO Supplier_Dimension (supplier_name, principal) VALUES
    ('Del Monte Philippines', 'delmonte'),
    ('Unilever Philippines', 'unilever')
ON CONFLICT (principal) DO NOTHING;

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DELETE FROM Supplier_Dimension WHERE principal IN ('delmonte', 'unilever');
-- ALTER TABLE Inventory_Fact DROP COLUMN IF EXISTS quantity_pieces;
-- ALTER TABLE Inventory_Fact DROP COLUMN IF EXISTS _period;
-- DROP VIEW IF EXISTS SalesReturn_Fact_Real;
-- DROP VIEW IF EXISTS Unilever_SKU_Demand_Fact_Real;
-- DROP VIEW IF EXISTS SellOut_Fact_Real;
-- DROP VIEW IF EXISTS Inventory_Fact_Real;
-- DROP VIEW IF EXISTS Purchase_Fact_Real;
-- DROP VIEW IF EXISTS Sales_Fact_Real;
-- ALTER TABLE SalesReturn_Fact         DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE Unilever_SKU_Demand_Fact DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE SellOut_Fact             DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE Inventory_Fact           DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE Purchase_Fact            DROP COLUMN IF EXISTS is_demo;
-- ALTER TABLE Sales_Fact               DROP COLUMN IF EXISTS is_demo;
-- COMMIT;
