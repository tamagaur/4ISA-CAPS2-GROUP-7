-- 0077_decomposition_ss_follows_level.sql - the error decomposition's rebuilt safety stock follows the level, as the plan's does.
--
-- WHY. Since 2026-11-10 the plan sizes safety stock on sigma_d x level_factor for products whose forecast was treated
-- (succession, fading), and since 2026-11-11 also for products whose forecast is zero (analytics.params.SAFETY_STOCK_FOLLOWS_LEVEL
-- = 'treated'; scripts/run_lp.TREATMENT_QUERY, level_factor). The error decomposition (0063, 0064) rebuilds safety stock for
-- every product-month with no stored plan row, which on live is EVERY scored product-month (21,250 of 21,250 rows 'rebuilt',
-- read 2026-11-11: the backtest window ends 2026-02, the first stored plan is 2026-03). It rebuilt it at full sigma, so a faded,
-- re-coded or zero-forecast product-month was credited with safety stock the plan would not hold, and its under-forecast read
-- as "absorbed" rather than "beyond safety stock". The plan and the decomposition described two different safety stocks.
--
-- WHAT CHANGES.
--   1. mart.forecast_run_value.treatment (new, nullable): 'succession' or 'fading' where analytics/forecasting/treatments.apply
--      matched for that product-month. Written by scripts/accuracy_as_served.py for new runs; backfilled for the existing
--      as-served runs by `python -m scripts.accuracy_as_served --backfill-treatment` (recomputes each flag from the history and
--      context the backtest used, and refuses unless re-applying the treatment to every stored value returns that value).
--   2. mart.error_decomposition_row.safety_stock_level_factor (new, nullable): the factor applied to that row's rebuilt safety
--      stock; NULL where none was applied.
--   3. mart.refresh_error_decomposition (same signature, so analytics/marts.DECOMPOSITION_SIGNATURE and every caller are
--      unchanged): the rebuilt safety stock is multiplied by min(1, forecast / mean monthly quantity of the history before the
--      month) when the forecast is zero or its treatment is succession/fading: run_lp.level_factor over the same months and
--      with the same rules as the rebuilt sigma (no row = 0, a blank month left out, never above 1, 1 when the history has no
--      positive mean). A stored-run row with no treatment of its own takes it from forecast_result.model_params of that
--      product and month. A stored plan figure (ss_method 'stored_lp') already carries the plan's scaling and is unchanged.
--      tests/test_decomposition_follows_level.py holds this rule to analytics.params.SAFETY_STOCK_FOLLOWS_LEVEL = 'treated':
--      a different setting needs a migration of its own.
--
-- Moves (rehearsed on a restore of backups/full_backup_20261111T103426Z, see scripts/apply_final_bundle.py): the error
-- decomposition's absorbed / beyond split and exceed counts; nothing in forecasting, safety stock, targets or the LP reads it.
-- Rollback: re-run the CREATE OR REPLACE FUNCTION of 0064; ALTER TABLE mart.error_decomposition_row DROP COLUMN
-- safety_stock_level_factor; ALTER TABLE mart.forecast_run_value DROP COLUMN treatment; DELETE FROM schema_migrations WHERE
-- filename = '0077_decomposition_ss_follows_level.sql'.

ALTER TABLE mart.forecast_run_value ADD COLUMN IF NOT EXISTS treatment text
    CHECK (treatment IS NULL OR treatment IN ('succession', 'fading'));
COMMENT ON COLUMN mart.forecast_run_value.treatment IS
    'succession / fading where analytics/forecasting/treatments.apply matched for this product-month (0077); NULL = none, or a run written before the flag existed and not backfilled';

ALTER TABLE mart.error_decomposition_row ADD COLUMN IF NOT EXISTS safety_stock_level_factor numeric;
COMMENT ON COLUMN mart.error_decomposition_row.safety_stock_level_factor IS
    'min(1, forecast / mean monthly quantity before the month) applied to the rebuilt safety stock of a zero-forecast or succession/fading product-month (0077, as scripts/run_lp.level_factor); NULL = not applied';

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
        over_pesos, under_pesos, absorbed_pesos, beyond_pesos, safety_stock_level_factor)
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
               END AS ss,
               -- run_lp.level_factor's mean: positive quantity over the observed months of the same history (NULL = no level)
               CASE WHEN n >= 1 AND s1 > 0 THEN s1 / n END AS level_mean
        FROM hist
    ),
    fc_backtest AS (
        SELECT fv.product_key, fv.month, fv.forecast_pieces, r.run_id, 'backtest_as_served'::text AS src, 1 AS pri,
               fv.treatment
        FROM mart.forecast_run r JOIN mart.forecast_run_value fv ON fv.run_id = r.run_id
        WHERE r.kind = 'backtest_recreated' AND r.label ~ '^(COUNTERFACTUAL \(never served[^)]*\) - )?as-served backtest .*calendar-adjusted$'
    ),
    fc_live AS (
        SELECT DISTINCT ON (fv.product_key, fv.month)
               fv.product_key, fv.month, fv.forecast_pieces, r.run_id, 'stored_run'::text AS src, 2 AS pri,
               COALESCE(fv.treatment, fr.model_params ->> 'treatment') AS treatment
        FROM mart.forecast_run r JOIN mart.forecast_run_value fv ON fv.run_id = r.run_id
        LEFT JOIN forecast_result fr ON fr.product_key = fv.product_key AND to_char(fr.forecast_date, 'YYYY-MM') = fv.month
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
               rb.q AS actual, lv.factor AS level_factor,
               rb.ss * COALESCE(lv.factor, 1) AS ss_rebuilt, lp.ss_i AS ss_stored
        FROM fc
        JOIN rebuilt rb ON rb.product_key = fc.product_key AND rb.period = fc.month AND rb.q IS NOT NULL
        JOIN abc_classification ac ON ac.principal = 'unilever' AND ac.method = p_tier_a_basis
             AND ac.product_key = fc.product_key AND ac.classification_period = mart.month_add(fc.month, -1)
        -- SAFETY_STOCK_FOLLOWS_LEVEL = 'treated': a zero forecast, or a succession / fading treatment
        CROSS JOIN LATERAL (
            SELECT CASE WHEN rb.ss IS NOT NULL AND (fc.forecast_pieces = 0 OR fc.treatment IN ('succession', 'fading'))
                        THEN CASE WHEN rb.level_mean IS NULL THEN 1::numeric
                                  ELSE LEAST(1::numeric, GREATEST(0::numeric, fc.forecast_pieces / rb.level_mean)) END
                   END AS factor
        ) lv
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
           CASE WHEN ss IS NOT NULL THEN GREATEST(under_p - ss, 0) * price END,
           CASE WHEN ss_stored IS NULL THEN level_factor END
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

    RETURN jsonb_build_object('error_decomposition_row', v_rows, 'error_decomposition', v_agg,
                              'level_factor_rows', (SELECT COUNT(*) FROM mart.error_decomposition_row
                                                    WHERE safety_stock_level_factor IS NOT NULL));
END;
$$;
