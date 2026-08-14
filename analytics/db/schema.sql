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
    product_name    TEXT,
    pack_size       TEXT,
    brand           TEXT,
    UNIQUE (principal, grain, sku_code, category_path)
);

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

CREATE TABLE IF NOT EXISTS Sales_Fact (
    sales_key           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_num         TEXT NOT NULL,
    invoice_date        DATE REFERENCES Date_Dimension(date_key),
    principal           TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
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
    _src_file                TEXT NOT NULL,
    _src_sheet                TEXT NOT NULL,
    _period                   TEXT NOT NULL,
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
    invoice_num            TEXT,             -- fallback natural-key half when slip # is blank
    return_type             TEXT NOT NULL CHECK (return_type IN ('GS', 'BO')),
    return_date              DATE REFERENCES Date_Dimension(date_key),
    principal                 TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    region                     TEXT,
    net_amount                  NUMERIC(14,2),
    bo_units                     NUMERIC(14,2),  -- populated only when return_type = 'BO'
    _src_file                     TEXT NOT NULL,
    _src_sheet                     TEXT NOT NULL,
    _period                         TEXT NOT NULL,
    UNIQUE (return_slip_num, invoice_num, principal, region, return_type)
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
    snapshot_date        DATE NOT NULL REFERENCES Date_Dimension(date_key),
    principal             TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    region                 TEXT,
    quantity_on_hand        NUMERIC(14,2),
    _src_file                TEXT NOT NULL,
    _src_sheet                TEXT NOT NULL,
    UNIQUE (sku_code, snapshot_date, region)  -- DEC-04 natural key (config/source_of_truth.yaml: inventory)
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
    quantity_sold             NUMERIC(14,2),
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
CREATE TABLE IF NOT EXISTS ABC_Classification (
    classification_key      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_key                BIGINT NOT NULL REFERENCES Product_Dimension(product_key),
    principal                    TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    classification_period          TEXT NOT NULL,   -- 'YYYY-MM'
    tier                             TEXT NOT NULL CHECK (tier IN ('A', 'B', 'C')),
    revenue_share                     NUMERIC(7,4),  -- this item's share of period revenue
    cumulative_share                   NUMERIC(7,4), -- running total used for the 80/95 cut points
    computed_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_key, classification_period)
);

CREATE INDEX IF NOT EXISTS ix_abc_classification_tier ON ABC_Classification (tier, classification_period);

-- Category A only (MAPE < 20% gate, per README pipeline diagram) -
-- Unilever SKU grain, since SARIMA per DEC-03 only runs where real
-- per-SKU demand exists.
CREATE TABLE IF NOT EXISTS Forecast_Result (
    forecast_key      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_key         BIGINT NOT NULL REFERENCES Product_Dimension(product_key),
    forecast_date         DATE NOT NULL,
    forecast_value          NUMERIC(14,2) NOT NULL,
    confidence_lower          NUMERIC(14,2),
    confidence_upper          NUMERIC(14,2),
    mape                        NUMERIC(6,3),        -- must be < 20.0 to gate into LP_Recommendation
    model_params                  JSONB,             -- SARIMA (p,d,q)(P,D,Q,s) etc. - stored as given, not re-derived
    generated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_key, forecast_date)
);

CREATE INDEX IF NOT EXISTS ix_forecast_result_product ON Forecast_Result (product_key);

-- SS_i = Z x sigma_di (Z=1.28, 90% service level); ROP_i = Y_hat_(t+1,i) + SS_i;
-- Q_i from LP minimizing Z = w1*TC - w2*SL + w3*SC (w1=.45, w2=.35, w3=.20).
-- status supports the dashboard's Accept/Dismiss write-back (README Phase 7).
CREATE TABLE IF NOT EXISTS LP_Recommendation (
    recommendation_key      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_key                BIGINT NOT NULL REFERENCES Product_Dimension(product_key),
    planning_cycle_date          DATE NOT NULL,
    q_i                             NUMERIC(14,2) NOT NULL,   -- recommended order quantity
    rop_i                             NUMERIC(14,2) NOT NULL, -- reorder point
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
-- Drop/replace this view once the open question above is resolved.
-- ============================================================

CREATE OR REPLACE VIEW BO_Monitoring_View AS
SELECT
    p.principal,
    p.region,
    p._period,
    SUM(r.bo_units)                                   AS bo_units,
    SUM(p.units_received)                              AS units_received,
    CASE
        WHEN SUM(p.units_received) > 0
            THEN ROUND(SUM(r.bo_units) / SUM(p.units_received) * 100, 2)
        ELSE NULL  -- NULL, not 0: "no bad orders" and "we don't know" are different claims
    END                                                  AS bo_rate
FROM Purchase_Fact p
LEFT JOIN SalesReturn_Fact r
    ON r.principal = p.principal
   AND r.region = p.region
   AND r._period = p._period
   AND r.return_type = 'BO'
GROUP BY p.principal, p.region, p._period;

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
    role            TEXT NOT NULL DEFAULT 'staff' CHECK (role IN ('admin', 'staff')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
