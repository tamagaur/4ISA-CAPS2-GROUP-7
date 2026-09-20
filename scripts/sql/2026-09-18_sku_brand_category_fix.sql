-- SKU Management / ABC page fix — brand + category_path cleanup
-- Prepared 2026-09-18 (Audrey's recon, items 2-4). Run these yourself,
-- in order. Each step's expected row count is stated before it runs.

-- ============================================================
-- STEP 0: BACKUP (run first, always)
-- ============================================================
CREATE TABLE public.product_dimension_backup_20260918 AS
SELECT * FROM public.product_dimension;
-- Expect: 17,407 rows copied.

-- ============================================================
-- STEP 1: SCRATCH VERIFICATION (run against a scratch copy first)
-- ============================================================
CREATE SCHEMA IF NOT EXISTS ssm_sku_brand_fix;
CREATE TABLE ssm_sku_brand_fix.product_dimension AS
SELECT * FROM public.product_dimension;

-- 1a. product_key 50186 ('False' brand/category): DELETE, not rename.
--     Renaming category_path to 'UNCLASSIFIED' collides with the
--     UNIQUE (principal, grain, sku_code, category_path) constraint —
--     product_key 54990 is already the real delmonte/category/NULL/
--     UNCLASSIFIED bucket (124 sellout_fact + 22 sellout_fact_real rows
--     attached). Verified 2026-09-18: 50186 has ZERO rows in all 10
--     tables with a product_key column (sellout_fact*, inventory_fact*,
--     unilever_*_demand_fact*, lp_recommendation, forecast_result,
--     sku_traits, sku_segment, abc_classification) — an orphan dimension
--     row, nothing to reassign. Safe to delete outright.
--     Expect: 1 row.
DELETE FROM ssm_sku_brand_fix.product_dimension
WHERE product_key = 50186;

-- 1b. Mojibake apostrophe fix for the 2 LADY[mojibake]S rows
--     (source-level fix also applied in scripts/run_canonical_load.py's
--     _load_soh_snapshot(); this repairs the 2 rows already loaded).
--     Expect: 2 rows.
UPDATE ssm_sku_brand_fix.product_dimension
SET brand = 'LADY''S',
    product_name = REGEXP_REPLACE(product_name, '[�’‘]', '''', 'g'),
    brand_source = 'soh_first_token_rule'
WHERE product_key IN (120, 121);

-- 1c. Alias-table reapply WITHOUT COALESCE (existing brand rows only;
--     rows here already had a token the alias table maps to a fuller
--     canonical brand name). Expect: 209 rows (41+89+1+22+3+4+27+3+19).
UPDATE ssm_sku_brand_fix.product_dimension
SET brand = CASE brand
        WHEN 'LADYS' THEN 'LADY''S'
        WHEN 'CREAM' THEN 'CREAMSILK'
        WHEN 'POND''S' THEN 'PONDS'
        WHEN 'CLOSE' THEN 'CLOSEUP'
        WHEN 'DR.KAUFMAN' THEN 'DR.KAUFMANN'
        WHEN 'BRZ' THEN 'BREEZE'
        WHEN 'REX' THEN 'REXONA'
        WHEN 'SRF' THEN 'SURF'
        WHEN 'BABY' THEN 'DOVE'
        ELSE brand
    END,
    brand_source = 'soh_first_token_rule'
WHERE principal = 'unilever'
  AND brand IN ('LADYS','CREAM','POND''S','CLOSE','DR.KAUFMAN','BRZ','REX','SRF','BABY');

-- 1d. Del Monte's 99 fake "brands" (first category_path segment, not a
--     real brand) -> NULL. Expect: 98 rows (50186 was one of the 99;
--     it's gone after 1a's DELETE, so 1d only sees the remaining 98).
UPDATE ssm_sku_brand_fix.product_dimension
SET brand = NULL, brand_source = NULL
WHERE principal = 'delmonte' AND brand IS NOT NULL;

-- Verify against scratch:
SELECT principal, brand IS NULL AS brand_null, count(*)
FROM ssm_sku_brand_fix.product_dimension GROUP BY 1,2 ORDER BY 1,2;
-- Expect: delmonte all NULL (15,308 = 15,309 - 1 deleted); unilever
-- non-null count unchanged at 2,098 (values remapped, not dropped).
-- Total row count: 17,406 (17,407 - 1 deleted).

-- ============================================================
-- STEP 2: PUBLIC APPLY (only after step 1's scratch output matches
-- the expected counts above)
-- ============================================================
-- 2a. Same reasoning as 1a — DELETE, not rename (see comment there).
DELETE FROM public.product_dimension
WHERE product_key = 50186;

-- 2b.
UPDATE public.product_dimension
SET brand = 'LADY''S',
    product_name = REGEXP_REPLACE(product_name, '[�’‘]', '''', 'g'),
    brand_source = 'soh_first_token_rule'
WHERE product_key IN (120, 121);

-- 2c.
UPDATE public.product_dimension
SET brand = CASE brand
        WHEN 'LADYS' THEN 'LADY''S'
        WHEN 'CREAM' THEN 'CREAMSILK'
        WHEN 'POND''S' THEN 'PONDS'
        WHEN 'CLOSE' THEN 'CLOSEUP'
        WHEN 'DR.KAUFMAN' THEN 'DR.KAUFMANN'
        WHEN 'BRZ' THEN 'BREEZE'
        WHEN 'REX' THEN 'REXONA'
        WHEN 'SRF' THEN 'SURF'
        WHEN 'BABY' THEN 'DOVE'
        ELSE brand
    END,
    brand_source = 'soh_first_token_rule'
WHERE principal = 'unilever'
  AND brand IN ('LADYS','CREAM','POND''S','CLOSE','DR.KAUFMAN','BRZ','REX','SRF','BABY');

-- 2d.
UPDATE public.product_dimension
SET brand = NULL, brand_source = NULL
WHERE principal = 'delmonte' AND brand IS NOT NULL;

-- Final check:
SELECT principal, brand IS NULL AS brand_null, count(*)
FROM public.product_dimension GROUP BY 1,2 ORDER BY 1,2;

-- ============================================================
-- ROLLBACK (if needed)
-- ============================================================
-- BEGIN;
-- DELETE FROM public.product_dimension;
-- INSERT INTO public.product_dimension SELECT * FROM public.product_dimension_backup_20260918;
-- COMMIT;
