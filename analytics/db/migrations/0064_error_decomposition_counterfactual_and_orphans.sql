-- 0064_error_decomposition_counterfactual_and_orphans.sql — two corrections to 0063.
--
-- 1. COUNTERFACTUAL RUNS. forecast_run 12 and 13 (the Tier B and Tier C as-served backtests) were stored so the
--    decomposition could score every tier. They are NOT served accuracy: the live runner forecasts Tier A only,
--    so no Tier B or C forecast was ever deployed. Their label, cohort and notes now say so at the run level, where
--    accuracy_mart (run_label, cohort), mart.forecast_run and GET /dashboard/forecast-runs all carry it:
--      label   'COUNTERFACTUAL (never served: the live runner forecasts Tier A only) - as-served backtest ...'
--      cohort  'COUNTERFACTUAL, NOT SERVED - ...'
--      notes   {"counterfactual": true, "reason": ...}   (machine-readable)
--    Run 11 (Tier A) is the served one and is untouched. The decomposition still reads these runs (the label
--    pattern below accepts the prefix) and its Tier B and C rows are counterfactual by the same token.
--
-- 2. ORPHAN SAFETY STOCK. 0063 preferred lp_recommendation.ss_i whenever a row existed for the product and month.
--    146 such rows were bulk-written 2026-08-24 with lp_run_key NULL: no LP run produced them (about 52 pieces
--    each against 3,370 rebuilt). A stored figure now counts only when its row belongs to an actual LP run
--    (lp_recommendation.lp_run_key joined to lp_run); otherwise safety stock is rebuilt and ss_method says 'rebuilt'.
--
-- Same function signature as 0063 (CREATE OR REPLACE); the body differs in the two places above only.
-- Rollback: re-run the CREATE FUNCTION of 0063; restore the three columns of runs 12 and 13 from
-- backups/tables_20261021T175535Z; DELETE FROM schema_migrations WHERE filename =
-- '0064_error_decomposition_counterfactual_and_orphans.sql'.

UPDATE mart.forecast_run
SET label = 'COUNTERFACTUAL (never served: the live runner forecasts Tier A only) - ' || label,
    cohort = 'COUNTERFACTUAL, NOT SERVED - ' || COALESCE(cohort, ''),
    notes = COALESCE(notes, '{}'::jsonb) || jsonb_build_object(
        'counterfactual', true,
        'reason', 'Tier B/C forecasts are not produced by the live runner (Tier A only); this backtest exists to score the error decomposition by tier and is not deployed accuracy')
WHERE kind = 'backtest_recreated'
  AND label ~ '^as-served backtest .*, Tier [BC] the month before each month, calendar-adjusted$';

-- p_service_z / p_protect_days: analytics.params SERVICE_Z and PLACEHOLDERS review_days + lead_days.
-- p_tier_a_basis: analytics.params.abc_method('unilever'). analytics/marts.py passes all three; the
-- defaults are the same values.
CREATE OR REPLACE FUNCTION mart.refresh_error_decomposition(
    p_trigger text DEFAULT 'manual',
    p_service_z numeric DEFAULT 1.28,
    p_protect_days integer DEFAULT 8,
    p_tier_a_basis text DEFAULT 't12m_new'
) RETURNS jsonb LANGUAGE plpgsql SET search_path = mart, public AS $$
DECLARE
    v_rows integer;
    v_agg integer;
BEGIN
    -- The full refresh's lock: never interleaves with one (re-entrant inside it).
    PERFORM pg_advisory_xact_lock(hashtext('mart.refresh'));

    DELETE FROM mart.error_decomposition;
    DELETE FROM mart.error_decomposition_row;

    INSERT INTO mart.error_decomposition_row (
        principal, tier, product_key, month, forecast_run_id, forecast_source, forecast_pieces, actual_pieces,
        price_per_piece, safety_stock_pieces, safety_stock_stored_pieces, safety_stock_rebuilt_pieces, ss_method,
        over_pieces, under_pieces, absorbed_pieces, beyond_pieces, exceeds_safety_stock,
        over_pesos, under_pesos, absorbed_pesos, beyond_pesos)
    WITH real_sales AS (
        SELECT product_key, period, pieces, pieces_null_rows, pesos
        FROM mart.sales_mart
        WHERE principal = 'unilever' AND level = 'product' AND source_tag = 'real'
    ),
    bounds AS (
        SELECT MIN(period) AS first_period, MAX(period) AS last_period FROM real_sales
    ),
    firsts AS (
        SELECT product_key, MIN(period) AS first_period FROM real_sales GROUP BY product_key
    ),
    -- weekdays per calendar month (pandas bdate_range: Monday to Friday, no holidays)
    bdays AS (
        SELECT to_char(m, 'YYYY-MM') AS period,
               (SELECT COUNT(*) FROM generate_series(m::date, (m + interval '1 month - 1 day')::date, interval '1 day') d
                WHERE extract(isodow FROM d) < 6)::numeric AS bd
        FROM bounds b,
             generate_series(to_date(b.first_period, 'YYYY-MM'), to_date(b.last_period, 'YYYY-MM'), interval '1 month') m
    ),
    -- run_baseline_forecast.build_series: from the product's first row to the latest month; no row =
    -- 0; blank = unknown (NULL); a net-negative month = 0.
    grid AS (
        SELECT f.product_key, to_char(g, 'YYYY-MM') AS period,
               CASE WHEN r.product_key IS NULL THEN 0::numeric
                    WHEN r.pieces_null_rows > 0 THEN NULL
                    ELSE GREATEST(r.pieces, 0) END AS q
        FROM firsts f
        CROSS JOIN bounds b
        CROSS JOIN LATERAL generate_series(to_date(f.first_period, 'YYYY-MM'), to_date(b.last_period, 'YYYY-MM'), interval '1 month') g
        LEFT JOIN real_sales r ON r.product_key = f.product_key AND r.period = to_char(g, 'YYYY-MM')
    ),
    -- history strictly BEFORE each month: count, sum, sum of squares, mean business days (observed months)
    hist AS (
        SELECT g.product_key, g.period, g.q,
               COUNT(g.q) OVER w AS n,
               SUM(g.q) OVER w AS s1,
               SUM(g.q * g.q) OVER w AS s2,
               AVG(CASE WHEN g.q IS NOT NULL THEN b.bd END) OVER w AS bd_avg
        FROM grid g JOIN bdays b ON b.period = g.period
        WINDOW w AS (PARTITION BY g.product_key ORDER BY g.period ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
    ),
    rebuilt AS (
        SELECT product_key, period, q,
               CASE WHEN n >= 2 THEN
                   p_service_z * sqrt(GREATEST((s2 - s1 * s1 / n) / (n - 1), 0)) / sqrt(bd_avg) * sqrt(p_protect_days::numeric)
               END AS ss
        FROM hist
    ),
    fc_backtest AS (
        SELECT fv.product_key, fv.month, fv.forecast_pieces, r.run_id, 'backtest_as_served'::text AS src, 1 AS pri
        FROM mart.forecast_run r JOIN mart.forecast_run_value fv ON fv.run_id = r.run_id
        WHERE r.kind = 'backtest_recreated' AND r.label ~ '^(COUNTERFACTUAL \(never served[^)]*\) - )?as-served backtest .*calendar-adjusted$'
    ),
    fc_live AS (
        SELECT DISTINCT ON (fv.product_key, fv.month)
               fv.product_key, fv.month, fv.forecast_pieces, r.run_id, 'stored_run'::text AS src, 2 AS pri
        FROM mart.forecast_run r JOIN mart.forecast_run_value fv ON fv.run_id = r.run_id
        WHERE r.kind = 'stored_run'
        ORDER BY fv.product_key, fv.month, r.run_id DESC
    ),
    fc AS (
        SELECT DISTINCT ON (product_key, month) *
        FROM (SELECT * FROM fc_backtest UNION ALL SELECT * FROM fc_live) u
        ORDER BY product_key, month, pri, run_id DESC
    ),
    scored AS (
        SELECT fc.product_key, fc.month, fc.forecast_pieces, fc.run_id, fc.src, ac.tier,
               rb.q AS actual, rb.ss AS ss_rebuilt, lp.ss_i AS ss_stored
        FROM fc
        JOIN rebuilt rb ON rb.product_key = fc.product_key AND rb.period = fc.month AND rb.q IS NOT NULL
        JOIN abc_classification ac ON ac.principal = 'unilever' AND ac.method = p_tier_a_basis
             AND ac.product_key = fc.product_key AND ac.classification_period = mart.month_add(fc.month, -1)
        LEFT JOIN (SELECT l.product_key, l.planning_cycle_date, l.ss_i
                   FROM lp_recommendation l JOIN lp_run lr ON lr.run_key = l.lp_run_key) lp
               ON lp.product_key = fc.product_key AND to_char(lp.planning_cycle_date, 'YYYY-MM') = fc.month
    ),
    px AS (
        SELECT s.product_key, s.tier,
               CASE WHEN COALESCE(SUM(r.pieces), 0) > 0 AND COALESCE(SUM(r.pesos), 0) > 0
                    THEN SUM(r.pesos) / SUM(r.pieces) END AS price
        FROM scored s
        JOIN real_sales r ON r.product_key = s.product_key AND r.period = s.month
        GROUP BY s.product_key, s.tier
    ),
    calc AS (
        SELECT s.*, px.price,
               COALESCE(s.ss_stored, s.ss_rebuilt) AS ss,
               GREATEST(s.forecast_pieces - s.actual, 0) AS over_p,
               GREATEST(s.actual - s.forecast_pieces, 0) AS under_p
        FROM scored s LEFT JOIN px ON px.product_key = s.product_key AND px.tier = s.tier
    )
    SELECT 'unilever', tier, product_key, month, run_id, src, forecast_pieces, actual, price,
           ss, ss_stored, ss_rebuilt,
           CASE WHEN ss_stored IS NOT NULL THEN 'stored_lp' WHEN ss_rebuilt IS NOT NULL THEN 'rebuilt' ELSE 'none' END,
           over_p, under_p,
           CASE WHEN ss IS NOT NULL THEN LEAST(under_p, ss) END,
           CASE WHEN ss IS NOT NULL THEN GREATEST(under_p - ss, 0) END,
           CASE WHEN ss IS NOT NULL THEN under_p > ss END,
           over_p * price, under_p * price,
           CASE WHEN ss IS NOT NULL THEN LEAST(under_p, ss) * price END,
           CASE WHEN ss IS NOT NULL THEN GREATEST(under_p - ss, 0) * price END
    FROM calc;
    GET DIAGNOSTICS v_rows = ROW_COUNT;

    INSERT INTO mart.error_decomposition
    SELECT principal, tier, period, product_months, product_months_with_ss, ss_stored_rows, ss_rebuilt_rows,
           CASE WHEN ss_stored_rows > 0 AND ss_rebuilt_rows > 0 THEN 'mixed'
                WHEN ss_stored_rows > 0 THEN 'stored_lp'
                WHEN ss_rebuilt_rows > 0 THEN 'rebuilt' ELSE 'none' END,
           exceed_product_months,
           exceed_product_months::numeric / NULLIF(product_months_with_ss, 0),
           actual_pieces, over_pieces + absorbed_pieces + beyond_pieces + under_no_ss_pieces,
           over_pieces, absorbed_pieces, beyond_pieces, under_no_ss_pieces,
           over_pieces / NULLIF(over_pieces + absorbed_pieces + beyond_pieces + under_no_ss_pieces, 0),
           absorbed_pieces / NULLIF(over_pieces + absorbed_pieces + beyond_pieces + under_no_ss_pieces, 0),
           beyond_pieces / NULLIF(over_pieces + absorbed_pieces + beyond_pieces + under_no_ss_pieces, 0),
           over_pieces / NULLIF(actual_pieces, 0), absorbed_pieces / NULLIF(actual_pieces, 0), beyond_pieces / NULLIF(actual_pieces, 0),
           priced_product_months, actual_pesos, over_pesos + absorbed_pesos + beyond_pesos + under_no_ss_pesos,
           over_pesos, absorbed_pesos, beyond_pesos, under_no_ss_pesos,
           over_pesos / NULLIF(over_pesos + absorbed_pesos + beyond_pesos + under_no_ss_pesos, 0),
           absorbed_pesos / NULLIF(over_pesos + absorbed_pesos + beyond_pesos + under_no_ss_pesos, 0),
           beyond_pesos / NULLIF(over_pesos + absorbed_pesos + beyond_pesos + under_no_ss_pesos, 0),
           over_pesos / NULLIF(actual_pesos, 0), absorbed_pesos / NULLIF(actual_pesos, 0), beyond_pesos / NULLIF(actual_pesos, 0),
           now()
    FROM (
        SELECT principal, COALESCE(tier, 'all') AS tier, month AS period,
               COUNT(*)::int AS product_months,
               COUNT(safety_stock_pieces)::int AS product_months_with_ss,
               COUNT(*) FILTER (WHERE ss_method = 'stored_lp')::int AS ss_stored_rows,
               COUNT(*) FILTER (WHERE ss_method = 'rebuilt')::int AS ss_rebuilt_rows,
               COUNT(*) FILTER (WHERE exceeds_safety_stock)::int AS exceed_product_months,
               SUM(actual_pieces) AS actual_pieces,
               SUM(over_pieces) AS over_pieces,
               COALESCE(SUM(absorbed_pieces), 0) AS absorbed_pieces,
               COALESCE(SUM(beyond_pieces), 0) AS beyond_pieces,
               COALESCE(SUM(under_pieces) FILTER (WHERE safety_stock_pieces IS NULL), 0) AS under_no_ss_pieces,
               COUNT(price_per_piece)::int AS priced_product_months,
               COALESCE(SUM(actual_pieces * price_per_piece), 0) AS actual_pesos,
               COALESCE(SUM(over_pesos), 0) AS over_pesos,
               COALESCE(SUM(absorbed_pesos), 0) AS absorbed_pesos,
               COALESCE(SUM(beyond_pesos), 0) AS beyond_pesos,
               COALESCE(SUM(under_pesos) FILTER (WHERE safety_stock_pieces IS NULL), 0) AS under_no_ss_pesos
        FROM mart.error_decomposition_row
        GROUP BY GROUPING SETS ((principal, tier, month), (principal, month))
    ) a;
    GET DIAGNOSTICS v_agg = ROW_COUNT;

    RETURN jsonb_build_object('error_decomposition_row', v_rows, 'error_decomposition', v_agg);
END;
$$;
