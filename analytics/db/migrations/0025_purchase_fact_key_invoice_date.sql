-- analytics/db/migrations/0025_purchase_fact_key_invoice_date.sql
--
-- Purchase_Fact natural key: (invoice_num, principal, region)
--                         -> (invoice_num, principal, region, invoice_date).
--
-- Why: the 2026-09-21 completeness audit found the whole of September 2025
-- missing from Purchase_Fact. The Pangasinan sheet of "2025 SEPT.
-- PURCHASES.xlsx" reuses August's bill numbers (BILL/2025/0236-0253) on 18
-- purchases that carry their own date, PO number and untaxed amount. Under
-- the three-column key they were collapsed into the August rows as
-- duplicates. They are different purchases; the key has to tell them apart,
-- and invoice_date is the only distinguishing column this table stores.
-- config/source_of_truth.yaml's purchase natural_key changes with it.
--
-- NOT fixed here, for SSM: on those 18 rows the source's Tax and Net Amount
-- cells are also August's (untaxed + tax does not equal net). They load as
-- the source states them.
--
-- A NULL invoice_date stays distinct under plain UNIQUE, as region already
-- does. No real row has a NULL invoice_date today.

BEGIN;

ALTER TABLE Purchase_Fact DROP CONSTRAINT IF EXISTS purchase_fact_invoice_num_principal_region_key;
ALTER TABLE Purchase_Fact DROP CONSTRAINT IF EXISTS purchase_fact_invoice_num_principal_region_invoice_date_key;
ALTER TABLE Purchase_Fact
    ADD CONSTRAINT purchase_fact_invoice_num_principal_region_invoice_date_key
    UNIQUE (invoice_num, principal, region, invoice_date);

COMMIT;

-- Rollback (not run, kept for review; fails if two rows share the old key):
-- BEGIN;
-- ALTER TABLE Purchase_Fact DROP CONSTRAINT IF EXISTS purchase_fact_invoice_num_principal_region_invoice_date_key;
-- ALTER TABLE Purchase_Fact ADD CONSTRAINT purchase_fact_invoice_num_principal_region_key UNIQUE (invoice_num, principal, region);
-- COMMIT;
