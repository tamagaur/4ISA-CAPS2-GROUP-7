-- 0057_demo_forward_fill_and_unilever_lp.sql — schema `demo`: a fifth Del Monte sales origin, a flag on the
-- Unilever demonstration forecast, which side of a demo order plan's inputs is real vs generated, and the
-- Unilever demonstration order plan itself (real stock, demo forecast).
--
-- Kelvin, 2026-10-16: "fill every layer, no empty cards" — the standing instruction behind this migration.
-- Structure only, inside schema demo; nothing in public or any other schema is touched.
--
-- demo.dm_category_sales.origin  + 'forward_filled': a LIVE 2025 Del Monte category (BEVERAGE, CULINARY, DAIRY,
--   FRUITS, INNOVATION) whose real data stops before the window ends is carried forward flat at its own level
--   (analytics/demo/backcast.py's bridge_series, a new seed stream) — NOT a taxonomy change, so never 'bridged'.
--   Only DAIRY needs this today (real data 2025-03..2025-06 only; the other four already reach 2025-12).
-- demo.dm_category_lp.stock_source            'generated': every row's stock comes from demo.dm_category_stock.
-- demo.unilever_sku_forecast.blank_capture_filled  true when one blank-capture month inside the SKU's last-3-
--   real-months MA3 window was filled with the mean of the other two for this average ONLY — the sales chart
--   (demo.unilever_sku_sales) is never touched, so a blank still renders as blank there.
-- demo.unilever_sku_lp          Unilever demonstration order plan: demo FORECAST and demo SIGMA (full history,
--   including the 2021-22 back-cast — sigma is expected to move, see docs/DEMO_DATA.md) against REAL stock on
--   hand and REAL cost (the same scripts/run_lp.py fetchers the real path uses: fetch_stock_and_cost,
--   fetch_stock_counts, opening_counts). stock_source 'real' says so on every row, since it is not the same
--   confidence as Del Monte's fully-generated plan.
--
-- Expected after applying: dm_category_sales accepts 'forward_filled'; dm_category_lp has stock_source (existing
-- rows backfilled 'generated'); unilever_sku_forecast has blank_capture_filled (existing rows false); a new,
-- empty demo.unilever_sku_lp table. No existing row's values change; public row counts unchanged.
-- Rollback: DROP TABLE demo.unilever_sku_lp; ALTER TABLE demo.dm_category_lp DROP COLUMN stock_source;
-- ALTER TABLE demo.unilever_sku_forecast DROP COLUMN blank_capture_filled; restore 0055's dm_category_sales CHECK.

ALTER TABLE demo.dm_category_sales DROP CONSTRAINT IF EXISTS dm_category_sales_origin_check;
ALTER TABLE demo.dm_category_sales ADD CONSTRAINT dm_category_sales_origin_check
    CHECK (origin IN ('real_copy', 'interpolated', 'bridged', 'backcast', 'forward_filled'));

ALTER TABLE demo.dm_category_lp
    ADD COLUMN IF NOT EXISTS stock_source TEXT NOT NULL DEFAULT 'generated'
    CHECK (stock_source IN ('real', 'generated'));
COMMENT ON COLUMN demo.dm_category_lp.stock_source IS
    'Always generated for Del Monte: demo.dm_category_stock has no real anchor. Migration 0057.';

ALTER TABLE demo.unilever_sku_forecast
    ADD COLUMN IF NOT EXISTS blank_capture_filled BOOLEAN NOT NULL DEFAULT false;
COMMENT ON COLUMN demo.unilever_sku_forecast.blank_capture_filled IS
    'true when a blank-capture month inside the MA3 window was filled (mean of the other two) for this average '
    'only; demo.unilever_sku_sales itself is never touched. Migration 0057.';

CREATE TABLE IF NOT EXISTS demo.unilever_sku_lp (
    run_id            BIGINT      NOT NULL REFERENCES demo.run (run_id) ON DELETE CASCADE,
    product_key       BIGINT      NOT NULL,
    sku_code          TEXT        NOT NULL,
    period            TEXT        NOT NULL CHECK (period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    forecast_quantity NUMERIC(14,2) NOT NULL,
    stock_on_hand     NUMERIC(14,2) NOT NULL,
    sigma_d           NUMERIC(14,4) NOT NULL,
    safety_stock      NUMERIC(14,2) NOT NULL,
    target_stock      NUMERIC(14,2) NOT NULL,
    order_qty         NUMERIC(14,2) NOT NULL,
    stock_source      TEXT        NOT NULL DEFAULT 'real' CHECK (stock_source = 'real'),
    method            TEXT        NOT NULL DEFAULT 'lp' CHECK (method = 'lp'),
    is_demo           BOOLEAN     NOT NULL DEFAULT true CHECK (is_demo),
    fill_source       TEXT        NOT NULL DEFAULT 'synthetic_dm_pipeline_demo'
                      CHECK (fill_source = 'synthetic_dm_pipeline_demo'),
    PRIMARY KEY (run_id, product_key, period)
);
CREATE INDEX IF NOT EXISTS ix_demo_unilever_sku_lp_sku ON demo.unilever_sku_lp (run_id, sku_code);

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
