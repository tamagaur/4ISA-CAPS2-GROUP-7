-- analytics/db/migrations/0030_product_dimension_sku_code_format.sql
--
-- sku_code format CHECKs on Product_Dimension (product-master queue, reports/PROJECT_STATE_2026-09.md 17.3 item 2;
-- applied last, as planned). Recounted 2026-09-29 before adding: every existing code passes - 2,098 Unilever and
-- 597 Del Monte SKU rows here, and 2,695 real + 1,305 synthetic distinct codes in the fact tables.
--
-- Unilever: STRICT, exactly 8 digits - the format is uniform.
-- Del Monte: DELIBERATELY LOOSE - rejects only what is clearly not a code: contains whitespace, or contains no digit
-- at all (the class of the 7 banner rows: 'PROMO PACK', 'KIKKOMAN', ...). A tight pattern fitted to today's shapes
-- (9AAA99999, AAA99999, 999-99999, AAAA9999, 9AAA9999) would fail a rebuild the first time Del Monte issues a new
-- code family. NULL sku_code (the category-grain rows) is not constrained.

BEGIN;

ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_unilever_sku_code_format;
ALTER TABLE Product_Dimension ADD CONSTRAINT product_dimension_unilever_sku_code_format
    CHECK (principal <> 'unilever' OR sku_code IS NULL OR sku_code ~ '^[0-9]{8}$');
ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_delmonte_sku_code_format;
ALTER TABLE Product_Dimension ADD CONSTRAINT product_dimension_delmonte_sku_code_format
    CHECK (principal <> 'delmonte' OR sku_code IS NULL OR (sku_code ~ '[0-9]' AND sku_code !~ '\s'));

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_unilever_sku_code_format;
-- ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_delmonte_sku_code_format;
-- COMMIT;
