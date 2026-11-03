-- 0074: public.product_demand_view and public.bo_monitoring_view read real rows only.
--
-- Both views read base fact tables with no is_demo filter, so they served the labelled rows of arrangement 2
-- (CLAUDE.md rule 2) to any caller: product_demand_view (DEC-13, schema.sql section 7) 12,243 + 4,639 rows from
-- unilever_sku_demand_fact and sellout_fact; bo_monitoring_view (schema.sql section 6) sums over purchase_fact and
-- salesreturn_fact. Nothing in the repository, no view and no function reads either (checked 2026-11-04), so this
-- changes no figure. Filtered rather than dropped: same columns and grants, DEC-13 stands, and an outside query that
-- nobody can see from here keeps working but gets real rows.
--
-- Unqualified names: a scratch build refuses a migration that names public. explicitly.
--
-- Rollback: re-create both views from analytics/db/schema.sql as of commit b209a9e, then
--           DELETE FROM schema_migrations WHERE filename = '0074_views_real_rows_only.sql'.

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

CREATE OR REPLACE VIEW bo_monitoring_view AS
WITH purchases AS (
    SELECT principal, region, _period, SUM(net_amount) AS purchase_net_amount
    FROM purchase_fact
    WHERE is_demo = false
    GROUP BY principal, region, _period
),
bo_returns AS (
    SELECT principal, region, _period, SUM(net_amount) AS bo_net_amount
    FROM salesreturn_fact
    WHERE return_type = 'BO' AND is_demo = false
    GROUP BY principal, region, _period
)
SELECT
    p.principal,
    p.region,
    p._period,
    r.bo_net_amount,
    p.purchase_net_amount,
    CASE
        WHEN p.purchase_net_amount > 0
            THEN ROUND(r.bo_net_amount / p.purchase_net_amount * 100, 2)
        ELSE NULL
    END AS bo_rate
FROM purchases p
LEFT JOIN bo_returns r
    ON r.principal = p.principal
   AND r.region = p.region
   AND r._period = p._period;
