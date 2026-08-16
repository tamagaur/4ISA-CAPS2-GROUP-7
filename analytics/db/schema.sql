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
    invoice_num            TEXT,             -- kept for schema-generality; see note below on why it's not in the key
    return_type             TEXT NOT NULL CHECK (return_type IN ('GS', 'BO')),
    return_date              DATE REFERENCES Date_Dimension(date_key),
    principal                 TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    region                     TEXT,
    net_amount                  NUMERIC(14,2),
    bo_units                     NUMERIC(14,2),  -- always NULL for real data - see BO_Monitoring_View note below, no source column exists
    _src_file                     TEXT NOT NULL,
    _src_sheet                     TEXT NOT NULL,
    _period                         TEXT NOT NULL,
    -- Fixed 2026-08: invoice_num dropped from the key. Confirmed against
    -- real rmr_gs_bo data (the sole source for this table) that
    -- invoice_num never exists as a producible column at all (0/538 real
    -- rows, not just mostly-null) - Postgres UNIQUE treats NULL <> NULL,
    -- so including a column that's always NULL doesn't protect against
    -- real duplicates; it was a silent no-op. Column kept on the table
    -- itself in case a future source family actually has one.
    UNIQUE (return_slip_num, principal, region, return_type)
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
    -- DEC-11: comparable-unit quantity, Del Monte only for now — set
    -- directly from the source file's PCS (pieces) column via
    -- transform.normalize_quantities(). CAS/PKG (cases/packages) are
    -- deliberately NOT converted into this field: no confirmed pack_size
    -- exists anywhere in Del Monte's files, so a conversion would be
    -- fabricated, not derived. See config/column_maps/inventory_sign_off.yaml.
    quantity_pieces          NUMERIC(14,2),
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
    role            TEXT NOT NULL DEFAULT 'staff' CHECK (role IN ('admin', 'staff')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
