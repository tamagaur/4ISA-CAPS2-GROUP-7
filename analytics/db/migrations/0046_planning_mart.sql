-- 0046_planning_mart.sql — mart.planning_mart: one row per product x LP planning cycle, with
-- everything the Reorder page shows for it already joined (DEC-36's marts, extended to the plan).
--
-- WHY. GET /recommendations joined lp_recommendation to the product, the cycle's forecast, its
-- opening stock count, the ABC run, three months of sales, the review flag and the LP run on
-- every request: 12 statements (reports/diagnostics/speed_cache_2026-10-04). The plan only
-- changes when the pipeline or a decision changes it, so the joined row is kept here and the
-- page reads it in one statement.
--
-- ONE ROW = one lp_recommendation row (its key is unique on product x cycle). Every figure is
-- the one backend/routers/recommendations.py computed per request, by the same rules:
--   product          sku_code, sku_id (sku_code, else category_path), product_name, principal,
--                    pack_size (pieces per case, NULL when not a usable positive number)
--   Tier A class     tier + revenue_share at the principal's latest ABC run of basis
--                    tier_basis ('single' = one month's sales) for month tier_period
--   forecast         forecast_pieces + forecast_lower/upper (forecast_result for the cycle
--                    month), forecast_run_id (the mart.forecast_run that keeps those forecasts)
--   plan             safety_stock (ss_i), target_stock (rop_i), order_pieces (q_i)
--   opening stock    the count that OPENS the cycle month (the month before it, DEC-32), real
--                    rows only: stock_pieces (cases x pack size + loose), stock_cases,
--                    stock_pesos, opening_count_date. in_stock_count: TRUE listed, FALSE the
--                    principal was counted but not this product, NULL no count at all.
--                    opening_stock_pieces is the figure the plan reads: stock_pieces, or 0 when
--                    the product is missing from a count that never lists zero-stock items
--                    (p_zero_omitting, Unilever: backend/stock_status.py).
--   on order         the same count's "PO Qty". INFORMATION ONLY, meaning unverified, never
--                    subtracted from any order quantity (DEC-34).
--   order_pesos      order_pieces x order_price_per_piece: the last purchase price, the unit
--                    cost per case of the product's latest real count on or before the opening
--                    count (order_price_period) / pack size. NULL when there is none.
--   stock_status     IN STOCK / LOW / CRITICAL / NO DATA (backend/stock_status.py's rule on
--                    opening_stock_pieces; NO ROP cannot occur: every row has both quantities)
--   urgency          the same under the Reorder page's names: PLANNED / URGENT / CRITICAL / NO DATA
--   review           needs_review, review_reasons, the figures behind them (review_flag, DEC-33)
--   run              lp_run_key, allocation_pct (the run's supplier allocation %)
--   decision         decision_status (pending / accepted / dismissed; the app's word for a
--                    rejected row is 'dismissed'), decided_at, decided_by
--
-- KEPT IN STEP. mart.refresh_planning() rebuilds every row in one transaction (DELETE +
-- INSERT). analytics/marts.py calls it with every full refresh (data load, fill, forecast run,
-- LP run) and after a review-flag write; an edit to a product through the app calls it too; a
-- reorder decision updates its one row in the decision's own transaction.
-- mart.refresh_status gains planning_refreshed_at and planning_stale (a source changed after
-- the last planning refresh). A stale mart is never served: the endpoint falls back to the
-- per-request joins.
--
-- refresh_status.refreshed_at / stale keep their meaning: the last FULL refresh (a log row that
-- counts sales_mart), so a planning-only refresh cannot hide a stale dashboard mart.
--
-- Rollback: DROP FUNCTION mart.refresh_planning(text, integer, text[]); DROP TABLE
-- mart.planning_mart; re-create mart.refresh_status from 0041 (DROP VIEW first: it gained two
-- columns); DELETE FROM mart.refresh_log WHERE row_counts -> 'sales_mart' IS NULL;
-- DELETE FROM schema_migrations WHERE filename = '0046_planning_mart.sql';

CREATE TABLE mart.planning_mart (
    recommendation_key      bigint  NOT NULL UNIQUE,
    product_key             bigint  NOT NULL,
    planning_cycle_date     date    NOT NULL,
    principal               text    NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    sku_code                text,
    sku_id                  text,
    product_name            text,
    pack_size               numeric,
    tier                    text    CHECK (tier IN ('A', 'B', 'C')),
    revenue_share           numeric,
    tier_basis              text,
    tier_period             text,
    forecast_pieces         numeric,
    forecast_lower          numeric,
    forecast_upper          numeric,
    forecast_status         text,
    forecast_run_id         bigint,
    safety_stock            numeric NOT NULL,
    target_stock            numeric NOT NULL,
    opening_period          text    NOT NULL CHECK (opening_period ~ '^[0-9]{4}-[0-9]{2}$'),
    opening_count_date      date,
    opening_count_first_date date,
    opening_count_last_date date,
    opening_count_rows      integer,
    in_stock_count          boolean,
    stock_not_in_count      boolean NOT NULL,
    stock_pieces            numeric,
    stock_cases             numeric,
    stock_pesos             numeric,
    opening_stock_pieces    numeric,
    on_order_pieces         numeric,
    on_order_cases          numeric,
    on_order_unparsed       bigint,
    avg_monthly_sales_pesos numeric,
    order_pieces            numeric NOT NULL,
    order_price_per_piece   numeric,
    order_price_period      text,
    order_pesos             numeric,
    stock_status            text    NOT NULL CHECK (stock_status IN ('IN STOCK', 'LOW', 'CRITICAL', 'NO ROP', 'NO DATA')),
    urgency                 text    NOT NULL CHECK (urgency IN ('PLANNED', 'URGENT', 'CRITICAL', 'NO DATA')),
    needs_review            boolean,
    review_reasons          text[],
    review_over_run_months  integer,
    review_collapse_ratio   numeric,
    lp_run_key              bigint,
    allocation_pct          numeric,
    decision_status         text    NOT NULL CHECK (decision_status IN ('pending', 'accepted', 'dismissed')),
    decided_at              timestamptz,
    decided_by              text,
    generated_at            timestamptz NOT NULL,
    refreshed_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (product_key, planning_cycle_date)
);
CREATE INDEX planning_mart_cycle ON mart.planning_mart (planning_cycle_date, decision_status);

ALTER TABLE mart.planning_mart ENABLE ROW LEVEL SECURITY;

-- p_cover_months: analytics.params.SKU_COVER_HISTORY_MONTHS. p_zero_omitting: the principals
-- whose stock count never lists a zero-stock item (backend/stock_status.COUNT_OMITS_ZERO_STOCK).
-- analytics/marts.py passes both; the defaults are the same, pinned by tests/test_planning_mart.py.
CREATE FUNCTION mart.refresh_planning(
    p_trigger text DEFAULT 'manual',
    p_cover_months integer DEFAULT 3,
    p_zero_omitting text[] DEFAULT ARRAY['unilever']
) RETURNS jsonb LANGUAGE plpgsql SET search_path = mart, public AS $$
DECLARE
    t0 timestamptz := clock_timestamp();
    v_counts jsonb;
BEGIN
    -- The full refresh's lock: a planning refresh never interleaves with one (and takes it
    -- again without waiting when it runs inside the full refresh's own transaction).
    PERFORM pg_advisory_xact_lock(hashtext('mart.refresh'));

    DELETE FROM mart.planning_mart;

    INSERT INTO mart.planning_mart (
        recommendation_key, product_key, planning_cycle_date, principal, sku_code, sku_id, product_name, pack_size,
        tier, revenue_share, tier_basis, tier_period,
        forecast_pieces, forecast_lower, forecast_upper, forecast_status, forecast_run_id,
        safety_stock, target_stock,
        opening_period, opening_count_date, opening_count_first_date, opening_count_last_date, opening_count_rows,
        in_stock_count, stock_not_in_count, stock_pieces, stock_cases, stock_pesos, opening_stock_pieces,
        on_order_pieces, on_order_cases, on_order_unparsed, avg_monthly_sales_pesos,
        order_pieces, order_price_per_piece, order_price_period, order_pesos,
        stock_status, urgency,
        needs_review, review_reasons, review_over_run_months, review_collapse_ratio,
        lp_run_key, allocation_pct, decision_status, decided_at, decided_by, generated_at)
    WITH lr AS (
        SELECT r.*, to_char(r.planning_cycle_date - interval '1 month', 'YYYY-MM') AS opening_period
        FROM lp_recommendation r
    ),
    periods AS (SELECT DISTINCT opening_period FROM lr),
    -- backend/stock_units.py's STOCK_AT_PERIOD_SQL and ON_ORDER_AT_PERIOD_SQL, for every
    -- opening count at once: real rows only, pieces NULL without a usable pack size.
    inv AS (
        SELECT i.product_key, i._period AS period,
               CASE WHEN pd_pack.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd_pack.pack_size::numeric > 0
                    THEN SUM(i.quantity_on_hand) * pd_pack.pack_size::numeric + COALESCE(SUM(i.quantity_pieces), 0)
               END AS stock_pieces,
               SUM(COALESCE(i.valuation, i.quantity_on_hand * i.unit_cost_per_case)) AS stock_pesos,
               SUM(i.quantity_on_hand) AS stock_cases,
               CASE WHEN pd_pack.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd_pack.pack_size::numeric > 0
                    THEN SUM(i.po_qty_cases) * pd_pack.pack_size::numeric + COALESCE(SUM(i.po_qty_pieces), 0)
               END AS on_order_pieces,
               SUM(i.po_qty_cases) AS on_order_cases,
               COUNT(*) - COUNT(i.po_qty_cases) AS on_order_unparsed
        FROM inventory_fact_real i
        JOIN product_dimension pd_pack ON pd_pack.product_key = i.product_key
        WHERE i._period IN (SELECT opening_period FROM periods)
        GROUP BY i.product_key, i._period, pd_pack.pack_size
    ),
    counted AS (
        SELECT i.principal, i._period AS period, COUNT(*)::int AS row_count,
               MIN(i.snapshot_date) AS first_date, MAX(i.snapshot_date) AS last_date
        FROM inventory_fact_real i
        WHERE i._period IN (SELECT opening_period FROM periods)
        GROUP BY i.principal, i._period
    ),
    -- Each principal's latest ABC run on one month's sales (method 'single').
    abc_latest AS (
        SELECT principal, MAX(classification_period) AS period
        FROM abc_classification WHERE method = 'single' GROUP BY principal
    ),
    -- The p_cover_months most recent sales months the file has at or before each opening
    -- count; a month the product has no row in counts as 0 (the divisor is the window).
    sales_months AS (SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real),
    cover_window AS (
        SELECT p.opening_period, m.calendar_month, COUNT(*) OVER (PARTITION BY p.opening_period) AS months
        FROM periods p
        CROSS JOIN LATERAL (
            SELECT sm.calendar_month FROM sales_months sm
            WHERE sm.calendar_month <= p.opening_period
            ORDER BY sm.calendar_month DESC LIMIT p_cover_months
        ) m
    ),
    sales AS (
        SELECT w.opening_period, d.product_key, SUM(d.net_amount) / MAX(w.months) AS avg_monthly_sales_pesos
        FROM cover_window w
        JOIN unilever_sku_demand_fact_real d ON d.calendar_month = w.calendar_month
        GROUP BY w.opening_period, d.product_key
    ),
    served_run AS (
        SELECT run_id FROM mart.forecast_run
        WHERE kind = 'stored_run' AND source_generated_at = (SELECT MAX(generated_at) FROM forecast_result)
    ),
    joined AS (
        SELECT lr.recommendation_key, lr.product_key, lr.planning_cycle_date, pd.principal, pd.sku_code,
               COALESCE(pd.sku_code, pd.category_path) AS sku_id, pd.product_name,
               CASE WHEN pd.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd.pack_size::numeric > 0
                    THEN pd.pack_size::numeric END AS pack_size,
               abc.tier, abc.revenue_share,
               CASE WHEN abc.product_key IS NOT NULL THEN 'single' END AS tier_basis,
               CASE WHEN abc.product_key IS NOT NULL THEN abc.classification_period END AS tier_period,
               fr.forecast_value AS forecast_pieces, fr.confidence_lower AS forecast_lower,
               fr.confidence_upper AS forecast_upper, fr.status AS forecast_status,
               CASE WHEN fr.product_key IS NOT NULL THEN (SELECT run_id FROM served_run) END AS forecast_run_id,
               lr.ss_i AS safety_stock, lr.rop_i AS target_stock,
               lr.opening_period,
               CASE WHEN pd.principal = 'unilever' AND counted.first_date = counted.last_date
                    THEN counted.last_date END AS opening_count_date,
               counted.first_date AS opening_count_first_date, counted.last_date AS opening_count_last_date,
               counted.row_count AS opening_count_rows,
               CASE WHEN inv.product_key IS NOT NULL THEN TRUE
                    WHEN counted.principal IS NOT NULL THEN FALSE
               END AS in_stock_count,
               inv.stock_pieces, inv.stock_cases, inv.stock_pesos,
               inv.on_order_pieces, inv.on_order_cases, inv.on_order_unparsed,
               sales.avg_monthly_sales_pesos,
               lr.q_i AS order_pieces,
               CASE WHEN pd.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd.pack_size::numeric > 0
                    THEN price.unit_cost_per_case / pd.pack_size::numeric END AS order_price_per_piece,
               CASE WHEN pd.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd.pack_size::numeric > 0
                    THEN price.period END AS order_price_period,
               rf.needs_review, rf.reasons AS review_reasons, rf.over_run_months AS review_over_run_months,
               rf.collapse_ratio AS review_collapse_ratio,
               lr.lp_run_key, NULLIF(run.model #>> '{allocation,pct}', '')::numeric AS allocation_pct,
               lr.status AS decision_status, lr.decided_at, lr.decided_by, lr.generated_at
        FROM lr
        JOIN product_dimension pd ON pd.product_key = lr.product_key
        LEFT JOIN forecast_result fr
               ON fr.product_key = lr.product_key AND fr.forecast_date = lr.planning_cycle_date
        LEFT JOIN inv ON inv.product_key = lr.product_key AND inv.period = lr.opening_period
        LEFT JOIN counted ON counted.principal = pd.principal AND counted.period = lr.opening_period
        LEFT JOIN abc_latest ON abc_latest.principal = pd.principal
        LEFT JOIN abc_classification abc
               ON abc.product_key = lr.product_key AND abc.method = 'single'
              AND abc.classification_period = abc_latest.period
        LEFT JOIN sales ON sales.product_key = lr.product_key AND sales.opening_period = lr.opening_period
        LEFT JOIN review_flag rf
               ON rf.product_key = lr.product_key AND rf.planning_cycle_date = lr.planning_cycle_date
        LEFT JOIN lp_run run ON run.run_key = lr.lp_run_key
        LEFT JOIN LATERAL (
            SELECT i._period AS period, MAX(i.unit_cost_per_case) AS unit_cost_per_case
            FROM inventory_fact_real i
            WHERE i.product_key = lr.product_key AND i._period <= lr.opening_period AND i.unit_cost_per_case > 0
            GROUP BY i._period
            ORDER BY i._period DESC LIMIT 1
        ) price ON true
    ),
    planned AS (
        SELECT j.*,
               (j.in_stock_count IS FALSE AND j.principal = ANY(p_zero_omitting)) AS stock_not_in_count,
               CASE WHEN j.in_stock_count IS FALSE AND j.principal = ANY(p_zero_omitting) THEN 0
                    ELSE j.stock_pieces END AS opening_stock_pieces
        FROM joined j
    ),
    graded AS (
        SELECT p.*,
               CASE WHEN p.opening_stock_pieces IS NULL THEN 'NO DATA'
                    WHEN p.opening_stock_pieces < p.safety_stock THEN 'CRITICAL'
                    WHEN p.opening_stock_pieces < p.target_stock THEN 'LOW'
                    ELSE 'IN STOCK' END AS stock_status
        FROM planned p
    )
    SELECT recommendation_key, product_key, planning_cycle_date, principal, sku_code, sku_id, product_name, pack_size,
           tier, revenue_share, tier_basis, tier_period,
           forecast_pieces, forecast_lower, forecast_upper, forecast_status, forecast_run_id,
           safety_stock, target_stock,
           opening_period, opening_count_date, opening_count_first_date, opening_count_last_date, opening_count_rows,
           in_stock_count, stock_not_in_count, stock_pieces, stock_cases, stock_pesos, opening_stock_pieces,
           on_order_pieces, on_order_cases, on_order_unparsed, avg_monthly_sales_pesos,
           order_pieces, order_price_per_piece, order_price_period, order_pieces * order_price_per_piece,
           stock_status,
           CASE stock_status WHEN 'LOW' THEN 'URGENT' WHEN 'IN STOCK' THEN 'PLANNED' ELSE stock_status END,
           needs_review, review_reasons, review_over_run_months, review_collapse_ratio,
           lp_run_key, allocation_pct, decision_status, decided_at, decided_by, generated_at
    FROM graded;
    ANALYZE mart.planning_mart;

    SELECT jsonb_build_object('planning_mart', (SELECT COUNT(*) FROM mart.planning_mart)) INTO v_counts;

    INSERT INTO mart.refresh_log (trigger, duration_ms, row_counts, params)
    VALUES (p_trigger, (EXTRACT(EPOCH FROM clock_timestamp() - t0) * 1000)::int, v_counts,
            jsonb_build_object('scope', 'planning', 'cover_months', p_cover_months,
                               'zero_omitting', to_jsonb(p_zero_omitting)));
    RETURN v_counts;
END
$$;

-- refreshed_at / trigger / stale: the last FULL refresh, as before (a planning-only log row
-- counts no sales_mart). planning_stale: the plan's sources changed after the last planning
-- refresh. A reorder decision is not among them: it updates its own mart row as it commits.
CREATE OR REPLACE VIEW mart.refresh_status AS
    SELECT r.refreshed_at, r.trigger,
           src.latest_load, src.latest_fill, src.latest_forecast, src.latest_lp_run,
           (r.refreshed_at IS NULL
            OR GREATEST(src.latest_load, src.latest_fill, src.latest_forecast, src.latest_lp_run) > r.refreshed_at) AS stale,
           p.refreshed_at AS planning_refreshed_at,
           (p.refreshed_at IS NULL
            OR GREATEST(src.latest_load, src.latest_fill, src.latest_forecast, src.latest_lp_run,
                        plan.latest_review_flag, plan.latest_abc, plan.latest_product_edit) > p.refreshed_at) AS planning_stale
    FROM (SELECT 1) one
    LEFT JOIN LATERAL (SELECT refreshed_at, trigger FROM mart.refresh_log
                       WHERE row_counts -> 'sales_mart' IS NOT NULL ORDER BY refresh_id DESC LIMIT 1) r ON true
    LEFT JOIN LATERAL (SELECT refreshed_at FROM mart.refresh_log
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
               (SELECT MAX(computed_at) FROM abc_classification WHERE method = 'single') AS latest_abc,
               (SELECT MAX(created_at) FROM audit_log WHERE action = 'Edit SKU') AS latest_product_edit
    ) plan;

-- The first build.
SELECT mart.refresh_planning('migration 0046');
