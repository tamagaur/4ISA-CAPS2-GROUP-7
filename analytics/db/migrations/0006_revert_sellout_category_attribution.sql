-- analytics/db/migrations/0006_revert_sellout_category_attribution.sql
--
-- Reverts scripts/map_dm_sales_to_skus.py's random.choice() reassignment
-- of Del Monte SellOut_Fact.product_key from category grain to individual
-- SKU-grain product keys. That script (added commit 4df2501, executed
-- against the live DB on or after 2026-08-24) directly violates DEC-03
-- (ARCHITECTURE.md:73,93 — Del Monte forecasting/recommendation grain is
-- category, never a per-SKU allocation) and an existing in-repo guardrail
-- (analytics/db/models.py:271-274, SellOutFact model: "do not join a
-- fabricated per-SKU allocation here").
--
-- Reversible with zero data loss: the reassignment script only ever wrote
-- SellOut_Fact.product_key, never category_path. Every affected row still
-- carries its true original category_path (with a leading '/', e.g.
-- '/ACE/BASE') — stripping that leading slash matches all 8,368 affected
-- rows exactly back to their Product_Dimension grain='category' row
-- (confirmed 1:1, zero unmatched, before this migration was written).
--
-- ALREADY APPLIED live (executed and committed during this remediation
-- pass — row count conserved at 8,368, all rows now grain='category').
-- Recorded here so the fix is reproducible from scratch on a fresh DB
-- restore, not just something that happened once in a session.
--
-- Not idempotent in the strict sense (re-running after a first successful
-- run matches 0 rows and is a safe no-op, since the UPDATE's WHERE clause
-- only ever matches rows whose category_path corresponds to a currently
-- mismatched product_key) — safe to re-run.

BEGIN;

UPDATE SellOut_Fact s
SET product_key = pd.product_key
FROM Product_Dimension pd
WHERE pd.principal = 'delmonte'
  AND pd.grain = 'category'
  AND pd.category_path = LTRIM(s.category_path, '/')
  AND s.principal = 'delmonte'
  AND s.product_key != pd.product_key;

COMMIT;

-- Rollback: not meaningful for this migration. The pre-image (the random
-- per-row SKU assignment the original script produced) was never
-- deterministic and was never itself a valid state — there is nothing
-- correct to roll back to. If this UPDATE's effect must ever be undone for
-- an unrelated reason, take a fresh `SELECT sellout_key, product_key FROM
-- SellOut_Fact WHERE principal='delmonte'` snapshot first; there is no
-- generic reverse statement to keep here.
