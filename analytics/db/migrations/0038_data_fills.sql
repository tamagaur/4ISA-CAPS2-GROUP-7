-- 0038_data_fills.sql - DEC-31 (2026-10-02, Yuan): the fill step.
--
-- Every missing dataset is filled by one pipeline step (scripts/fill_missing.py,
-- analytics/etl/fills.py) that re-runs after every load. Real data always wins:
-- a cell with real rows is never filled, and its fill rows are removed in the
-- loading transaction. Four fills, each with its own source tag:
--
--   derived_stock_balance     Unilever receipts per SKU x month, from real stock
--                             and real sales (closing - opening + sold). Its own
--                             table: derived_receipt_fact. Not synthetic, not real.
--   synthetic_rate_transfer   Unilever returns = Unilever sales x Del Monte's real
--                             monthly return rate. salesreturn_fact, is_demo.
--   synthetic_category_split  Del Monte product-level sales = real sell-out totals
--                             x stock share. Its own table: sku_demand_fill. Preview only.
--   synthetic_v2_gap          Del Monte (and Unilever stock) gap months, from the
--                             synthetic v2 generator's own draws. Fact tables, is_demo.
--   synthetic_v2              the placeholder rows already in the fact tables
--                             (synthetic v2 cutover, 2026-09-28) - backfilled below.
--
-- The _Real views are NOT touched: they list their columns explicitly
-- (SELECT * is expanded when a view is created), so the new fill_source column
-- never reaches them and every fill row stays excluded by is_demo = false.
--
-- Apply order on public: 0032 -> 0033 -> 0035 -> 0036 -> 0038. This file needs
-- 0033 (etl_coverage, etl_load_event); it does not touch what 0035/0036 create.

BEGIN;

-- 1. fill_source on the six fact tables: NULL on real rows, a fill tag on demo rows.
ALTER TABLE sales_fact               ADD COLUMN IF NOT EXISTS fill_source TEXT;
ALTER TABLE purchase_fact            ADD COLUMN IF NOT EXISTS fill_source TEXT;
ALTER TABLE salesreturn_fact         ADD COLUMN IF NOT EXISTS fill_source TEXT;
ALTER TABLE sellout_fact             ADD COLUMN IF NOT EXISTS fill_source TEXT;
ALTER TABLE inventory_fact           ADD COLUMN IF NOT EXISTS fill_source TEXT;
ALTER TABLE unilever_sku_demand_fact ADD COLUMN IF NOT EXISTS fill_source TEXT;

UPDATE sales_fact               SET fill_source = 'synthetic_v2' WHERE is_demo AND fill_source IS NULL;
UPDATE purchase_fact            SET fill_source = 'synthetic_v2' WHERE is_demo AND fill_source IS NULL;
UPDATE salesreturn_fact         SET fill_source = 'synthetic_v2' WHERE is_demo AND fill_source IS NULL;
UPDATE sellout_fact             SET fill_source = 'synthetic_v2' WHERE is_demo AND fill_source IS NULL;
UPDATE inventory_fact           SET fill_source = 'synthetic_v2' WHERE is_demo AND fill_source IS NULL;
UPDATE unilever_sku_demand_fact SET fill_source = 'synthetic_v2' WHERE is_demo AND fill_source IS NULL;

-- A real row never carries a tag. A demo row written by an older generator block
-- may arrive untagged (NULL); the fill step tags every row it writes.
ALTER TABLE sales_fact ADD CONSTRAINT sales_fact_fill_source_check CHECK (
    fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap')));
ALTER TABLE purchase_fact ADD CONSTRAINT purchase_fact_fill_source_check CHECK (
    fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap')));
ALTER TABLE salesreturn_fact ADD CONSTRAINT salesreturn_fact_fill_source_check CHECK (
    fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap', 'synthetic_rate_transfer')));
ALTER TABLE sellout_fact ADD CONSTRAINT sellout_fact_fill_source_check CHECK (
    fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap')));
ALTER TABLE inventory_fact ADD CONSTRAINT inventory_fact_fill_source_check CHECK (
    fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap')));
ALTER TABLE unilever_sku_demand_fact ADD CONSTRAINT unilever_sku_demand_fact_fill_source_check CHECK (
    fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap')));

-- 2. Derived receipts (item 1). Pieces = cases x pack + loose pieces (the SOH's
-- quantity_pieces is the remainder below one case). balance is signed and kept;
-- receipt = max(balance, 0); a negative balance is flagged, never hidden.
CREATE TABLE IF NOT EXISTS derived_receipt_fact (
    derived_receipt_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    principal           TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    product_key         BIGINT NOT NULL REFERENCES product_dimension (product_key),
    sku_code            TEXT NOT NULL,
    _period             TEXT NOT NULL CHECK (_period ~ '^[0-9]{4}-[0-9]{2}$'),
    opening_pieces      NUMERIC NOT NULL,
    closing_pieces      NUMERIC NOT NULL,
    sold_pieces         NUMERIC NOT NULL,
    balance_pieces      NUMERIC NOT NULL,
    receipt_pieces      NUMERIC NOT NULL CHECK (receipt_pieces = GREATEST(balance_pieces, 0)),
    unit_cost_per_piece NUMERIC,
    receipt_value       NUMERIC,
    flag                TEXT CHECK (flag IS NULL OR flag = 'negative_balance'),
    fill_source         TEXT NOT NULL DEFAULT 'derived_stock_balance' CHECK (fill_source = 'derived_stock_balance'),
    is_demo             BOOLEAN NOT NULL DEFAULT true CHECK (is_demo),
    run_id              TEXT NOT NULL,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT derived_receipt_fact_flag_matches_balance CHECK (
        (balance_pieces < 0 AND flag = 'negative_balance') OR (balance_pieces >= 0 AND flag IS NULL)),
    CONSTRAINT derived_receipt_fact_key UNIQUE (principal, sku_code, _period)
);
CREATE INDEX IF NOT EXISTS ix_derived_receipt_fact_period ON derived_receipt_fact (principal, _period);
COMMENT ON TABLE derived_receipt_fact IS
    'Estimated receipts (migration 0038, DEC-31): closing - opening stock + sales, real inputs only. An estimate, not a purchase record: never read by models, shown as a labelled estimate. Removed for a month once real purchases for it load.';

-- 3. Del Monte product-level sales (item 3): a month's REAL sell-out total split
-- across SKUs by stock share. split_level 'principal' today (D1 b); 'category'
-- once a reviewed SKU -> category map exists (config/alias_tables/delmonte_sku_category.csv).
CREATE TABLE IF NOT EXISTS sku_demand_fill (
    sku_demand_fill_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    principal           TEXT NOT NULL CHECK (principal = 'delmonte'),
    product_key         BIGINT NOT NULL REFERENCES product_dimension (product_key),
    sku_code            TEXT NOT NULL,
    _period             TEXT NOT NULL CHECK (_period ~ '^[0-9]{4}-[0-9]{2}$'),
    split_level         TEXT NOT NULL CHECK (split_level IN ('principal', 'category')),
    category_path       TEXT,
    stock_share         NUMERIC NOT NULL CHECK (stock_share > 0 AND stock_share <= 1),
    quantity            NUMERIC,
    net_amount          NUMERIC,
    fill_source         TEXT NOT NULL DEFAULT 'synthetic_category_split' CHECK (fill_source = 'synthetic_category_split'),
    is_demo             BOOLEAN NOT NULL DEFAULT true CHECK (is_demo),
    run_id              TEXT NOT NULL,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sku_demand_fill_level_category CHECK (
        (split_level = 'principal' AND category_path IS NULL) OR (split_level = 'category' AND category_path IS NOT NULL)),
    CONSTRAINT sku_demand_fill_key UNIQUE (product_key, _period)
);
CREATE INDEX IF NOT EXISTS ix_sku_demand_fill_period ON sku_demand_fill (_period);
COMMENT ON TABLE sku_demand_fill IS
    'Demo (migration 0038, DEC-31): Del Monte product sales estimated from total sell-out x share of stock (not of sales). SSM has no product-level Del Monte sales. Preview only; never read by a real-mode figure.';

-- 4. Coverage and the load ledger learn about fills.
ALTER TABLE etl_coverage ADD COLUMN IF NOT EXISTS derived_rows INTEGER NOT NULL DEFAULT 0;
ALTER TABLE etl_coverage DROP CONSTRAINT IF EXISTS etl_coverage_status_check;
ALTER TABLE etl_coverage ADD CONSTRAINT etl_coverage_status_check
    CHECK (status IN ('real', 'derived', 'synthetic', 'partial', 'missing'));
ALTER TABLE etl_load_event ADD COLUMN IF NOT EXISTS fill_rows_added INTEGER NOT NULL DEFAULT 0;
ALTER TABLE etl_load_event ADD COLUMN IF NOT EXISTS fill_rows_removed INTEGER NOT NULL DEFAULT 0;

-- 5. Same exposure as 0033's tables: service role only.
ALTER TABLE derived_receipt_fact ENABLE ROW LEVEL SECURITY;
ALTER TABLE sku_demand_fill ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON derived_receipt_fact, sku_demand_fill FROM %I', r);
            EXECUTE format('REVOKE ALL ON SEQUENCE derived_receipt_fact_derived_receipt_key_seq, '
                           'sku_demand_fill_sku_demand_fill_key_seq FROM %I', r);
        END IF;
    END LOOP;
END
$$;

COMMIT;
