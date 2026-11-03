-- 0074: public.product_demand_view reads real rows only.
--
-- The view (DEC-13, schema.sql section 7) joined unilever_sku_demand_fact and sellout_fact with no
-- is_demo filter, so it served the 12,243 + 4,639 labelled rows of arrangement 2 (CLAUDE.md rule 2) to any
-- caller. Nothing in the repository, no view and no function reads it (checked 2026-11-04), so this changes
-- no figure. Filtered rather than dropped: same columns and grants, DEC-13 stands, and an outside query
-- that nobody can see from here keeps working but gets real rows.
--
-- Unqualified names: a scratch build refuses a migration that names public. explicitly.

CREATE OR REPLACE VIEW product_demand_view AS
SELECT
    pd.product_key, pd.principal, pd.grain, pd.sku_code,
    pd.category_path, pd.product_name,
    u.calendar_month AS period,
    u.quantity_sold   AS quantity,
    'pieces'            AS quantity_unit,
    NULL::numeric          AS net_amount,
    u.region, u._src_file, u._src_sheet
FROM unilever_sku_demand_fact u
JOIN product_dimension pd ON pd.product_key = u.product_key
WHERE u.is_demo = false

UNION ALL

SELECT
    pd.product_key,
    COALESCE(pd.principal, s.principal)         AS principal,
    pd.grain, pd.sku_code,
    COALESCE(pd.category_path, s.category_path) AS category_path,
    pd.product_name,
    s._period AS period,
    s.quantity AS quantity,
    'unconfirmed' AS quantity_unit,
    s.net_amount,
    s.region, s._src_file, s._src_sheet
FROM sellout_fact s
LEFT JOIN product_dimension pd ON pd.product_key = s.product_key
WHERE s.is_demo = false;
