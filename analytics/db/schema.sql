-- analytics/db/schema.sql
-- Phase 3A (CLAUDE.md Step 2 — Checkpoint: matches Section 3.3.1 and 3.3.2)
--
-- Galaxy / Fact-Constellation schema for SSM Capstone.
-- Principals in scope: Unilever Philippines · Del Monte Philippines ONLY.
--
-- Execution order:
--   1. Dimension tables (no foreign-key dependencies)
--   2. Fact tables (reference dimension PKs)
--   3. ABC_Classification (derived from Sales_Fact)
--
-- Yuan reviews this file against the manuscript ERD before running in Supabase.
--
-- TODO: Write full DDL for all 10 tables listed in CLAUDE.md Part 1.
--       Confirm column names, data types, and constraint definitions with Yuan.



-- analytics/db/schema.sql
--
-- Galaxy / Fact-Constellation schema for the SSM Decision Support Dashboard.
-- Principals in scope: Unilever Philippines · Del Monte Philippines ONLY.
--
-- This DDL implements ARCHITECTURE.md's locked decisions:
--   DEC-01  raw -> staging -> curated layering (this file = curated zone)
--   DEC-02  TWO MARTS, not one clean constellation:
--             - transaction mart: Sales_Fact / Purchase_Fact / SalesReturn_Fact
--               are INVOICE grain. Their source files carry no SKU column,
--               so they carry NO product_key FK. Forcing one would be
--               fabrication (ARCHITECTURE.md principle #1) - do not add it
--               later without a real source column behind it.
--             - product mart: Inventory_Fact / SellOut_Fact /
--               Unilever_SKU_Demand_Fact DO join Product_Dimension because
--               their source files carry real product/category identifiers.
--   DEC-03  recommendation/forecast grain per principal: Unilever = SKU
--           (Unilever_SKU_Demand_Fact), Del Monte = category/brand
--           (SellOut_Fact). No Del Monte SKU allocation - not a baseline
--           option per ARCHITECTURE.md §5.1.
--   DEC-04  source-of-truth per fact per principal (config/source_of_truth.yaml)
--           -> the UNIQUE natural-key constraints below encode that map so a
--           double-count (e.g. loading both RAW DATA and INVOICE REG) fails
--           loudly at the DB layer, not silently.
--   DEC-05  totals-row checksum lives in Extract/staging, not here.
--   DEC-06  SCD Type 1 (overwrite) for dimensions - no history columns.
--
-- Type rules (ARCHITECTURE.md §6.3, confirmed against real files):
--   - codes / identifiers (branch code, SKU code, invoice num) -> TEXT,
--     NEVER numeric. Leading zeros are real data (e.g. branch code "0632").
--   - money -> NUMERIC(14,2), never FLOAT (rounding must be exact/auditable).
--   - discount_rate_label is a TEXT LABEL ("Public Pricelist", "LESS 2%"),
--     not a numeric rate - do not "fix" this to a number.
--   - dates -> DATE, referencing Date_Dimension for consistent calendar joins.
--
-- Every fact table also carries _src_file / _src_sheet (+ _period where the
-- grain is monthly) so any curated row can be walked back to its exact
-- source cell - this is what makes the anti-fabrication rule auditable
-- (ARCHITECTURE.md principle #3). These are NOT renamed/dropped from the
-- staging provenance columns Extract already attaches.
--
-- Execution order: dimensions -> transaction-mart facts -> product-mart
-- facts -> analytics outputs (ABC_Classification, Forecast_Result,
-- LP_Recommendation). Run top to bottom; FKs depend on earlier sections.
--
-- OPEN QUESTION FOR YUAN (flagging, not guessing — see anti-fabrication
-- principle): backend/schemas/bo_monitoring.py's original TODO assumes a
-- per-SKU `sku_id` field for BO-rate monitoring. But bo_rmr_gs.py confirms
-- BO/RMR returns are INVOICE grain for Del Monte (no SKU column exists in
-- that file family - same constraint as Sales/Purchase/SalesReturn). This
-- schema does NOT add a fabricated sku_id to BO monitoring; §9 below
-- computes bo_rate at the grain the source data actually supports
-- (principal/region/period) via a view over Purchase_Fact + SalesReturn_Fact.
-- Confirm with Yuan whether GET /bo-monitoring should be redefined at that
-- grain, or whether BO monitoring is meant to run only for Unilever SKUs
-- (which do have a real SKU key via Unilever_SKU_Demand_Fact) instead.
--
-- UPDATE 2026-08: the GRAIN question above is still open, but the METRIC
-- was resolved separately - bo_rate in §5 below is now value-based
-- (net_amount ratio), not unit-based, since bo_units has no source
-- column anywhere in real RMR data and never will.

-- ============================================================
-- SECTION 1 — DIMENSION TABLES (no FK dependencies, DEC-06: SCD Type 1)
-- ============================================================

CREATE TABLE IF NOT EXISTS Date_Dimension (
    date_key        DATE PRIMARY KEY,
    day_of_week     SMALLINT NOT NULL,      -- 1=Mon .. 7=Sun (ISO)
    day_name        TEXT NOT NULL,
    week_of_year    SMALLINT NOT NULL,
    month           SMALLINT NOT NULL,
    month_name      TEXT NOT NULL,
    quarter         SMALLINT NOT NULL,
    year            SMALLINT NOT NULL,
    is_weekend      BOOLEAN NOT NULL,
    fiscal_period   TEXT                    -- align with SSM cycles once confirmed; NULL until then
);

-- Covers both Unilever SKUs (real, from Unilever_SKU_Demand_Fact source)
-- and Del Monte category/brand nodes (from SellOut_Fact's "/ACE/BASE"-style
-- hierarchy). One dimension, two kinds of "product identity" per DEC-03 -
-- category/brand rows are legitimate members here, not a workaround.
CREATE TABLE IF NOT EXISTS Product_Dimension (
    product_key     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    principal       TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    grain           TEXT NOT NULL CHECK (grain IN ('sku', 'category')),  -- DEC-03
    sku_code        TEXT,                   -- Unilever: real SKU code; NULL for Del Monte category rows
    category_path   TEXT,                   -- Del Monte: e.g. '/ACE/BASE'; NULL for Unilever SKU rows
    -- Added migration 0011 (2026-09-11): records HOW category_path/brand
    -- were populated, so the direct/fallback/unclassified split is
    -- queryable afterward instead of recomputed. See each column's own
    -- COMMENT ON COLUMN (migration 0011) for the full value meanings.
    category_path_source TEXT CHECK (category_path_source IS NULL OR category_path_source IN
        ('direct_soh_match', 'keyword_rule', 'unclassified')),
    product_name    TEXT,
    pack_size       TEXT,
    brand           TEXT,
    brand_source    TEXT CHECK (brand_source IS NULL OR brand_source IN ('soh_first_token_rule')),  -- migration 0026 adds 'demand_first_token_rule'
    -- Added for the SKU Management module (GET/POST/PATCH /sku) — see
    -- analytics/db/migrations/0002_add_sku_management_fields.sql for the
    -- incremental ALTER path on a database that already exists.
    unit_price      NUMERIC(14,2),
    lead_time_days  INTEGER,
    status          TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'DISABLED')),
    notes           TEXT,
    -- NULLS NOT DISTINCT (migration 0013, 2026-09-15 incident fix — see
    -- that migration's own comment): sku_code IS NULL for every
    -- category-grain row (both principals) and category_path IS NULL for
    -- every SKU-grain row (both principals — see migration 0016 correction
    -- below). A plain UNIQUE constraint treats NULL as never equal to
    -- NULL, so it never actually enforced uniqueness for Unilever's real
    -- rows — confirmed directly: a repeat INSERT for an already-existing
    -- SKU succeeded as a brand new duplicate row instead of being
    -- rejected/skipped. NULLS NOT DISTINCT (PG15+) makes two NULLs compare
    -- equal for THIS constraint only — every other NULL comparison in the
    -- database is unaffected.
    --
    -- migration 0014 (2026-09-15, root cause #4): this table-wide
    -- constraint alone is still not enough for Unilever specifically —
    -- run_category_brand_backfill() (scripts/run_canonical_load.py)
    -- mutates category_path from NULL to a real value for every existing
    -- Unilever SKU-grain row, once, so a key that includes category_path
    -- goes stale the moment that backfill has run. A separate PARTIAL
    -- unique index, scoped to principal='unilever' AND grain='sku' and
    -- keyed on (principal, grain, sku_code) only, is what
    -- scripts/run_canonical_load.py's _product_fk_spec("sku") actually
    -- resolves/inserts against for Unilever now — see that migration.
    --
    -- migration 0016 (2026-09-17, column-gap audit) CORRECTS 0014's
    -- premise: Del Monte sku_codes do NOT "legitimately span multiple
    -- category_path values." That category_path was a self-admitted
    -- "fake category" heuristic (scripts/generate_synthetic_dm.py:31-44,
    -- an ad-hoc, non-canonical, pre-canonical-load-era script), not real
    -- source data — no Del Monte source ties an individual SKU to a
    -- category. Migration 0016 deduped the 291 resulting extra rows,
    -- nulled the heuristic category_path values, and added a table-wide
    -- partial unique index on (principal, sku_code), so category_path is
    -- now NULL for every SKU-grain row, both principals, same as Unilever
    -- always was.
    UNIQUE NULLS NOT DISTINCT (principal, grain, sku_code, category_path)
);

-- migration 0014 — see the table comment above for why this partial index
-- exists alongside the table-wide UNIQUE constraint.
CREATE UNIQUE INDEX IF NOT EXISTS product_dimension_unilever_sku_key_idx
    ON Product_Dimension (principal, grain, sku_code)
    WHERE principal = 'unilever' AND grain = 'sku';

-- migration 0016 — table-wide (both principals) now that Del Monte's
-- sku-grain duplicates are deduped and their category_path values (never
-- real to begin with) are nulled. Partial on sku_code IS NOT NULL so
-- grain='category' rows (sku_code always NULL) stay excluded.
CREATE UNIQUE INDEX IF NOT EXISTS product_dimension_sku_key_idx
    ON Product_Dimension (principal, sku_code)
    WHERE sku_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS Customer_Dimension (
    customer_key    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_name   TEXT NOT NULL,
    region          TEXT,                   -- pangasinan / ilocos / la_union
    principal       TEXT CHECK (principal IN ('unilever', 'delmonte')),
    UNIQUE (customer_name, region, principal)
);

CREATE TABLE IF NOT EXISTS Salesman_Dimension (
    salesman_key    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    salesman_name   TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS Supplier_Dimension (
    supplier_key    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_name   TEXT NOT NULL UNIQUE,   -- 'Unilever Philippines' / 'Del Monte Philippines'
    principal       TEXT NOT NULL UNIQUE CHECK (principal IN ('unilever', 'delmonte'))
);

-- ============================================================
-- SECTION 2 — TRANSACTION MART (invoice grain, DEC-02)
-- No product_key here: source files have no SKU column at this grain.
-- Natural keys below encode DEC-04's source-of-truth map
-- (config/source_of_truth.yaml) so a demoted cross-check sheet
-- (INVOICE REG, SALES PER CUSTOMER, ONE PAGER, daily echoes, ...) can
-- never be double-loaded alongside the system-of-record sheet.
-- ============================================================

-- Fixed 2026-08 (pre-Supabase-creation review): restricted to Del Monte
-- only. Unilever's real Sales system-of-record (SSIS RAW_DATA) has NO
-- invoice/reference column at all (confirmed against real staged headers
-- - the real grain is closer to outlet+calendar_day than invoice), so
-- this table could never honestly hold a Unilever row without
-- fabricating invoice_num. Confirmed via exhaustive grep that nothing in
-- analytics/ or backend/ reads this table expecting Unilever data -
-- classify_abc() deliberately never reads it at all. Consequence: the
-- ssis_summary doc family (1,949,687 real staged rows, the largest
-- single source in the corpus) currently has NO fact-table destination
-- - it was the only thing that would have fed Unilever rows here. Not
-- fixed in this pass; if Unilever sales ever need to be a fact (not just
-- SKU demand via Unilever_SKU_Demand_Fact), it needs its own table at
-- outlet+calendar_day grain, matching ssis_summary's real columns
-- (Salesman, CALENDAR DAY, REASON CODE, OUTLET, OUTLET NAME, GSV, ...).
CREATE TABLE IF NOT EXISTS Sales_Fact (
    sales_key           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_num         TEXT NOT NULL,
    invoice_date        DATE REFERENCES Date_Dimension(date_key),
    principal           TEXT NOT NULL CHECK (principal = 'delmonte'),
    region              TEXT,
    branch_code         TEXT,               -- TEXT: leading zeros are real (§6.3 type trap)
    customer_key        BIGINT REFERENCES Customer_Dimension(customer_key),
    salesman_key        BIGINT REFERENCES Salesman_Dimension(salesman_key),
    untaxed_amount      NUMERIC(14,2),
    discount_amount     NUMERIC(14,2),
    discount_rate_label TEXT,               -- text label (e.g. 'LESS 2%'), never coerced to numeric
    tax_amount          NUMERIC(14,2),
    net_amount          NUMERIC(14,2) NOT NULL,
    balance             NUMERIC(14,2),
    _outlier_flag       BOOLEAN NOT NULL DEFAULT FALSE,   -- from clean.flag_iqr_outliers; flagged, never dropped
    -- Phase 4 (2026-08): true only for adviser-sanctioned synthetic demo
    -- rows (see reports/SYNTHETIC_DATA_AUDIT.md) - DEFAULT false means a
    -- real row's INSERT, which never specifies this column at all (Extract
    -- never produces an is_demo raw column for real files - see
    -- column_maps/sales_register.yaml's note), gets false from Postgres
    -- itself, not from application code. See Sales_Fact_Real below.
    is_demo             BOOLEAN NOT NULL DEFAULT false,
    _src_file           TEXT NOT NULL,
    _src_sheet          TEXT NOT NULL,
    _period             TEXT NOT NULL,      -- 'YYYY-MM'
    UNIQUE (invoice_num, principal, region) -- DEC-04 natural key (config/source_of_truth.yaml: sales)
);

CREATE INDEX IF NOT EXISTS ix_sales_fact_principal_period ON Sales_Fact (principal, _period);
CREATE INDEX IF NOT EXISTS ix_sales_fact_customer ON Sales_Fact (customer_key);

CREATE TABLE IF NOT EXISTS Purchase_Fact (
    purchase_key        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_num          TEXT NOT NULL,      -- 'BILL/...' or PO ref
    invoice_date        DATE REFERENCES Date_Dimension(date_key),
    principal            TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    region                TEXT,
    supplier_key          BIGINT REFERENCES Supplier_Dimension(supplier_key),
    net_amount             NUMERIC(14,2) NOT NULL,
    tax_amount              NUMERIC(14,2),
    units_received           NUMERIC(14,2), -- feeds clean.compute_bo_rate; NULL (not 0) when absent from source
    -- Phase 4 (2026-08): see Sales_Fact.is_demo's comment - identical
    -- reasoning and real-row-default behavior for this table.
    is_demo                   BOOLEAN NOT NULL DEFAULT false,
    _src_file                TEXT NOT NULL,
    _src_sheet                TEXT NOT NULL,
    _period                   TEXT NOT NULL,
    -- Migration 0025 replaces this key with (invoice_num, principal, region,
    -- invoice_date). Left as first declared on purpose: a fresh build runs this
    -- file and then every migration, and 0025 drops this constraint by name.
    UNIQUE (invoice_num, principal, region) -- DEC-04 natural key (config/source_of_truth.yaml: purchase)
);

CREATE INDEX IF NOT EXISTS ix_purchase_fact_principal_period ON Purchase_Fact (principal, _period);

-- return_type is confirmed GS/BO only (config/source_of_truth.yaml:
-- sales_return.system_of_record_role = [gs, bo]). The RMR "ONE PAGER"
-- sheet (= GS union BO) is a demoted cross-check per DEC-04 and must
-- never be loaded here - that's the double-count trap this table guards.
CREATE TABLE IF NOT EXISTS SalesReturn_Fact (
    return_key           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    return_slip_num       TEXT,              -- primary natural-key half
    invoice_num            TEXT,             -- kept for schema-generality; see note below on why it's not in the key
    -- Fixed 2026-08 (Sales Return driver build): was NOT NULL. The
    -- GS/BO split is a formatting artifact of the 2025-era report only -
    -- 2023 and Jan/Feb 2024 Sales Return files (the majority of the real
    -- corpus, ~10-12 of 19 files) record returns in one undifferentiated
    -- sheet with no Return Type column at all. A NOT NULL constraint here
    -- would make those real rows permanently unloadable without
    -- fabricating a GS/BO value they don't report. Nullable now; a NULL
    -- return_type means "return type not distinguished by the source",
    -- not "unknown data". BO_Monitoring_View's `WHERE return_type = 'BO'`
    -- degrades safely on NULL (row excluded, no error) - confirmed no
    -- other caller (load.py, routers, tests) assumes this column is
    -- populated before this change shipped.
    return_type             TEXT CHECK (return_type IS NULL OR return_type IN ('GS', 'BO')),
    return_date              DATE REFERENCES Date_Dimension(date_key),
    principal                 TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    region                     TEXT,
    net_amount                  NUMERIC(14,2),
    bo_units                     NUMERIC(14,2),  -- always NULL for real data - see BO_Monitoring_View note below, no source column exists
    -- Phase 4 (2026-08): see Sales_Fact.is_demo's comment - identical
    -- reasoning and real-row-default behavior for this table.
    is_demo                       BOOLEAN NOT NULL DEFAULT false,
    _src_file                     TEXT NOT NULL,
    _src_sheet                     TEXT NOT NULL,
    _period                         TEXT NOT NULL,
    -- CHANGED 2026-09-11 (migration 0011, Yuan approved): return_type
    -- dropped from this key, invoice_num added back. The system of record
    -- for this table changed 2026-09-09 (rmr_gs_bo -> sales_return,
    -- config/source_of_truth.yaml) - unlike rmr_gs_bo, sales_return DOES
    -- carry a real invoice_num (1,912/1,931 rows), so the "0/538 real
    -- rows" reasoning below for dropping it no longer holds. Tested both
    -- return_type options against real data before deciding (see migration
    -- 0011's own header comment and reports/PHASE1_EXECUTION_PLAN_2026-09.md
    -- step 2c, item 21): dropping return_type entirely vs
    -- COALESCE(return_type,'') gave IDENTICAL results (1 colliding group,
    -- 3 fully-blank rows, neither a real duplicate) - return_type adds no
    -- discriminating power once invoice_num is in the key. Dropping it also
    -- recovers the pre-2025 `data`-shaped sheets (~55% of the real corpus),
    -- which never populated return_type at all and were previously
    -- individually quarantined by transform.dedup_facts() purely for that
    -- reason (verified: quarantine count drops 773 -> 8 once return_type is
    -- out of the key).
    UNIQUE (return_slip_num, principal, region, invoice_num)
);

CREATE INDEX IF NOT EXISTS ix_salesreturn_fact_principal_period ON SalesReturn_Fact (principal, _period);

-- ============================================================
-- SECTION 3 — PRODUCT MART (SKU / category grain, DEC-02 + DEC-03)
-- These DO join Product_Dimension - their source files carry real
-- product/category identifiers, so an FK here is honest, not fabricated.
-- ============================================================

CREATE TABLE IF NOT EXISTS Inventory_Fact (
    inventory_key     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_key        BIGINT REFERENCES Product_Dimension(product_key),
    sku_code            TEXT NOT NULL,       -- kept raw alongside the FK; Extract never renames, Transform maps it
    -- DEC-12: these exports are monthly - no real day-of-month exists
    -- anywhere in the source. snapshot_date is kept a valid DATE by
    -- setting it to the 1st of _period below (transform._snapshot_date_from_period()) -
    -- a documented SYNTHETIC marker, not an independently reported date.
    -- _period (added DEC-12) is the real join/period key, straight from
    -- Extract's own _period provenance column, mirroring Sales_Fact/
    -- Purchase_Fact/SalesReturn_Fact/SellOut_Fact's existing pattern so
    -- Inventory can be joined to monthly-only facts (e.g. Unilever SKU
    -- demand's calendar_month, SellOut_Fact._period) on a common format.
    snapshot_date        DATE NOT NULL REFERENCES Date_Dimension(date_key),
    _period                TEXT,             -- 'YYYY-MM', the real period key (see note above)
    principal             TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    region                 TEXT,
    quantity_on_hand        NUMERIC(14,2),
    -- UNIT: CASES, not pieces (documented explicitly via COMMENT ON COLUMN,
    -- migration 0011, 2026-09-11 — transform_ssis_soh.py:226 has always
    -- loaded this from stock_qty_cases; no column carried that fact until
    -- now). Consumers needing pieces must multiply by
    -- Product_Dimension.pack_size.
    -- DEC-11: comparable-unit quantity, Del Monte only for now — set
    -- directly from the source file's PCS (pieces) column via
    -- transform.normalize_quantities(). CAS/PKG (cases/packages) are
    -- deliberately NOT converted into this field: no confirmed pack_size
    -- exists anywhere in Del Monte's files, so a conversion would be
    -- fabricated, not derived. See config/column_maps/inventory_sign_off.yaml.
    quantity_pieces          NUMERIC(14,2),
    -- Phase 4 (2026-08): see Sales_Fact.is_demo's comment - identical
    -- reasoning and real-row-default behavior for this table.
    is_demo                   BOOLEAN NOT NULL DEFAULT false,
    _src_file                TEXT NOT NULL,
    _src_sheet                TEXT NOT NULL,
    -- Backfilled 2026-08-27 (migrations/0009_add_soh_columns.sql):
    -- both columns were ALREADY LIVE on Supabase before this line existed
    -- here — valuation via migrations/0004_add_valuation.sql, cost added
    -- live/ad hoc at some earlier point with no migration ever tracking
    -- it (confirmed via a live information_schema query, 2026-08-27).
    -- Documented here now, not dropped or altered — 0009 only ADDs
    -- columns (IF NOT EXISTS), it never touches these two.
    valuation                 NUMERIC,     -- Del Monte: extended peso total for this SKU/snapshot's on-hand qty
    -- cost is Del Monte's own extended peso total, confirmed EQUAL to
    -- valuation on real data (R10, 2026-08: 584 rows Cost==Valuation in
    -- the 2025 layout, plus the totals row) — NOT a per-unit price.
    -- Unilever's SOH source has no equivalent (its Last Purchase Price
    -- is a per-case UNIT price, a different concept entirely — see
    -- unit_cost_per_case below); Unilever rows leave this column NULL,
    -- never populated from Last Purchase Price (R10: do not conflate the
    -- two units under one column name).
    cost                       NUMERIC,
    -- R11 (2026-08, Unilever SOH Load): Last Purchase Price(GSV/CS) is a
    -- per-CASE unit price (the source header says so directly), a
    -- different unit than Del Monte's cost/valuation (extended peso
    -- totals) above — kept in its own column rather than mixed into
    -- `cost`. Del Monte rows leave this column NULL (no per-case unit
    -- price concept exists in that source).
    unit_cost_per_case         NUMERIC,
    -- R12 (2026-08, Unilever SOH Load): the dead-stock signal (Blocked
    -- Stock (CS/PC) split into cases/pieces, + Status) — flagged as
    -- needed downstream in this session's Transform report, no prior
    -- home. Unilever only for now; Del Monte rows leave these NULL (no
    -- equivalent column in that source).
    blocked_qty_cases          NUMERIC,
    blocked_qty_pieces         NUMERIC,
    stock_status                TEXT,
    UNIQUE (sku_code, snapshot_date, region)  -- DEC-04 natural key (config/source_of_truth.yaml: inventory).
    -- CAVEAT (2026-08-27, Unilever SOH Load): Postgres treats NULL <>
    -- NULL in a UNIQUE constraint (same class of gap SalesReturn_Fact's
    -- invoice_num had, see that table's comment) - Unilever SOH rows all
    -- have region=NULL (R6: Storage Location dropped, no real region
    -- concept for this source), so THIS CONSTRAINT DOES NOT ACTUALLY
    -- ENFORCE (sku_code, snapshot_date) uniqueness for Unilever rows at
    -- the database level. source_of_truth.yaml's inventory.unilever
    -- natural_key is [sku_code, snapshot_date] (no region) for exactly
    -- this reason; uniqueness for Unilever is verified by Transform's
    -- dedup_facts() and this Load's own live post-load query, not by
    -- this constraint. Not fixed here — out of this migration's scope
    -- (R11/R12 additions + valuation/cost documentation only); flag for
    -- a future migration if a real Unilever duplicate is ever a risk.
);

CREATE INDEX IF NOT EXISTS ix_inventory_fact_product ON Inventory_Fact (product_key);

-- Del Monte only (DEC-03). Category grain, from Sell Out files
-- ('/ACE/BASE', '/TETRA/BASE', ... hierarchy paths). This is the honest
-- ceiling for Del Monte forecasting - do not join this to a fabricated
-- per-SKU allocation.
CREATE TABLE IF NOT EXISTS SellOut_Fact (
    sellout_key       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_key         BIGINT REFERENCES Product_Dimension(product_key),  -- grain='category' row
    category_path        TEXT NOT NULL,      -- e.g. '/ACE/BASE'; kept raw alongside the FK
    principal              TEXT NOT NULL DEFAULT 'delmonte' CHECK (principal = 'delmonte'),
    region                   TEXT,
    _period                   TEXT NOT NULL,  -- 'YYYY-MM'
    quantity                   NUMERIC(14,2), -- negatives are real (returns/adjustments) - do not clamp to zero
    net_amount                  NUMERIC(14,2),
    -- Phase 4 (2026-08): see Sales_Fact.is_demo's comment - identical
    -- reasoning and real-row-default behavior for this table.
    is_demo                      BOOLEAN NOT NULL DEFAULT false,
    _src_file                    TEXT NOT NULL,
    _src_sheet                    TEXT NOT NULL,
    UNIQUE (category_path, region, _period)   -- DEC-04 natural key (config/source_of_truth.yaml: sell_out)
);

CREATE INDEX IF NOT EXISTS ix_sellout_fact_period ON SellOut_Fact (_period);

-- Unilever only (DEC-03). The SOLE confirmed SKU-level DEMAND source in
-- the whole corpus (the La Union MHTML file) - distinct grain from
-- Sales_Fact (Calendar Month x Product x Pack Size, not an invoice), so
-- it gets its own table rather than a nullable product_key bolted onto
-- Sales_Fact. This is the direct SARIMA input for Unilever (ARCHITECTURE.md
-- §5.1). NOTE: this table does not appear in the original models.py TODO
-- list (which named only 5 facts) - it's added here because DEC-03 requires
-- a real per-SKU demand table and no existing fact honestly carries that
-- grain. Flag to Yuan if this should be merged/renamed instead of added.
CREATE TABLE IF NOT EXISTS Unilever_SKU_Demand_Fact (
    demand_key       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_key        BIGINT NOT NULL REFERENCES Product_Dimension(product_key),
    sku_code             TEXT NOT NULL,
    calendar_month         TEXT NOT NULL,    -- 'YYYY-MM', from the source's own 'Calendar Month' cell (per-row, not sheet-wide)
    region                   TEXT NOT NULL DEFAULT 'la_union',
    -- DEC-11: in pieces — set from the source's reported
    -- sale_quantity_pieces column (transform.normalize_quantities()),
    -- not derived from sale_quantity_cases x pack_size (only ~84%
    -- consistent with reported pieces on real data; that comparison is
    -- a QC cross-check only, never the value of record).
    quantity_sold             NUMERIC(14,2),
    -- Added 2026-08: classify_abc() requires total_revenue per SKU, and
    -- this is the only Unilever SKU-grain fact table - without a revenue
    -- column, Unilever cannot get an ABC tier at all. Source: the real
    -- staged unilever_sku data already has net_amount_inc_tax/gsv fields
    -- (config/column_maps/unilever_sku.yaml), coerced to numeric in the
    -- prior Transform work - this column just gives them a home here.
    net_amount                NUMERIC(14,2),
    -- Phase 4 (2026-08): see Sales_Fact.is_demo's comment - identical
    -- reasoning and real-row-default behavior for this table.
    is_demo                    BOOLEAN NOT NULL DEFAULT false,
    _src_file                  TEXT NOT NULL,
    _src_sheet                   TEXT NOT NULL,
    UNIQUE (sku_code, calendar_month)
);

CREATE INDEX IF NOT EXISTS ix_unilever_sku_demand_product ON Unilever_SKU_Demand_Fact (product_key);

-- ============================================================
-- SECTION 4 — ANALYTICS OUTPUTS (derived, written by analytics/ pipeline,
-- read-only from backend/'s point of view per the architecture boundary)
-- ============================================================

-- product_key here is always a grain='sku' (Unilever) or grain='category'
-- (Del Monte) row from Product_Dimension - never a fabricated one-size-fits
-- all key. classification_period is the month this tier assignment covers;
-- re-running for a later period does not overwrite history (DEC-06 applies
-- to dimensions, not to this time-stamped derived table).
-- 2026-08: added boundary_flag for backlog #43 ("SKUs sitting near a
-- tier boundary flagged so reclassification is anticipated"). If this
-- table was already created in your Supabase project before this
-- change, CREATE TABLE IF NOT EXISTS will NOT retroactively add the
-- column - run this once by hand first:
--   ALTER TABLE ABC_Classification ADD COLUMN IF NOT EXISTS boundary_flag BOOLEAN NOT NULL DEFAULT FALSE;
-- method/run_id added by migration 0017 (2026-09-17, ABC Phase 2 re-check):
-- 'single' = that month's revenue, 't3m' = trailing 3 months including that
-- month. Natural key widened to (product_key, classification_period, method)
-- since both bases legitimately coexist for the same product/period.
-- 't12m_new' (migration 0044, DEC-38): 12 months + new products; which method
-- is Tier A is analytics.params.TIER_A_BASIS / abc_method().
CREATE TABLE IF NOT EXISTS ABC_Classification (
    classification_key      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_key                BIGINT NOT NULL REFERENCES Product_Dimension(product_key),
    principal                    TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    classification_period          TEXT NOT NULL,   -- 'YYYY-MM'
    method                           TEXT NOT NULL DEFAULT 'single' CHECK (method IN ('single', 't3m', 't12m_new')),  -- 't12m_new': migration 0044
    run_id                            TEXT NOT NULL DEFAULT 'legacy_pre_0017',  -- audit tag for the orchestration run that wrote this row, not part of the natural key
    tier                             TEXT NOT NULL CHECK (tier IN ('A', 'B', 'C')),
    revenue_share                     NUMERIC(7,4),  -- this item's share of period revenue
    cumulative_share                   NUMERIC(7,4), -- running total used for the 80/95 cut points
    boundary_flag                       BOOLEAN NOT NULL DEFAULT FALSE,  -- backlog #43; margin (analytics/classification/abc.py BOUNDARY_MARGIN) unconfirmed vs manuscript Sec.3.6
    added_as_new                        BOOLEAN NOT NULL DEFAULT FALSE,  -- migration 0044: t12m_new row made Class A by the new-product rule
    computed_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_key, classification_period, method)
);

CREATE INDEX IF NOT EXISTS ix_abc_classification_tier ON ABC_Classification (tier, classification_period);

-- sku_traits / sku_segment added by migration 0018 (2026-09-17, Phase 2
-- binning Round 1 — reports/BINNING_ROUND1_2026-09.md). BINS ONLY: no
-- model runs, no MASE, no model assignment written here — that is Phase 3.
-- sku_traits is computed once per (product_key, cohort_period, abc_method)
-- (abc_method + the widened key come from migration 0020 - see the note on
-- the table's UNIQUE line); sku_segment
-- holds one row per (product_key, cohort_period, abc_method, scheme) so
-- later schemes (trend_v1, volatility_v1, newness_v1, combined_v1) add rows
-- here without touching sku_traits or the schema again.
CREATE TABLE IF NOT EXISTS sku_traits (
    trait_key               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                   TEXT NOT NULL,
    principal                 TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    product_key                BIGINT NOT NULL REFERENCES Product_Dimension(product_key),
    cohort_period                TEXT NOT NULL,
    abc_method                    TEXT NOT NULL DEFAULT 'single' CHECK (abc_method IN ('single', 't3m', 't12m_new')),  -- migration 0020; 't12m_new' 0044
    history_months                INT NOT NULL,   -- months with quantity_sold > 0
    first_sale_period               TEXT,
    longest_run                      INT NOT NULL,
    trend                              TEXT NOT NULL CHECK (trend IN ('up', 'down', 'none')),  -- Mann-Kendall, p < 0.05
    cv                                  NUMERIC,
    restart_flag                        BOOLEAN NOT NULL DEFAULT FALSE,
    stability_group                      TEXT NOT NULL CHECK (stability_group IN ('all_38', 'at_least_30', 'churn')),
    revenue_share_2026_02                 NUMERIC(7,4),
    adi                                    NUMERIC,  -- migration 0022: months since first sale / months with a sale
    trend_pvalue                            NUMERIC,  -- migration 0022: Mann-Kendall two-sided p, from first sale
    trend_slope                              NUMERIC,  -- migration 0022: Theil-Sen slope, units/month, from first sale
    computed_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Declared in its PRE-0020 two-column form ON PURPOSE. Migration 0020 drops this constraint and adds
    -- UNIQUE (product_key, cohort_period, abc_method) under an explicit name, without IF NOT EXISTS. A fresh
    -- build runs this file and then every migration, so declaring the three-column key here makes 0020 fail
    -- with "relation ... already exists" (it did, 2026-09-21). The live key IS the three-column one.
    UNIQUE (product_key, cohort_period)
);

CREATE TABLE IF NOT EXISTS sku_segment (
    segment_key              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                     TEXT NOT NULL,
    principal                   TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    product_key                  BIGINT NOT NULL REFERENCES Product_Dimension(product_key),
    sku_code                       TEXT,
    cohort_period                    TEXT NOT NULL,
    abc_method                        TEXT NOT NULL DEFAULT 'single' CHECK (abc_method IN ('single', 't3m', 't12m_new')),  -- 't12m_new': migration 0044
    scheme                              TEXT NOT NULL,
    bin                                  TEXT NOT NULL,
    bin_reason                            TEXT NOT NULL,
    computed_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_key, cohort_period, abc_method, scheme)
);

CREATE INDEX IF NOT EXISTS ix_sku_segment_scheme_bin ON sku_segment (scheme, bin);
CREATE INDEX IF NOT EXISTS ix_sku_traits_cohort ON sku_traits (cohort_period, principal);

-- Tier A, Unilever SKU grain (DEC-03: real per-SKU demand exists only
-- there). The LP's candidate gate is mase < analytics.params.MASE_GATE
-- (scripts/run_lp.py CANDIDATE_QUERY), not mape; the MAPE < 20% gate and
-- SARIMA are both retired (DEC-25, DEC-26).
CREATE TABLE IF NOT EXISTS Forecast_Result (
    forecast_key      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_key         BIGINT NOT NULL REFERENCES Product_Dimension(product_key),
    forecast_date         DATE NOT NULL,
    forecast_value          NUMERIC(14,2) NOT NULL,
    confidence_lower          NUMERIC(14,2),
    confidence_upper          NUMERIC(14,2),
    mape                        NUMERIC(10,3),       -- PERCENT, not a 0-1 fraction (e.g. 20.0 means 20%,
                                                       -- matching scripts/run_sarima.py's *100 conversion
                                                       -- before insert). Reported, never a gate (the LP gates
                                                       -- on mase). A `>= 0.20` comparison anywhere
                                                       -- against this column is wrong by a factor of 100.
                                                       -- (Live precision confirmed NUMERIC(10,3), not the
                                                       -- (6,3) this comment said until 2026-08 remediation.)
    mase                        NUMERIC(10,3),       -- Scale-free (Hyndman & Koehler 2006), doesn't blow up
                                                       -- on near-zero actuals the way mape can. Was live on
                                                       -- Supabase but undocumented here and never populated
                                                       -- by run_sarima.py until this fix - see evaluate_sarima().
    model_params                  JSONB,             -- SARIMA (p,d,q)(P,D,Q,s) etc. - stored as given, not re-derived
    generated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Added by migrations/0008_add_forecast_result_status.sql: distinguishes
    -- a real, measured forecast from one that couldn't be measured, so mape
    -- is never fabricated to look like it passed the gate. See run_sarima.py.
    status                         TEXT NOT NULL DEFAULT 'ok'
                                     CHECK (status IN ('ok', 'insufficient_data', 'dead_sku', 'fit_failed', 'unreliable')),
    UNIQUE (product_key, forecast_date)
);

CREATE INDEX IF NOT EXISTS ix_forecast_result_product ON Forecast_Result (product_key);

-- SS_i = Z x sigma (Z=1.28, 90% service level) over review + lead days;
-- rop_i holds the order-up-to TARGET stock T_i = weekly forecast x (review +
-- lead days) / 5 + SS_i (scripts/run_lp.py, since 2026-09-29), not a reorder
-- point; the column keeps its old name. Q_i from the LP (analytics/
-- optimization/lp.py; weights analytics.params.LP_WEIGHTS).
-- status supports the dashboard's Accept/Dismiss write-back (README Phase 7).
CREATE TABLE IF NOT EXISTS LP_Recommendation (
    recommendation_key      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_key                BIGINT NOT NULL REFERENCES Product_Dimension(product_key),
    planning_cycle_date          DATE NOT NULL,
    q_i                             NUMERIC(14,2) NOT NULL,   -- recommended order quantity
    rop_i                             NUMERIC(14,2) NOT NULL, -- target stock T_i (order-up-to), not a reorder point
    ss_i                                NUMERIC(14,2) NOT NULL, -- safety stock
    status                                TEXT NOT NULL DEFAULT 'pending'
                                              CHECK (status IN ('pending', 'accepted', 'dismissed')),
    decided_at                              TIMESTAMPTZ,
    decided_by                                TEXT,
    generated_at                                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_key, planning_cycle_date)
);

CREATE INDEX IF NOT EXISTS ix_lp_recommendation_status ON LP_Recommendation (status, planning_cycle_date);

-- ============================================================
-- SECTION 5 — GET /bo-monitoring support (see OPEN QUESTION note above)
-- Computed at the grain the source data honestly supports (principal /
-- region / period), NOT per-SKU - a per-SKU number here would be
-- fabricated for Del Monte (BO/RMR is invoice grain, no SKU column).
--
-- Redefined 2026-08 (value-based, was unit-based): bo_units has no
-- source column anywhere in real RMR GS/BO data (confirmed against real
-- staged headers - only monetary fields exist in that file family,
-- Untaxed/Discount/Tax/Net Amount/Balance) and never will unless SSM's
-- reporting changes - so the old unit-based bo_rate was permanently
-- unrecoverable, not a temporary gap. net_amount is real and populated
-- on both sides, so bo_rate here is now (BO returns net_amount) /
-- (purchases net_amount) - a peso-based rate instead of a unit-based
-- one. Separately note: analytics/optimization/lp.py's w3 objective
-- term is implemented as generic storage cost, not spoilage/BO-linked -
-- no BO term exists anywhere in the LP objective at any grain.
--
-- Fixed 2026-08 (fan-out bug): a straight JOIN of Purchase_Fact and
-- SalesReturn_Fact on (principal, region, _period) is many-to-many on
-- both sides - real group sizes run up to 69 Purchase_Fact rows and 14
-- SalesReturn_Fact rows per key. Joining before aggregating multiplies
-- each side's SUM by the other side's row count, so bo_rate does not
-- reduce to the true ratio (confirmed: currently 0 real-world impact
-- because SalesReturn_Fact's real data only spans 2025-10/2025-11 while
-- Purchase_Fact's real periods don't overlap those months - but this is
-- dormant, not fixed, and the moment date coverage overlaps it will
-- silently inflate). Fix: aggregate each fact independently to one row
-- per (principal, region, _period) in its own CTE before joining -
-- the join itself is then one-to-one and can't fan out either side.
-- ============================================================

CREATE OR REPLACE VIEW BO_Monitoring_View AS
WITH purchases AS (
    SELECT principal, region, _period, SUM(net_amount) AS purchase_net_amount
    FROM Purchase_Fact
    GROUP BY principal, region, _period
),
bo_returns AS (
    SELECT principal, region, _period, SUM(net_amount) AS bo_net_amount
    FROM SalesReturn_Fact
    WHERE return_type = 'BO'
    GROUP BY principal, region, _period
)
SELECT
    p.principal,
    p.region,
    p._period,
    r.bo_net_amount,
    p.purchase_net_amount,
    CASE
        WHEN p.purchase_net_amount > 0
            THEN ROUND(r.bo_net_amount / p.purchase_net_amount * 100, 2)
        ELSE NULL  -- NULL, not 0: "no bad orders" and "we don't know" are different claims
    END AS bo_rate
FROM purchases p
LEFT JOIN bo_returns r
    ON r.principal = p.principal
   AND r.region = p.region
   AND r._period = p._period;

-- ============================================================
-- SECTION 6 — APPLICATION USERS (Story #89: login with hashed credentials)
-- Not part of the analytics warehouse - this is dashboard application
-- state (who may sign in), not ETL output. Kept in the same schema file
-- since it lives in the same Supabase/Postgres instance.
--
-- password_hash stores a bcrypt digest (via passlib) - the plaintext
-- password is never persisted or logged anywhere.
-- No seed rows here: the first admin account is created by a one-time
-- manual insert (see backend/scripts/seed_admin.py), not by this DDL,
-- so no default/shared credential ships in source control.
-- ============================================================

CREATE TABLE IF NOT EXISTS Users (
    user_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'staff' CHECK (role IN ('admin', 'staff')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One account per email in any capitalisation (migration 0034): UNIQUE
-- (email) above only catches exact matches.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_key ON Users (lower(email));

-- Per-user exceptions to the role's permission preset (migration 0034,
-- backend/permissions.py): granted = true adds a permission, false removes
-- it. Keys are checked in code, not here, so a new permission needs no
-- migration.
CREATE TABLE IF NOT EXISTS user_permission_override (
    user_id         BIGINT NOT NULL REFERENCES Users (user_id) ON DELETE CASCADE,
    permission_key  TEXT NOT NULL,
    granted         BOOLEAN NOT NULL,
    set_by          BIGINT REFERENCES Users (user_id) ON DELETE SET NULL,
    set_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, permission_key)
);

-- Two-step sign-in with an authenticator app (migration 0035,
-- backend/mfa.py). secret_encrypted is Fernet-encrypted with the server's
-- MFA_ENCRYPTION_KEY; enabled_at stays NULL until setup is confirmed with a
-- first code; recovery_hashes holds the sha256 of each unused recovery code.
CREATE TABLE IF NOT EXISTS user_mfa (
    user_id           BIGINT PRIMARY KEY REFERENCES Users (user_id) ON DELETE CASCADE,
    secret_encrypted  TEXT NOT NULL,
    enabled_at        TIMESTAMPTZ,
    last_used_step    BIGINT,
    recovery_hashes   TEXT[] NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Application audit trail (who did what, when) — dashboard application
-- state, not ETL output, same reasoning as Users above. Replaces the
-- earlier localStorage-only audit log (frontend/src/utils/auditLogger.js),
-- which never left the reporting browser and reset on cache clear.
CREATE TABLE IF NOT EXISTS Audit_Log (
    audit_log_key   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_email      TEXT NOT NULL,
    user_name       TEXT,
    role            TEXT,
    action          TEXT NOT NULL,
    details         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON Audit_Log (created_at DESC);

-- One row per sign-in (migration 0023) — login counts and session lengths
-- for the Audit Log page. Written by backend/routers/auth.py (login,
-- heartbeat, logout); length = COALESCE(ended_at, last_seen_at) - started_at.
CREATE TABLE IF NOT EXISTS user_session (
    session_key   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id    TEXT NOT NULL UNIQUE,
    user_id       BIGINT,
    user_email    TEXT NOT NULL,
    user_name     TEXT,
    role          TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ,
    ended_at      TIMESTAMPTZ,
    end_reason    TEXT CHECK (end_reason IN ('logout', 'idle')),
    source        TEXT NOT NULL DEFAULT 'tracked' CHECK (source IN ('tracked', 'audit_log_backfill'))
);

CREATE INDEX IF NOT EXISTS ix_user_session_user_email ON user_session (user_email);

-- ============================================================
-- SECTION 7 — Unified product-demand read shape (DEC-13)
-- Downstream models (ABC classification, SARIMA, LP - analytics/) need to
-- read Unilever and Del Monte demand through one common shape. Storage
-- stays grain-honest per DEC-02 (still PROPOSED - two marts, not decided
-- to physically merge) / DEC-03 (Unilever_SKU_Demand_Fact = real SKU
-- grain; SellOut_Fact = real category grain, Del Monte has no SKU column
-- anywhere) - this view unifies only the READ side, via Product_Dimension's
-- already-shared product_key, the same "two marts, one read shape"
-- resolution BO_Monitoring_View above uses for BO rate.
--
-- quantity_unit matters and must not be ignored: Unilever's quantity is
-- confirmed pieces (DEC-11, transform.normalize_quantities() sets it from
-- the source's reported sale_quantity_pieces). Del Monte's
-- SellOut_Fact.quantity has NO confirmed unit (DEC-11 explicitly left
-- this out of scope - no pack_size exists anywhere in Del Monte's files
-- to confirm it against). Do not treat the two "quantity" values as
-- directly comparable just because they share a column here -
-- quantity_unit tells a caller which is which. net_amount is NULL for
-- Unilever rows - that source has no revenue field at all, never
-- fabricated here, not a bug.
--
-- LEFT JOIN + COALESCE on the Del Monte side: SellOut_Fact.product_key is
-- nullable (unlike Unilever's NOT NULL FK), so a category not yet
-- resolved into Product_Dimension still surfaces here (with
-- product_key/grain NULL) rather than being silently dropped, matching
-- this project's no-silent-drop QC philosophy; COALESCE keeps
-- principal/category_path visible from SellOut_Fact's own columns even
-- when unresolved. Unilever_SKU_Demand_Fact.product_key is NOT NULL, so a
-- plain JOIN there always matches - no fallback needed.
--
-- Deliberately NOT mapped in models.py, same reasoning as
-- BO_Monitoring_View above - see the NOTE block at the end of that file.
-- No live Postgres instance has run this yet (Load has never run against
-- a live DB - see ARCHITECTURE.md status); verify against real data
-- before treating this as more than reviewed-by-construction.
-- ============================================================

CREATE OR REPLACE VIEW Product_Demand_View AS
SELECT
    pd.product_key, pd.principal, pd.grain, pd.sku_code,
    pd.category_path, pd.product_name,
    u.calendar_month AS period,
    u.quantity_sold   AS quantity,
    'pieces'            AS quantity_unit,
    NULL::numeric          AS net_amount,   -- Unilever SKU source has no revenue field
    u.region, u._src_file, u._src_sheet
FROM Unilever_SKU_Demand_Fact u
JOIN Product_Dimension pd ON pd.product_key = u.product_key   -- NOT NULL FK, always resolves

UNION ALL

SELECT
    pd.product_key,
    COALESCE(pd.principal, s.principal)         AS principal,
    pd.grain, pd.sku_code,
    COALESCE(pd.category_path, s.category_path) AS category_path,
    pd.product_name,
    s._period AS period,
    s.quantity AS quantity,
    'unconfirmed' AS quantity_unit,   -- DEC-11: no pack_size evidence exists for Del Monte
    s.net_amount,
    s.region, s._src_file, s._src_sheet
FROM SellOut_Fact s
LEFT JOIN Product_Dimension pd ON pd.product_key = s.product_key;

-- ============================================================
-- SECTION 8 — DEMO-DATA ISOLATION (Phase 4, 2026-08)
-- analytics/docs/DEL_MONTE_DEMO_DATA_SPEC.md:314's proposal, implemented:
-- "Recommend a documented, reusable view (e.g. Sales_Fact_Real) per fact
-- table that bakes in the filter, so nobody has to remember it by hand
-- each time." is_demo alone does not enforce anything - any query that
-- forgets `WHERE is_demo = false` silently includes synthetic rows. One
-- _Real view per fact table with an is_demo column removes that
-- discipline burden for every downstream query, report, and analytics
-- pipeline (ABC classification, SARIMA, LP) that must never see demo
-- data. Every real-only query used for the manuscript, the panel demo,
-- or any exported report should read from these views, not the base
-- fact tables, per that same spec note.
-- ============================================================

-- Fixed 2026-08 (analytics/db/migrations/0005_fix_real_views.sql): these six
-- views briefly carried an `OR principal = 'delmonte'` (and, for
-- Inventory_Fact_Real, an additional unconditional Unilever carve-out)
-- that made the predicate always-true for that principal — i.e. every
-- _Real view stopped excluding synthetic rows for Del Monte entirely, the
-- opposite of what this view family exists to guarantee. Restored to the
-- strict is_demo = false form below; see 0005's header for the full
-- incident writeup.

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
