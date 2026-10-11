-- 0047_planning_stale_tier_basis.sql — mart.refresh_status.planning_tier_a_basis.
--
-- The Tier A basis (analytics.params.TIER_A_BASIS) the last planning refresh was built with, read from
-- mart.refresh_log params ->> 'tier_a_basis'. planning_stale is also true when no basis was recorded.
-- backend/planning_mart.py compares the recorded basis with the current constant, so a plan built on an
-- older basis is never served. View only: no table, row or function is touched.
--
-- Expected (live, 2026-10-08): 0 rows written; planning_mart 277 rows; latest planning log row records
-- 't12m_new'; planning_stale stays false.
--
-- Rollback: DROP VIEW mart.refresh_status; re-create it from 0046 (the CREATE OR REPLACE VIEW block);
--           a column cannot be removed with CREATE OR REPLACE.
--           DELETE FROM schema_migrations WHERE filename = '0047_planning_stale_tier_basis.sql';

CREATE OR REPLACE VIEW mart.refresh_status AS
    SELECT r.refreshed_at, r.trigger,
           src.latest_load, src.latest_fill, src.latest_forecast, src.latest_lp_run,
           (r.refreshed_at IS NULL
            OR GREATEST(src.latest_load, src.latest_fill, src.latest_forecast, src.latest_lp_run) > r.refreshed_at) AS stale,
           p.refreshed_at AS planning_refreshed_at,
           (p.refreshed_at IS NULL
            OR p.tier_a_basis IS NULL
            OR GREATEST(src.latest_load, src.latest_fill, src.latest_forecast, src.latest_lp_run,
                        plan.latest_review_flag, plan.latest_abc, plan.latest_product_edit) > p.refreshed_at) AS planning_stale,
           p.tier_a_basis AS planning_tier_a_basis
    FROM (SELECT 1) one
    LEFT JOIN LATERAL (SELECT refreshed_at, trigger FROM mart.refresh_log
                       WHERE row_counts -> 'sales_mart' IS NOT NULL ORDER BY refresh_id DESC LIMIT 1) r ON true
    LEFT JOIN LATERAL (SELECT refreshed_at, params ->> 'tier_a_basis' AS tier_a_basis FROM mart.refresh_log
                       WHERE row_counts -> 'planning_mart' IS NOT NULL ORDER BY refresh_id DESC LIMIT 1) p ON true
    CROSS JOIN LATERAL (
        SELECT (SELECT MAX(finished_at) FROM etl_load_event
                WHERE NOT dry_run
                  AND COALESCE(real_rows_added, 0) + COALESCE(real_rows_removed, 0)
                      + COALESCE(fill_rows_added, 0) + COALESCE(fill_rows_removed, 0) > 0) AS latest_load,
               GREATEST((SELECT MAX(computed_at) FROM derived_receipt_fact), (SELECT MAX(computed_at) FROM sku_demand_fill)) AS latest_fill,
               (SELECT MAX(generated_at) FROM forecast_result) AS latest_forecast,
               (SELECT MAX(created_at) FROM lp_run) AS latest_lp_run
    ) src
    CROSS JOIN LATERAL (
        SELECT (SELECT MAX(computed_at) FROM review_flag) AS latest_review_flag,
               (SELECT MAX(computed_at) FROM abc_classification) AS latest_abc,
               (SELECT MAX(created_at) FROM audit_log WHERE action = 'Edit SKU') AS latest_product_edit
    ) plan;
