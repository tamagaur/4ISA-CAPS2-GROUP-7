-- analytics/db/migrations/0009_add_soh_columns.sql
--
-- Unilever SOH inventory Load (2026-08) — R11/R12.
--
-- R11: unit_cost_per_case NUMERIC — Unilever's Last Purchase Price
-- (GSV/CS) is a per-case unit price (the header says so directly:
-- "GSV/CS"), confirmed NOT the same thing as Del Monte's existing `cost`
-- column, which is an extended peso total equal to `valuation` (R10:
-- verified 584 rows Cost==Valuation in the 2025 layout, plus the totals
-- row). Mapping Unilever's per-case price into `cost` would silently
-- mix two different units under one column name — R10 says do not do
-- that. This is a new, separate column instead.
--
-- R12: blocked_qty_cases, blocked_qty_pieces NUMERIC, stock_status TEXT
-- — the dead-stock signal (Blocked Stock (CS/PC) + Status) flagged in
-- this session's Transform report as needed downstream but having no
-- existing home. Added now rather than left as a further-flagged gap.
--
-- Also backfills schema.sql's Inventory_Fact CREATE TABLE with
-- `valuation` and `cost` — both already live on Supabase (valuation via
-- migrations/0004_add_valuation.sql; cost added live, ad hoc, at some
-- earlier point with NO migration file ever tracking it — confirmed via
-- live information_schema query this session, 2026-08-27) but never
-- present in schema.sql's from-scratch CREATE TABLE. Documented in
-- schema.sql directly; this migration does not touch either column's
-- data (ADD COLUMN IF NOT EXISTS is a no-op against the live DB, since
-- both already exist there — this file exists so schema.sql and any
-- fresh from-scratch build match what's actually live, and so `cost`
-- finally has a tracked migration instead of being pure undocumented
-- drift).
--
-- Recreates Inventory_Fact_Real with the new columns exposed — the view
-- is `SELECT *`, so this is really just re-asserting the is_demo=false
-- filter verbatim (unchanged) after the ALTERs above.

BEGIN;

-- Backfill: already live, tracked here for the first time (see note above).
ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS valuation NUMERIC;
ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS cost      NUMERIC;

-- R11
ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS unit_cost_per_case NUMERIC;

-- R12
ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS blocked_qty_cases  NUMERIC;
ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS blocked_qty_pieces NUMERIC;
ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS stock_status       TEXT;

-- is_demo=false filter preserved verbatim (unchanged from
-- migrations/0004_add_valuation.sql / 0005_fix_real_views.sql) — SELECT *
-- means the 5 new/backfilled columns above are exposed automatically.
CREATE OR REPLACE VIEW Inventory_Fact_Real AS
SELECT * FROM Inventory_Fact WHERE is_demo = false;

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- CREATE OR REPLACE VIEW Inventory_Fact_Real AS
-- SELECT * FROM Inventory_Fact WHERE is_demo = false;
-- ALTER TABLE Inventory_Fact DROP COLUMN IF EXISTS stock_status;
-- ALTER TABLE Inventory_Fact DROP COLUMN IF EXISTS blocked_qty_pieces;
-- ALTER TABLE Inventory_Fact DROP COLUMN IF EXISTS blocked_qty_cases;
-- ALTER TABLE Inventory_Fact DROP COLUMN IF EXISTS unit_cost_per_case;
-- -- valuation/cost predate this migration on the live DB — do NOT drop
-- -- them as part of rolling this migration back, only the new R11/R12
-- -- columns above.
-- COMMIT;
