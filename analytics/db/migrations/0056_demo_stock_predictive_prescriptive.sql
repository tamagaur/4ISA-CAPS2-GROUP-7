-- 0056_demo_stock_predictive_prescriptive.sql — schema `demo`: Del Monte stock on hand, the Unilever
-- demonstration forecast, and the Del Monte demonstration order plan.
--
-- Kelvin, 2026-10-16 (CLAUDE.md hard rule 2, the sanctioned demonstration exception). Structure only, inside
-- schema demo (created by 0052); nothing in public or any other schema is touched.
--
-- demo.dm_category_stock       Del Monte stock on hand, per category per month. There is NO real stock count at
--                              this grain anywhere in SSM's data (confirmed live 2026-10-16: Inventory_Fact_Real
--                              is SKU grain only, 597 products, and 0 of them carry a category_path), so every
--                              row is generated — origin is always 'generated_months_of_cover'
--                              (analytics/demo/stock.py), never 'real_copy'. Two layers of generated input feed
--                              any order plan built from this table: generated demand AND generated stock.
-- demo.unilever_sku_forecast   Unilever's one-step MA3 forecast (analytics/demo's generator), read from
--                              demo.unilever_sku_sales real_copy rows only — nearly identical to Forecast_Result
--                              since the last 3 months the method reads are real. Not wired into any endpoint:
--                              Unilever's real forecast already exists and is never replaced by this.
-- demo.dm_category_lp          The Del Monte demonstration order plan (safety stock, target stock, order
--                              quantity): analytics/demo/prescriptive.py's order-up-to, no allocation or
--                              warehouse ceiling (neither exists for Del Monte; see that module's docstring).
--
-- Expected after applying: three new tables in schema demo, all empty; no existing demo row changed; public row
-- counts unchanged. Rollback: DROP TABLE demo.dm_category_stock, demo.unilever_sku_forecast, demo.dm_category_lp;

CREATE TABLE IF NOT EXISTS demo.dm_category_stock (
    run_id            BIGINT      NOT NULL REFERENCES demo.run (run_id) ON DELETE CASCADE,
    category_path     TEXT        NOT NULL,
    product_key       BIGINT,
    period            TEXT        NOT NULL CHECK (period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    quantity_on_hand  NUMERIC(14,2) NOT NULL,
    months_of_cover   NUMERIC(8,4)  NOT NULL,
    origin            TEXT        NOT NULL DEFAULT 'generated_months_of_cover'
                      CHECK (origin = 'generated_months_of_cover'),
    is_demo           BOOLEAN     NOT NULL DEFAULT true CHECK (is_demo),
    fill_source       TEXT        NOT NULL DEFAULT 'synthetic_dm_pipeline_demo'
                      CHECK (fill_source = 'synthetic_dm_pipeline_demo'),
    PRIMARY KEY (run_id, category_path, period)
);

CREATE TABLE IF NOT EXISTS demo.unilever_sku_forecast (
    run_id            BIGINT      NOT NULL REFERENCES demo.run (run_id) ON DELETE CASCADE,
    product_key       BIGINT      NOT NULL,
    sku_code          TEXT        NOT NULL,
    forecast_period   TEXT        NOT NULL CHECK (forecast_period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    forecast_quantity NUMERIC(14,2) NOT NULL,
    method            TEXT        NOT NULL CHECK (method = 'ma3'),
    history_months    INTEGER     NOT NULL,
    is_demo           BOOLEAN     NOT NULL DEFAULT true CHECK (is_demo),
    fill_source       TEXT        NOT NULL DEFAULT 'synthetic_dm_pipeline_demo'
                      CHECK (fill_source = 'synthetic_dm_pipeline_demo'),
    PRIMARY KEY (run_id, product_key, forecast_period)
);
CREATE INDEX IF NOT EXISTS ix_demo_unilever_sku_forecast_sku ON demo.unilever_sku_forecast (run_id, sku_code);

CREATE TABLE IF NOT EXISTS demo.dm_category_lp (
    run_id            BIGINT      NOT NULL REFERENCES demo.run (run_id) ON DELETE CASCADE,
    category_path     TEXT        NOT NULL,
    product_key       BIGINT,
    period            TEXT        NOT NULL CHECK (period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    forecast_quantity NUMERIC(14,2) NOT NULL,
    stock_on_hand     NUMERIC(14,2) NOT NULL,
    sigma_d           NUMERIC(14,4) NOT NULL,
    safety_stock      NUMERIC(14,2) NOT NULL,
    target_stock      NUMERIC(14,2) NOT NULL,
    order_qty         NUMERIC(14,2) NOT NULL,
    method            TEXT        NOT NULL DEFAULT 'order_up_to_no_constraint'
                      CHECK (method = 'order_up_to_no_constraint'),
    is_demo           BOOLEAN     NOT NULL DEFAULT true CHECK (is_demo),
    fill_source       TEXT        NOT NULL DEFAULT 'synthetic_dm_pipeline_demo'
                      CHECK (fill_source = 'synthetic_dm_pipeline_demo'),
    PRIMARY KEY (run_id, category_path, period)
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
