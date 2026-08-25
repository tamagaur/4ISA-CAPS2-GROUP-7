-- analytics/db/migrations/0007_null_phantom_category_sku_codes.sql
--
-- Nulls Product_Dimension.sku_code on the 99 grain='category' Del Monte
-- rows that carried a fabricated, 9-plus-3-letters-plus-5-digits-shaped
-- code (e.g. '9NEO37594' for category 'ACE/BASE'). schema.sql:106 has
-- always documented sku_code as "NULL for Del Monte category rows"; these
-- 99 rows (minted in commit 4df2501, alongside the SellOut_Fact
-- reassignment reverted by 0006) never matched that contract and do not
-- appear anywhere in raw or staged source data under any code — confirmed
-- by an exhaustive search across every staging table before this migration
-- was written.
--
-- Safe: no FK targets sku_code (only product_key does); the
-- UNIQUE(principal, grain, sku_code, category_path) constraint treats
-- multiple NULLs as distinct, so no conflict; backend/routers/abc.py and
-- backend/routers/sku.py already COALESCE(sku_code, category_path), so
-- these rows immediately start behaving as originally designed.
--
-- Also reverts one live-app edit made against phantom row 9NEO37594
-- (product_key 50133) before its true nature was known: Audit_Log shows
-- an admin used the SKU Management UI to set Unit Price 150 and Status
-- DISABLED on 2026-08-24. That edit was made under the false premise that
-- the row was a real, distinct SKU; reverting both fields back to their
-- pre-edit values (NULL / ACTIVE) so the /ACE/BASE category isn't
-- silently carrying a fabricated price or excluded from ACTIVE-scoped
-- queries for a reason nobody intended. Audit_Log's own row is left
-- untouched — it's a historical record, not a live reference.
--
-- ALREADY APPLIED live (executed and committed during this remediation
-- pass — 99 rows nulled, 0 remaining, row 50133 confirmed reverted).
--
-- Idempotent: both UPDATEs' WHERE clauses only match already-unfixed rows,
-- safe to re-run.

BEGIN;

UPDATE Product_Dimension
SET sku_code = NULL
WHERE principal = 'delmonte' AND grain = 'category' AND sku_code IS NOT NULL;

UPDATE Product_Dimension
SET unit_price = NULL, status = 'ACTIVE'
WHERE product_key = 50133 AND sku_code IS NULL;

COMMIT;

-- Rollback (not run, kept for review — reintroduces the phantom codes,
-- there is no reason to ever run this):
-- BEGIN;
-- UPDATE Product_Dimension SET sku_code = category_path -- lossy, original
--   codes were never derived from category_path and cannot be reconstructed
-- WHERE principal='delmonte' AND grain='category';
-- COMMIT;
