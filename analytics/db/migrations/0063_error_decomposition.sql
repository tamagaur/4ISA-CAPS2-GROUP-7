-- 0063_error_decomposition.sql — mart.error_decomposition_row / mart.error_decomposition: the forecast
-- miss split into over-buying, under-forecast that safety stock absorbed, and under-forecast BEYOND
-- safety stock (stockout exposure), per product-month and per month x ABC tier. Kept in step with the
-- other marts by mart.refresh_error_decomposition(), which analytics/marts.py calls inside every full
-- refresh (the same hook as the planning mart), so it moves when new actuals land.
--
-- WHAT IT IS. A VIEW OF EXISTING DATA. It reads forecasts already stored in mart.forecast_run_value,
-- actuals already in mart.sales_mart (real rows), the ABC tier already in abc_classification and the
-- safety stock already in lp_recommendation. It writes only its two tables. Nothing here is read back
-- by forecasting, safety stock, targets, the LP or any order quantity.
--
-- SCORING RULE: THE AS-SERVED ONE (scripts/accuracy_as_served.py, docs/ACCURACY_AS_SERVED.md).
--   forecast  the value the live forecast would serve, as stored by that script: runs of kind
--             backtest_recreated whose label is 'as-served backtest ... calendar-adjusted' (dead-SKU
--             rule applied, company calendar factor applied). One run per ABC tier (A: run 11; B and C
--             are stored by the same script, --write-tier-runs). For a month no such run covers, the
--             latest kind = 'stored_run' forecast for that month (what the live runner kept).
--   actual    the month's pieces floored at 0 (a net-negative month, returns above sales, is 0); a
--             month with no sales row is a real zero-sale month (Unilever); a blank-quantity month
--             (pieces_null_rows > 0) is unknown and is NOT scored; a month after the latest real
--             sales month is not known yet and is not scored.
--   tier      the product's tier on abc_classification in the month BEFORE the target month, on
--             p_tier_a_basis (analytics.params.abc_method('unilever')).
--   price     SUM(pesos) / SUM(pieces) over the product's scored months (per product and tier), NULL
--             when either sum is not positive; the headline() rule of scripts/backtest_forecast_run.py.
--             Pesos columns cover priced product-months only.
--
-- SAFETY STOCK, AND WHICH METHOD EACH ROW USED (ss_method).
--   stored_lp  lp_recommendation.ss_i for that product and planning cycle = the target month, where
--              the row exists.
--   rebuilt    where it does not: rebuilt from history the way scripts/run_lp.py builds it, point in
--              time: SS = z x sigma_monthly / sqrt(mean business days per month) x sqrt(protected
--              days), sigma_monthly the sample standard deviation of the product's monthly demand
--              (floored actuals, blanks left out, zero-sale months in) over the months BEFORE the
--              target month, at least 2 of them. z and the protected days (review + lead) are
--              analytics.params SERVICE_Z and PLACEHOLDERS, passed in by analytics/marts.py.
--   none       fewer than 2 observed months: no safety stock, nothing is called absorbed or beyond.
-- Both figures are kept (safety_stock_stored_pieces, safety_stock_rebuilt_pieces) beside the one used.
-- The aggregate table says per month and tier how many rows used each method, and ss_method = stored_lp,
-- rebuilt or mixed, so a rebuilt figure is never mistaken for a stored one.
--
-- Per product-month: over = max(forecast - actual, 0); under = max(actual - forecast, 0);
-- absorbed = min(under, safety stock); beyond = max(under - safety stock, 0) (stockout exposure,
-- potential, not an observed stockout); exceeds_safety_stock = under > safety stock.
-- Shares: of total error (over + under) and of total actual, in pieces and in pesos.
--
-- Unilever only: Del Monte has no product-level forecasts (CLAUDE.md, "Why data is missing"), so it has
-- no rows here, on purpose.
--
-- Rollback: DROP FUNCTION mart.refresh_error_decomposition(text, numeric, integer, text);
-- DROP TABLE mart.error_decomposition; DROP TABLE mart.error_decomposition_row;
-- DELETE FROM schema_migrations WHERE filename = '0063_error_decomposition.sql';

CREATE TABLE mart.error_decomposition_row (
    principal                    text    NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    tier                         text    NOT NULL CHECK (tier IN ('A', 'B', 'C')),
    product_key                  bigint  NOT NULL,
    month                        text    NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    forecast_run_id              bigint  NOT NULL,
    forecast_source              text    NOT NULL CHECK (forecast_source IN ('backtest_as_served', 'stored_run')),
    forecast_pieces              numeric NOT NULL,
    actual_pieces                numeric NOT NULL,
    price_per_piece              numeric,
    safety_stock_pieces          numeric,
    safety_stock_stored_pieces   numeric,
    safety_stock_rebuilt_pieces  numeric,
    ss_method                    text    NOT NULL CHECK (ss_method IN ('stored_lp', 'rebuilt', 'none')),
    over_pieces                  numeric NOT NULL,
    under_pieces                 numeric NOT NULL,
    absorbed_pieces              numeric,
    beyond_pieces                numeric,
    exceeds_safety_stock         boolean,
    over_pesos                   numeric,
    under_pesos                  numeric,
    absorbed_pesos               numeric,
    beyond_pesos                 numeric,
    PRIMARY KEY (principal, product_key, month)
);
CREATE INDEX error_decomposition_row_month ON mart.error_decomposition_row (principal, tier, month);

CREATE TABLE mart.error_decomposition (
    principal                       text    NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    tier                            text    NOT NULL CHECK (tier IN ('A', 'B', 'C', 'all')),
    period                          text    NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    product_months                  integer NOT NULL,
    product_months_with_ss          integer NOT NULL,
    ss_stored_rows                  integer NOT NULL,
    ss_rebuilt_rows                 integer NOT NULL,
    ss_method                       text    NOT NULL CHECK (ss_method IN ('stored_lp', 'rebuilt', 'mixed', 'none')),
    exceed_product_months           integer NOT NULL,
    exceed_share_of_product_months  numeric,
    actual_pieces                   numeric NOT NULL,
    error_pieces                    numeric NOT NULL,
    over_pieces                     numeric NOT NULL,
    absorbed_pieces                 numeric NOT NULL,
    beyond_pieces                   numeric NOT NULL,
    under_no_ss_pieces              numeric NOT NULL,
    over_share_of_error_pieces      numeric,
    absorbed_share_of_error_pieces  numeric,
    beyond_share_of_error_pieces    numeric,
    over_share_of_actual_pieces     numeric,
    absorbed_share_of_actual_pieces numeric,
    beyond_share_of_actual_pieces   numeric,
    priced_product_months           integer NOT NULL,
    actual_pesos                    numeric NOT NULL,
    error_pesos                     numeric NOT NULL,
    over_pesos                      numeric NOT NULL,
    absorbed_pesos                  numeric NOT NULL,
    beyond_pesos                    numeric NOT NULL,
    under_no_ss_pesos               numeric NOT NULL,
    over_share_of_error_pesos       numeric,
    absorbed_share_of_error_pesos   numeric,
    beyond_share_of_error_pesos     numeric,
    over_share_of_actual_pesos      numeric,
    absorbed_share_of_actual_pesos  numeric,
    beyond_share_of_actual_pesos    numeric,
    refreshed_at                    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (principal, tier, period)
);

ALTER TABLE mart.error_decomposition_row ENABLE ROW LEVEL SECURITY;
ALTER TABLE mart.error_decomposition ENABLE ROW LEVEL SECURITY;

-- p_service_z / p_protect_days: analytics.params SERVICE_Z and PLACEHOLDERS review_days + lead_days.
-- p_tier_a_basis: analytics.params.abc_method('unilever'). analytics/marts.py passes all three; the
-- defaults are the same values.
CREATE FUNCTION mart.refresh_error_decomposition(
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
        WHERE r.kind = 'backtest_recreated' AND r.label ~ '^as-served backtest .*calendar-adjusted$'
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
        LEFT JOIN lp_recommendation lp ON lp.product_key = fc.product_key
             AND to_char(lp.planning_cycle_date, 'YYYY-MM') = fc.month
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
