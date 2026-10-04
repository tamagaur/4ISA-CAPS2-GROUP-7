-- 0043_mart_stock_limited_rule.sql — accuracy_mart's "possibly stock-limited" label replaced by
-- the rule of kelvin/surplus-bias-experiment 3226cc4, README Part 0.1 (Yuan, 2026-10-04).
--
-- 0041 defined it here for the first time (no rule on record): over-forecast AND 0 pieces at
-- the opening or closing count, a product missing from the possibly-partial 2025-05 count
-- counted as unknown. Replaced by Part 0.1, for every product-month whatever the forecast's
-- direction:
--   opening count = the count for M-1, closing count = the count for M, in pieces (cases x
--   pack size + loose); a product missing from a count that was taken = 0; a month with no
--   real count = unknown. Every real count as recorded: 2025-05 included, missing = 0, as in
--   Part 0's main results; such rows now carry count_possibly_partial = true instead.
--   average sales = mean monthly pieces over the 12 months before M, from the first sale, a
--   month without a row = 0, at least 3 months; 1 week = average x 12 / 52.
--   possibly stock-limited = the opening or closing count is 0, or below 1 week.
-- The three numbers are analytics.params STOCK_LIMITED_WEEKS / _AVG_MONTHS / _AVG_MIN_MONTHS,
-- passed in by analytics/marts.py (the defaults below are the same, pinned by tests/test_marts.py).
--
-- refresh() gains three parameters, so the 3-argument function is dropped and recreated with
-- the same body otherwise (0041's, unchanged outside the accuracy_mart step). accuracy_mart gains
-- avg_monthly_pieces, stock_limited_reason and count_possibly_partial, then is rebuilt.
--
-- Rollback: re-run 0041's CREATE FUNCTION mart.refresh (after DROP FUNCTION mart.refresh(text,
-- integer, text[], numeric, integer, integer)), drop the three columns, SELECT mart.refresh().

ALTER TABLE mart.accuracy_mart ADD COLUMN IF NOT EXISTS avg_monthly_pieces numeric;
ALTER TABLE mart.accuracy_mart ADD COLUMN IF NOT EXISTS stock_limited_reason text;
ALTER TABLE mart.accuracy_mart ADD COLUMN IF NOT EXISTS count_possibly_partial boolean;

DROP FUNCTION mart.refresh(text, integer, text[]);

CREATE FUNCTION mart.refresh(
    p_trigger text DEFAULT 'manual',
    p_idle_months integer DEFAULT 6,
    p_partial_counts text[] DEFAULT ARRAY['2025-05'],
    p_low_weeks numeric DEFAULT 1.0,
    p_avg_months integer DEFAULT 12,
    p_avg_min_months integer DEFAULT 3
) RETURNS jsonb LANGUAGE plpgsql SET search_path = mart, public AS $$
DECLARE
    t0 timestamptz := clock_timestamp();
    v_counts jsonb;
BEGIN
    -- One refresh at a time; a second caller waits rather than interleaving deletes.
    PERFORM pg_advisory_xact_lock(hashtext('mart.refresh'));

    -- sales_mart --------------------------------------------------------------
    DELETE FROM mart.sales_mart;

    INSERT INTO mart.sales_mart
    SELECT 'unilever', 'product', d.product_key, pd.category_path,
           d.period, mart.data_kind(d.is_demo, d.fill_source), mart.source_tag(d.is_demo, d.fill_source),
           true,
           (d.is_demo AND d.period < (SELECT MIN(calendar_month) FROM unilever_sku_demand_fact WHERE is_demo = false)),
           d.pieces, d.pieces_null_rows, true, d.pesos, 'vat_inclusive', d.gsv, d.source_rows
    FROM (
        SELECT product_key, calendar_month AS period, is_demo, fill_source,
               SUM(quantity_sold) AS pieces, (COUNT(*) - COUNT(quantity_sold))::int AS pieces_null_rows,
               SUM(net_amount) AS pesos, SUM(gsv) AS gsv, COUNT(*)::int AS source_rows
        FROM unilever_sku_demand_fact
        GROUP BY product_key, calendar_month, is_demo, fill_source
    ) d
    LEFT JOIN product_dimension pd ON pd.product_key = d.product_key;

    INSERT INTO mart.sales_mart
    SELECT 'delmonte', 'category', s.product_key, COALESCE(pd.category_path, s.category_path),
           s.period, mart.data_kind(s.is_demo, s.fill_source), mart.source_tag(s.is_demo, s.fill_source),
           true, false,
           s.pieces, s.pieces_null_rows, false, s.pesos,
           CASE WHEN s.tax_inclusive THEN 'vat_inclusive_recorded_with_tax' ELSE 'ex_vat' END, NULL, s.source_rows
    FROM (
        SELECT product_key, _period AS period, is_demo, fill_source, MIN(category_path) AS category_path,
               SUM(quantity) AS pieces, (COUNT(*) - COUNT(quantity))::int AS pieces_null_rows,
               SUM(net_amount) AS pesos, bool_or(COALESCE(net_amount_tax_inclusive, false)) AS tax_inclusive,
               COUNT(*)::int AS source_rows
        FROM sellout_fact
        GROUP BY product_key, _period, is_demo, fill_source
    ) s
    LEFT JOIN product_dimension pd ON pd.product_key = s.product_key;

    INSERT INTO mart.sales_mart
    SELECT f.principal, 'product', f.product_key, COALESCE(pd.category_path, f.category_path),
           f.period, mart.data_kind(f.is_demo, f.fill_source), mart.source_tag(f.is_demo, f.fill_source),
           false, false,
           f.pieces, f.pieces_null_rows, false, f.pesos,
           CASE WHEN f.period IN (SELECT _period FROM sellout_fact WHERE is_demo = false AND net_amount_tax_inclusive)
                THEN 'vat_inclusive_recorded_with_tax' ELSE 'ex_vat' END,
           NULL, f.source_rows
    FROM (
        SELECT principal, product_key, _period AS period, is_demo, fill_source, MIN(category_path) AS category_path,
               SUM(quantity) AS pieces, (COUNT(*) - COUNT(quantity))::int AS pieces_null_rows,
               SUM(net_amount) AS pesos, COUNT(*)::int AS source_rows
        FROM sku_demand_fill
        GROUP BY principal, product_key, _period, is_demo, fill_source
    ) f
    LEFT JOIN product_dimension pd ON pd.product_key = f.product_key;
    ANALYZE mart.sales_mart;

    -- flow_month --------------------------------------------------------------
    DELETE FROM mart.flow_month;

    -- Purchases on the sales line's tax basis: Del Monte's Net Amount includes VAT
    -- (tax_amount / net_amount = 12/112), its sell-out does not.
    INSERT INTO mart.flow_month
    SELECT principal, _period, 'purchases', mart.data_kind(is_demo, fill_source), mart.source_tag(is_demo, fill_source),
           SUM(CASE WHEN principal = 'delmonte' THEN net_amount - COALESCE(tax_amount, 0) ELSE net_amount END),
           SUM(units_received), NULL,
           CASE WHEN principal = 'delmonte' THEN 'ex_vat' ELSE 'vat_inclusive' END,
           COUNT(*)::int, 0, NULL
    FROM purchase_fact
    GROUP BY principal, _period, is_demo, fill_source;

    INSERT INTO mart.flow_month
    SELECT principal, _period, 'estimated_receipts', mart.data_kind(is_demo, fill_source), mart.source_tag(is_demo, fill_source),
           SUM(receipt_value), SUM(receipt_pieces), NULL, 'last_purchase_price',
           COUNT(*)::int, (COUNT(*) FILTER (WHERE flag = 'negative_balance'))::int, COUNT(DISTINCT product_key)::int
    FROM derived_receipt_fact
    GROUP BY principal, _period, is_demo, fill_source;

    INSERT INTO mart.flow_month
    SELECT principal, _period, 'returns', mart.data_kind(is_demo, fill_source), mart.source_tag(is_demo, fill_source),
           SUM(net_amount), SUM(quantity_pieces), SUM(quantity_cases), 'net_amount_as_recorded',
           COUNT(*)::int, 0, NULL
    FROM salesreturn_fact
    GROUP BY principal, _period, is_demo, fill_source;

    -- inventory_mart ----------------------------------------------------------
    DELETE FROM mart.inventory_mart;

    INSERT INTO mart.inventory_mart
    WITH base AS (
        SELECT i.principal, i.product_key, i._period AS period,
               mart.data_kind(i.is_demo, i.fill_source) AS data_kind,
               mart.source_tag(i.is_demo, i.fill_source) AS source_tag,
               MIN(i.snapshot_date) AS first_date, MAX(i.snapshot_date) AS last_date,
               MIN(i.demand_period) AS demand_period,
               SUM(i.quantity_on_hand) AS cases, SUM(i.quantity_pieces) AS loose_pieces,
               SUM(COALESCE(i.valuation, i.quantity_on_hand * i.unit_cost_per_case)) AS pesos,
               bool_or(i.stock_status = 'Active') AS any_active,
               bool_or(i.stock_status = 'Inactive') AS any_inactive,
               COUNT(*)::int AS source_rows
        FROM inventory_fact i
        GROUP BY i.principal, i.product_key, i._period, mart.data_kind(i.is_demo, i.fill_source),
                 mart.source_tag(i.is_demo, i.fill_source)
    ),
    -- The day a count was taken: Unilever's SSIS file states it (one snapshot_date per
    -- count); Del Monte's stored date is a 1st-of-month placeholder (DEC-12), never shown.
    count_day AS (
        SELECT principal, period, source_tag, MIN(first_date) AS first_date, MAX(last_date) AS last_date
        FROM base GROUP BY principal, period, source_tag
    ),
    seq AS (
        SELECT principal, period, source_tag,
               LAG(period) OVER (PARTITION BY principal, source_tag ORDER BY period) AS prev_period
        FROM count_day
    ),
    sized AS (
        SELECT b.*,
               CASE WHEN b.principal = 'unilever' AND pd.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd.pack_size::numeric > 0
                    THEN pd.pack_size::numeric END AS pack_size,
               CASE WHEN cd.first_date = cd.last_date AND b.principal = 'unilever' THEN cd.last_date END AS count_date
        FROM base b
        JOIN count_day cd USING (principal, period, source_tag)
        LEFT JOIN product_dimension pd ON pd.product_key = b.product_key
    ),
    priced AS (
        SELECT s.*,
               CASE WHEN s.pack_size IS NOT NULL THEN s.cases * s.pack_size + COALESCE(s.loose_pieces, 0) END AS pieces,
               CASE WHEN s.pack_size IS NULL THEN 'no_pack_size' END AS pieces_flag
        FROM sized s
    ),
    -- The product's own previous row; it is the previous COUNT's row only when its period
    -- is the principal's previous count (else the product was missing from that count).
    lagged AS (
        SELECT p.*,
               LAG(p.period) OVER w AS row_prev_period,
               LAG(p.pieces) OVER w AS row_prev_pieces,
               LAG(p.pesos) OVER w AS row_prev_pesos
        FROM priced p
        WINDOW w AS (PARTITION BY p.product_key, p.source_tag ORDER BY p.period)
    )
    SELECT l.principal, l.product_key, l.period, l.count_date, l.demand_period, l.data_kind, l.source_tag,
           l.cases, l.loose_pieces, l.pack_size, l.pieces, l.pieces_flag, l.pesos,
           l.any_active, l.any_inactive,
           q.prev_period,
           CASE WHEN q.prev_period IS NULL THEN NULL ELSE l.row_prev_period IS NOT DISTINCT FROM q.prev_period END,
           CASE WHEN l.row_prev_period = q.prev_period THEN l.row_prev_pieces END,
           CASE WHEN l.row_prev_period = q.prev_period THEN l.row_prev_pesos END,
           l.source_rows
    FROM lagged l
    JOIN seq q USING (principal, period, source_tag);
    ANALYZE mart.inventory_mart;

    -- idle_stock (real counts x real sales, Unilever: Del Monte has no product-level real sales)
    DELETE FROM mart.idle_stock;

    INSERT INTO mart.idle_stock
    WITH sales_months AS (
        SELECT DISTINCT period FROM mart.sales_mart
        WHERE principal = 'unilever' AND level = 'product' AND data_kind = 'real'
    ),
    counts AS (
        SELECT DISTINCT period FROM mart.inventory_mart WHERE principal = 'unilever' AND data_kind = 'real'
    ),
    win AS (
        SELECT c.period AS count_period,
               (SELECT MAX(sm.period) FROM sales_months sm WHERE sm.period <= c.period) AS window_end
        FROM counts c
    ),
    -- A window counts only when every one of its months has real sales on file, so
    -- "no sale in 6 months" is never claimed over months the sales file doesn't cover.
    full_win AS (
        SELECT w.count_period, w.window_end, mart.month_add(w.window_end, 1 - p_idle_months) AS window_start
        FROM win w
        WHERE w.window_end IS NOT NULL
          AND (SELECT COUNT(*) FROM sales_months sm
               WHERE sm.period BETWEEN mart.month_add(w.window_end, 1 - p_idle_months) AND w.window_end) = p_idle_months
    ),
    idle AS (
        SELECT w.count_period, w.window_start, w.window_end, i.*
        FROM full_win w
        JOIN mart.inventory_mart i ON i.principal = 'unilever' AND i.data_kind = 'real' AND i.period = w.count_period
        WHERE NOT EXISTS (
            SELECT 1 FROM mart.sales_mart s
            WHERE s.level = 'product' AND s.product_key = i.product_key AND s.data_kind = 'real'
              AND s.period BETWEEN w.window_start AND w.window_end AND s.pieces > 0
        )
    )
    SELECT 'unilever', d.count_period, d.count_date, d.product_key,
           d.pesos, d.pieces, d.cases, ls.last_sale, ls.last_sale IS NULL,
           d.window_start, d.window_end, p_idle_months
    FROM idle d
    LEFT JOIN LATERAL (
        SELECT MAX(s.period) AS last_sale FROM mart.sales_mart s
        WHERE s.level = 'product' AND s.product_key = d.product_key AND s.data_kind = 'real'
          AND s.period <= d.window_end AND s.pieces > 0
    ) ls ON true;

    -- accuracy_mart -----------------------------------------------------------
    DELETE FROM mart.accuracy_mart;

    INSERT INTO mart.accuracy_mart (
        run_id, forecast_source, run_label, cohort, principal, product_key, category_path, month,
        forecast_pieces, actual_pieces, ma3_pieces, miss_pieces, abs_miss_pieces, direction, run_length,
        price_per_piece, miss_pesos, abs_miss_pesos, surplus_pesos, shortage_pesos,
        opening_count_period, opening_pieces, closing_pieces, possibly_stock_limited, method, bin, status,
        avg_monthly_pieces, stock_limited_reason, count_possibly_partial)
    WITH bounds AS (
        SELECT MIN(period) AS first_month, MAX(period) AS last_month FROM mart.sales_mart
        WHERE principal = 'unilever' AND level = 'product' AND data_kind = 'real'
    ),
    real_counts AS (
        SELECT DISTINCT period FROM mart.inventory_mart WHERE principal = 'unilever' AND data_kind = 'real'
    ),
    v AS (
        SELECT r.run_id, r.kind, r.label, r.cohort, fv.product_key, fv.month, fv.forecast_pieces, fv.ma3_pieces,
               fv.method, fv.bin, fv.status,
               pd.principal, pd.category_path,
               -- Actual: real sales only. No row in a covered month = nothing sold (the
               -- series the router fits fills those with 0); a blank quantity = missing,
               -- never 0 (2026-10-03 blank-quantity decision); after the last real
               -- month = not known yet.
               CASE WHEN fv.month > b.last_month OR fv.month < b.first_month THEN NULL
                    WHEN rs.product_key IS NULL THEN 0
                    WHEN rs.pieces_null_rows > 0 THEN NULL
                    ELSE rs.pieces END AS actual_pieces,
               CASE WHEN fv.month > b.last_month OR fv.month < b.first_month THEN NULL
                    WHEN rs.product_key IS NULL THEN 0
                    WHEN rs.pieces_null_rows > 0 THEN NULL
                    ELSE rs.pesos END AS actual_pesos,
               mart.month_add(fv.month, -1) AS opening_period,
               oc.period IS NOT NULL AS opening_counted, oi.pieces AS opening_row_pieces, oi.product_key IS NOT NULL AS opening_listed,
               cc.period IS NOT NULL AS closing_counted, ci.pieces AS closing_row_pieces, ci.product_key IS NOT NULL AS closing_listed
        FROM mart.forecast_run r
        JOIN mart.forecast_run_value fv ON fv.run_id = r.run_id
        LEFT JOIN product_dimension pd ON pd.product_key = fv.product_key
        CROSS JOIN bounds b
        LEFT JOIN mart.sales_mart rs ON rs.level = 'product' AND rs.product_key = fv.product_key
              AND rs.period = fv.month AND rs.source_tag = 'real'
        LEFT JOIN real_counts oc ON oc.period = mart.month_add(fv.month, -1)
        LEFT JOIN mart.inventory_mart oi ON oi.principal = 'unilever' AND oi.data_kind = 'real'
              AND oi.period = mart.month_add(fv.month, -1) AND oi.product_key = fv.product_key
        LEFT JOIN real_counts cc ON cc.period = fv.month
        LEFT JOIN mart.inventory_mart ci ON ci.principal = 'unilever' AND ci.data_kind = 'real'
              AND ci.period = fv.month AND ci.product_key = fv.product_key
    ),
    -- The yardstick of kelvin/surplus-bias-experiment 3226cc4 README Part 0.1: the product's
    -- mean monthly pieces over the p_avg_months months BEFORE the month, counted from its
    -- first sale (a month without a row = 0; a blank quantity = 0, as the forecast runner
    -- reads it), at least p_avg_min_months months; one week = that mean x 12 / 52. The month
    -- itself is left out, so a stockout cannot lower its own yardstick.
    first_sale AS (
        SELECT product_key, MIN(period) AS first_month FROM mart.sales_mart
        WHERE principal = 'unilever' AND level = 'product' AND data_kind = 'real' AND pieces > 0
        GROUP BY product_key
    ),
    yard AS (
        SELECT k.product_key, k.month, w.n_months,
               CASE WHEN w.n_months >= p_avg_min_months THEN
                   (SELECT COALESCE(SUM(COALESCE(s.pieces, 0)), 0) FROM mart.sales_mart s
                    WHERE s.level = 'product' AND s.product_key = k.product_key AND s.source_tag = 'real'
                      AND s.period >= mart.month_add(k.month, -w.n_months) AND s.period < k.month) / w.n_months
               END AS avg_monthly_pieces
        FROM (SELECT DISTINCT product_key, month FROM mart.forecast_run_value) k
        LEFT JOIN first_sale fs ON fs.product_key = k.product_key
        CROSS JOIN LATERAL (
            SELECT CASE WHEN fs.first_month IS NULL THEN 0
                        ELSE LEAST(p_avg_months, GREATEST(0,
                             (substr(k.month, 1, 4)::int * 12 + substr(k.month, 6, 2)::int)
                             - (substr(fs.first_month, 1, 4)::int * 12 + substr(fs.first_month, 6, 2)::int)))
                   END AS n_months
        ) w
    ),
    stock AS (
        -- Part 0.1: missing from a count that was taken = 0 on hand (Unilever files omit zero
        -- rows, backend/stock_status.py), every real count as recorded; a month with no real
        -- count = unknown. A count on record as possibly partial is flagged, not dropped.
        SELECT v.*,
               CASE WHEN NOT opening_counted THEN NULL WHEN opening_listed THEN opening_row_pieces
                    ELSE 0 END AS opening_pieces,
               CASE WHEN NOT closing_counted THEN NULL WHEN closing_listed THEN closing_row_pieces
                    ELSE 0 END AS closing_pieces,
               (opening_counted AND opening_period = ANY(p_partial_counts))
                   OR (closing_counted AND month = ANY(p_partial_counts)) AS count_possibly_partial,
               forecast_pieces - actual_pieces AS miss_pieces,
               CASE WHEN forecast_pieces IS NULL OR actual_pieces IS NULL THEN NULL
                    WHEN forecast_pieces > actual_pieces THEN 'over'
                    WHEN forecast_pieces < actual_pieces THEN 'under'
                    ELSE 'exact' END AS direction
        FROM v
    ),
    runs AS (
        SELECT run_id, product_key, month,
               ROW_NUMBER() OVER (PARTITION BY run_id, product_key ORDER BY month)
               - ROW_NUMBER() OVER (PARTITION BY run_id, product_key, direction ORDER BY month) AS grp,
               direction
        FROM stock WHERE direction IS NOT NULL
    ),
    run_len AS (
        SELECT run_id, product_key, month,
               CASE WHEN direction = 'exact' THEN 0
                    ELSE ROW_NUMBER() OVER (PARTITION BY run_id, product_key, direction, grp ORDER BY month)::int END AS run_length
        FROM runs
    ),
    -- One selling price per product per run: its real pesos / pieces over the run's scored
    -- months (VAT-inclusive, "Total Sales Amt Inc. Tax"), the basis of the 2026-10-03
    -- forecast-error reports. NULL when either sum is not positive.
    price AS (
        SELECT run_id, product_key,
               CASE WHEN SUM(actual_pesos) > 0 AND SUM(actual_pieces) > 0
                    THEN SUM(actual_pesos) / SUM(actual_pieces) END AS price_per_piece
        FROM stock
        WHERE actual_pieces IS NOT NULL AND forecast_pieces IS NOT NULL
        GROUP BY run_id, product_key
    )
    , labelled AS (
        SELECT s.*, y.avg_monthly_pieces,
               CASE WHEN y.avg_monthly_pieces > 0 THEN y.avg_monthly_pieces * 12 / 52 END AS week_pieces
        FROM stock s
        LEFT JOIN yard y ON y.product_key = s.product_key AND y.month = s.month
    )
    SELECT s.run_id, s.kind, s.label, s.cohort, COALESCE(s.principal, 'unilever'), s.product_key,
           s.category_path, s.month,
           s.forecast_pieces, s.actual_pieces, s.ma3_pieces, s.miss_pieces, abs(s.miss_pieces), s.direction,
           rl.run_length, p.price_per_piece,
           s.miss_pieces * p.price_per_piece, abs(s.miss_pieces) * p.price_per_piece,
           GREATEST(s.miss_pieces, 0) * p.price_per_piece, GREATEST(-s.miss_pieces, 0) * p.price_per_piece,
           s.opening_period, s.opening_pieces, s.closing_pieces,
           -- Possibly stock-limited (3226cc4 Part 0.1), whatever the forecast's direction: the
           -- opening or closing count is 0, or below p_low_weeks weeks of average sales.
           -- Unknown when neither count exists, or when both are positive and there is no
           -- yardstick (under p_avg_min_months months of history, or an average of 0).
           CASE WHEN s.opening_pieces IS NULL AND s.closing_pieces IS NULL THEN NULL
                WHEN s.opening_pieces <= 0 OR s.closing_pieces <= 0 THEN true
                WHEN s.week_pieces IS NOT NULL
                     AND ((s.opening_pieces > 0 AND s.opening_pieces < p_low_weeks * s.week_pieces)
                          OR (s.closing_pieces > 0 AND s.closing_pieces < p_low_weeks * s.week_pieces)) THEN true
                WHEN s.week_pieces IS NOT NULL THEN false
                ELSE NULL END,
           s.method, s.bin, s.status,
           s.avg_monthly_pieces,
           NULLIF(concat_ws('; ',
               CASE WHEN s.opening_pieces <= 0 THEN 'opening zero' END,
               CASE WHEN s.closing_pieces <= 0 THEN 'closing zero' END,
               CASE WHEN s.opening_pieces > 0 AND s.opening_pieces < p_low_weeks * s.week_pieces
                    THEN 'opening < ' || (p_low_weeks::float8)::text || ' wk' END,
               CASE WHEN s.closing_pieces > 0 AND s.closing_pieces < p_low_weeks * s.week_pieces
                    THEN 'closing < ' || (p_low_weeks::float8)::text || ' wk' END), ''),
           s.count_possibly_partial
    FROM labelled s
    LEFT JOIN run_len rl ON rl.run_id = s.run_id AND rl.product_key = s.product_key AND rl.month = s.month
    LEFT JOIN price p ON p.run_id = s.run_id AND p.product_key = s.product_key;

    SELECT jsonb_build_object(
        'sales_mart', (SELECT COUNT(*) FROM mart.sales_mart),
        'flow_month', (SELECT COUNT(*) FROM mart.flow_month),
        'inventory_mart', (SELECT COUNT(*) FROM mart.inventory_mart),
        'idle_stock', (SELECT COUNT(*) FROM mart.idle_stock),
        'accuracy_mart', (SELECT COUNT(*) FROM mart.accuracy_mart),
        'forecast_runs', (SELECT COUNT(*) FROM mart.forecast_run)
    ) INTO v_counts;

    INSERT INTO mart.refresh_log (trigger, duration_ms, row_counts, params)
    VALUES (p_trigger, (EXTRACT(EPOCH FROM clock_timestamp() - t0) * 1000)::int, v_counts,
            jsonb_build_object('idle_months', p_idle_months, 'partial_counts', to_jsonb(p_partial_counts),
                               'low_weeks', p_low_weeks, 'avg_months', p_avg_months,
                               'avg_min_months', p_avg_min_months));
    RETURN v_counts;
END
$$;

SELECT mart.refresh('migration 0043');
