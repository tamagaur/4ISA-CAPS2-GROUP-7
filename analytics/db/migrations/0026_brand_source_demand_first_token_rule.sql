-- analytics/db/migrations/0026_brand_source_demand_first_token_rule.sql
--
-- Product_Dimension.brand_source: allow 'demand_first_token_rule'.
--
-- Why: the Unilever demand file's second column is the product description
-- (config/column_maps/unilever_sku.yaml -> product_name). For the SKUs with
-- no SOH row, run_category_brand_backfill() (scripts/run_canonical_load.py)
-- reads the brand from that description's first token and labels where it
-- came from. The CHECK added by migration 0011 only knew the SOH source, so
-- the 2026-09-21 scratch rebuild failed on it. Decision D11 (Yuan,
-- 2026-09-22): widen the CHECK rather than leave brand_source NULL.

BEGIN;

ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_brand_source_check;
ALTER TABLE Product_Dimension
    ADD CONSTRAINT product_dimension_brand_source_check
    CHECK (brand_source IS NULL OR brand_source IN ('soh_first_token_rule', 'demand_first_token_rule'));

COMMIT;

-- Rollback (not run, kept for review; fails while any row holds the new value):
-- BEGIN;
-- ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_brand_source_check;
-- ALTER TABLE Product_Dimension ADD CONSTRAINT product_dimension_brand_source_check
--     CHECK (brand_source IS NULL OR brand_source IN ('soh_first_token_rule'));
-- COMMIT;
