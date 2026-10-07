-- 0045_unit_cost_lead_time.sql — Product_Dimension.unit_cost (new) and lead_time_days (existing, unfilled).
--
--   unit_cost      = cost PER PIECE, in pesos: latest month's average unit_cost_per_case (inventory_fact_real,
--                    cost > 0) / numeric pack_size. The same derivation scripts/run_lp.py STOCK_AND_COST_QUERY uses.
--                    It is what SSM pays, not a selling price. unit_price stays NULL for a future selling price.
--                    NULL where there is no cost or no numeric pack_size.
--   lead_time_days = 3 for every product: SSM meeting 2026-09-28 (Unilever 2-3 days, Del Monte 2-3 days, longer in
--                    seasonal stocking). Flagged 'pending_confirmation' until SSM confirms.
--
-- Expected (live, 2026-10-07): unit_cost 1,712 Unilever + 0 Del Monte; lead_time_days 2,098 + 685.
--
-- Del Monte pack_size is FRAGILE: 187 of 685 products have one, parsed from the product name ("x12", "24 x 400g"),
-- not from a source column. No Del Monte file carries a pack size, and Del Monte has no unit_cost_per_case rows at
-- all, so none of the 187 gets a unit_cost here. Do not treat those pack sizes as measured if a cost ever arrives.
--
-- Numbered 0045 although 0046 is already applied: the runner records applied files by name in schema_migrations and
-- applies any file the ledger lacks in filename order, so a lower number behind a higher applied one is accepted.
--
-- Rollback: UPDATE Product_Dimension SET unit_cost = NULL, unit_cost_source = NULL, lead_time_days = NULL,
--           lead_time_source = NULL; then DROP COLUMN the three new columns.

ALTER TABLE Product_Dimension ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(14,4);
ALTER TABLE Product_Dimension ADD COLUMN IF NOT EXISTS unit_cost_source TEXT
    CHECK (unit_cost_source IS NULL OR unit_cost_source IN ('inventory_cost_per_case/pack_size'));
ALTER TABLE Product_Dimension ADD COLUMN IF NOT EXISTS lead_time_source TEXT
    CHECK (lead_time_source IS NULL OR lead_time_source IN ('pending_confirmation', 'confirmed'));

UPDATE Product_Dimension pd
SET unit_cost = ROUND(c.cost_per_case / pd.pack_size::numeric, 4),
    unit_cost_source = 'inventory_cost_per_case/pack_size'
FROM (
    SELECT p.product_key,
           (SELECT AVG(i.unit_cost_per_case)
              FROM inventory_fact_real i
             WHERE i.product_key = p.product_key AND i.unit_cost_per_case > 0
             GROUP BY i._period ORDER BY i._period DESC LIMIT 1) AS cost_per_case
    FROM Product_Dimension p
) c
WHERE c.product_key = pd.product_key
  AND c.cost_per_case IS NOT NULL
  AND pd.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd.pack_size::numeric > 0
  AND pd.unit_cost IS NULL;

UPDATE Product_Dimension
SET lead_time_days = 3, lead_time_source = 'pending_confirmation'
WHERE principal IN ('unilever', 'delmonte') AND lead_time_days IS NULL;

COMMENT ON COLUMN Product_Dimension.unit_cost IS
    'Cost per piece in pesos (what SSM pays): latest-month avg unit_cost_per_case / pack_size. NULL without both. Migration 0045.';
COMMENT ON COLUMN Product_Dimension.unit_price IS
    'Selling price per piece. Not populated: no source yet. Migration 0045 deliberately leaves it NULL.';
COMMENT ON COLUMN Product_Dimension.lead_time_days IS
    'Days from order to receipt. 3 = SSM meeting 2026-09-28 (2-3 days), pending confirmation. Migration 0045.';
