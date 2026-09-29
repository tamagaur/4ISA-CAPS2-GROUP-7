-- analytics/db/migrations/0029_product_dimension_supersedes_product_key.sql
--
-- Product_Dimension.supersedes_product_key: the product row this row replaces (an old code carried on under a new
-- one). Nullable self-reference, added EMPTY (Yuan, 2026-09-29): the 147 current-code pairs in
-- reports/dm_code_review_2026-09-21.csv and the 19 Unilever pairs wait on SSM confirming which code is current, so
-- no row is populated here. A value, once set, protects the superseded row from deletion (FK, no cascade).

BEGIN;

ALTER TABLE Product_Dimension ADD COLUMN IF NOT EXISTS supersedes_product_key BIGINT;
ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_supersedes_product_key_fkey;
ALTER TABLE Product_Dimension ADD CONSTRAINT product_dimension_supersedes_product_key_fkey
    FOREIGN KEY (supersedes_product_key) REFERENCES Product_Dimension (product_key);
COMMENT ON COLUMN Product_Dimension.supersedes_product_key IS
    'The product_key this row supersedes (old code -> current code). NULL until SSM confirms a pair; not populated by 0029.';

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE Product_Dimension DROP CONSTRAINT IF EXISTS product_dimension_supersedes_product_key_fkey;
-- ALTER TABLE Product_Dimension DROP COLUMN IF EXISTS supersedes_product_key;
-- COMMIT;
