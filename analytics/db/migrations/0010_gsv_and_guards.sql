-- analytics/db/migrations/0010_gsv_and_guards.sql
--
-- Schema/DDL only. Per-row backfills (gsv for 44,575 Unilever SKU demand
-- rows; days_offset/demand_period for 27,282 real Unilever SOH inventory
-- rows) are NOT embedded here as inline SQL — a 44,575-row UPDATE keyed
-- on (sku_code, calendar_month) from staging/unilever_sku/*.parquet data
-- isn't reviewable or practical as a giant VALUES list. Run
-- scratch/backfill_0010.py immediately after this migration applies;
-- it performs both backfills via SQLAlchemy from the same staged parquet
-- data this session's Extract/Transform work already produced. Verify
-- non-null counts after both steps — see that script's own report.
--
-- 1. Duplicate guard (2026-08-27 finding): there was previously no DB-
-- level guard against duplicate Unilever SOH rows — dedup lived only in
-- Transform (analytics/etl/transform_ssis_soh.py's dedup_facts() call).
-- If a teammate pulled and re-ran the loader, every SOH figure would
-- silently double. Verified live, immediately before this migration
-- (2026-08-27): 0 duplicate (sku_code, snapshot_date, COALESCE(region,''),
-- is_demo) groups for principal='unilever' — this index is expected to
-- apply cleanly, not act as a cleanup/dedup step. If it fails, that means
-- real duplicates exist that this session's verification missed; STOP
-- and report them, do not add a workaround here to force it through.
--
-- 2. GSV (Gross Sales Value) — the OTHER money column in the La Union
-- source (config/column_maps/unilever_sku.yaml already maps raw "GSV" to
-- canonical `gsv`, but Unilever_SKU_Demand_Fact never had a column for
-- it — see reports/ADVISER_EVIDENCE.md-adjacent finding from the prior
-- session: net_amount is populated from "Total Sales Amt Inc. Tax", NOT
-- GSV; GSV was silently dropped at Load, never at Extract). Backfilled
-- from the RAW GSV column, never derived/calculated from net_amount —
-- they are two different reported figures (GSV is the pre-tax/pre-
-- discount figure; net_amount is inclusive of tax), not one field
-- expressible in terms of the other.
--
-- 3. days_offset / demand_period — Unilever SOH's snapshot_date (R5) is
-- a REAL date (unlike Del Monte's synthetic first-of-month
-- snapshot_date), but it's still provenance, not the join key —
-- _period is (see decision register, ARCHITECTURE.md). days_offset
-- makes that provenance auditable (how many days past month-end did
-- this snapshot actually land — expected 1-5 per the SOH discovery
-- pass, flagged if outside that). demand_period is _period's own
-- successor month, precomputed so a consumer doesn't have to re-derive
-- "which sales month does this inventory snapshot logically follow" by
-- hand every time.
--
-- 4. Unilever_Inventory_Monthly — a convenience view combining the
-- fields most likely to be queried together for Unilever SOH reporting,
-- scoped to real (is_demo=false) Unilever rows only.

BEGIN;

-- 1
CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_unilever_soh
    ON Inventory_Fact (sku_code, snapshot_date, COALESCE(region, ''), is_demo)
    WHERE principal = 'unilever';

-- 2 (column only — backfill via scratch/backfill_0010.py)
ALTER TABLE Unilever_SKU_Demand_Fact ADD COLUMN IF NOT EXISTS gsv NUMERIC(14,2);

CREATE OR REPLACE VIEW Unilever_SKU_Demand_Fact_Real AS
SELECT * FROM Unilever_SKU_Demand_Fact WHERE is_demo = false;

-- 3 (columns only — backfill via scratch/backfill_0010.py)
ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS days_offset   INTEGER;
ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS demand_period TEXT;

-- is_demo=false filter preserved verbatim.
CREATE OR REPLACE VIEW Inventory_Fact_Real AS
SELECT * FROM Inventory_Fact WHERE is_demo = false;

-- 4
CREATE OR REPLACE VIEW Unilever_Inventory_Monthly AS
SELECT
    _period,
    demand_period,
    product_key,
    sku_code,
    quantity_on_hand,
    quantity_pieces,
    valuation,
    unit_cost_per_case,
    blocked_qty_cases,
    stock_status,
    snapshot_date,
    days_offset
FROM Inventory_Fact
WHERE principal = 'unilever' AND is_demo = false;

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DROP VIEW IF EXISTS Unilever_Inventory_Monthly;
-- CREATE OR REPLACE VIEW Inventory_Fact_Real AS
-- SELECT * FROM Inventory_Fact WHERE is_demo = false;
-- ALTER TABLE Inventory_Fact DROP COLUMN IF EXISTS demand_period;
-- ALTER TABLE Inventory_Fact DROP COLUMN IF EXISTS days_offset;
-- CREATE OR REPLACE VIEW Unilever_SKU_Demand_Fact_Real AS
-- SELECT * FROM Unilever_SKU_Demand_Fact WHERE is_demo = false;
-- ALTER TABLE Unilever_SKU_Demand_Fact DROP COLUMN IF EXISTS gsv;
-- DROP INDEX IF EXISTS uq_inventory_unilever_soh;
-- COMMIT;
