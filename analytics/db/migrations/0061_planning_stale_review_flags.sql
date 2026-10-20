-- 0061_planning_stale_review_flags.sql - mart.refresh_status.planning_stale also knows the review flags.
--
-- compute_review_flags stores forecast_generated_at on every review_flag row, but nothing compared it
-- with the live forecast: a forecast rerun left flags computed against the old forecast looking current.
-- planning_stale is now also true when, for the latest forecast cycle, a Unilever forecast row has no
-- review_flag row or a flag row whose forecast_generated_at differs from forecast_result.generated_at.
-- View only: no table, row or function is touched. Freeze package 1d, 2026-10-20.
--
-- Expected on apply: 0 rows written. planning_stale is true until compute_review_flags --calendar-factor
-- --write is run against the forecast then in forecast_result.
--
-- Rollback: re-run the CREATE OR REPLACE VIEW block of 0047 (same column list, so it can replace this one).
--           DELETE FROM schema_migrations WHERE filename = '0061_planning_stale_review_flags.sql';

CREATE OR REPLACE VIEW block);
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
            OR flags.out_of_date
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
    ) plan
    -- 0061: review flags are stale while any flag row was computed against a forecast other than
    -- the live one (its forecast_generated_at differs from forecast_result.generated_at), or a
    -- live forecast row has no flag row for its cycle. A forecast rerun therefore marks the
    -- planning mart stale until scripts/compute_review_flags.py is run again.
    CROSS JOIN LATERAL (
        SELECT EXISTS (
                   SELECT 1 FROM forecast_result fr
                   JOIN product_dimension pd ON pd.product_key = fr.product_key AND pd.principal = 'unilever'
                   LEFT JOIN review_flag rf ON rf.product_key = fr.product_key AND rf.planning_cycle_date = fr.forecast_date
                   WHERE fr.forecast_date = (SELECT MAX(forecast_date) FROM forecast_result)
                     AND (rf.product_key IS NULL OR rf.forecast_generated_at IS DISTINCT FROM fr.generated_at)
               ) AS out_of_date
    ) flags;
