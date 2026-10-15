-- 0053_demo_backcast.sql — schema `demo`: the 2021-01..2022-12 back-cast, and Unilever.
--
-- Kelvin, 2026-10-15: add 2021-01..2022-12 to the demonstration build for BOTH principals, behind
-- DM_DEMO_ENABLED (default off). SSM has no 2021-2022 data at all; real sales for both principals start 2023-01.
-- Structure only, and only inside schema demo (created by 0052); nothing in public changes.
--
-- Origin taxonomy, strictly distinct in data, API and reports:
--   real_copy     a real month, copied
--   interpolated  between two real months of the same series (anchored both sides)
--   bridged       across the 2024-03..2025-02 taxonomy change (real data on one side). NOT built: the hole is left
--                 unfilled (rule 14, decision 2026-10-15). The value exists so the taxonomy is one list everywhere.
--   backcast      2021-01..2022-12: no real data on either side; flat at the series' own level
--
-- Changes:
--   demo.run.principal            'delmonte' only  ->  'delmonte' | 'unilever'  (one run per principal)
--   demo.dm_category_sales.origin real_copy | interpolated  ->  + bridged | backcast
--   demo.unilever_sku_sales       new: Unilever at SKU grain (DEC-03), origin real_copy | backcast. A Unilever
--                                 month with no row is a real zero-sale month and is never generated.
--   demo.backcast_excluded        new: series left out of the back-cast, with why (both principals)
--
-- Same rails as 0052: is_demo CHECK, fill_source CHECK, no accuracy or band column (tests/demo/test_demo_schema.py).
-- Expected after applying: demo.unilever_sku_sales and demo.backcast_excluded exist, empty; existing demo rows unchanged.
-- Rollback: DROP TABLE demo.unilever_sku_sales, demo.backcast_excluded; then restore the two CHECKs from 0052.

ALTER TABLE demo.run DROP CONSTRAINT IF EXISTS run_principal_check;
ALTER TABLE demo.run ADD CONSTRAINT run_principal_check CHECK (principal IN ('delmonte', 'unilever'));

ALTER TABLE demo.dm_category_sales DROP CONSTRAINT IF EXISTS dm_category_sales_origin_check;
ALTER TABLE demo.dm_category_sales ADD CONSTRAINT dm_category_sales_origin_check
    CHECK (origin IN ('real_copy', 'interpolated', 'bridged', 'backcast'));

CREATE TABLE IF NOT EXISTS demo.unilever_sku_sales (
    run_id      BIGINT      NOT NULL REFERENCES demo.run (run_id) ON DELETE CASCADE,
    product_key BIGINT      NOT NULL,
    sku_code    TEXT        NOT NULL,
    period      TEXT        NOT NULL CHECK (period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    quantity    NUMERIC(14,2),                       -- NULL = a real blank capture (real_copy only)
    net_amount  NUMERIC(14,2),
    origin      TEXT        NOT NULL CHECK (origin IN ('real_copy', 'backcast')),
    is_demo     BOOLEAN     NOT NULL DEFAULT true CHECK (is_demo),
    fill_source TEXT        NOT NULL DEFAULT 'synthetic_dm_pipeline_demo'
                CHECK (fill_source = 'synthetic_dm_pipeline_demo'),
    PRIMARY KEY (run_id, product_key, period)
);
CREATE INDEX IF NOT EXISTS ix_demo_unilever_sku_sales_sku ON demo.unilever_sku_sales (run_id, sku_code);

CREATE TABLE IF NOT EXISTS demo.backcast_excluded (
    run_id            BIGINT      NOT NULL REFERENCES demo.run (run_id) ON DELETE CASCADE,
    series_key        TEXT        NOT NULL,           -- category_path (Del Monte) or sku_code (Unilever)
    reason            TEXT        NOT NULL,
    real_months       INTEGER     NOT NULL,
    first_real_period TEXT,
    is_demo           BOOLEAN     NOT NULL DEFAULT true CHECK (is_demo),
    fill_source       TEXT        NOT NULL DEFAULT 'synthetic_dm_pipeline_demo'
                      CHECK (fill_source = 'synthetic_dm_pipeline_demo'),
    PRIMARY KEY (run_id, series_key)
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA demo FROM anon';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA demo FROM authenticated';
    END IF;
END
$$;
