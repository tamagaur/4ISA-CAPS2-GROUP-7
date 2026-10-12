-- 0049_planning_mart_tier_anchor.sql — mart.refresh_planning(): anchor tier/tier_period to each
-- row's OWN planning cycle month, same as the per-request join path (backend/routers/
-- recommendations.py:626, latest_abc_periods(db, principal, cycle_month)).
--
-- WHY. 0046's `abc_latest` CTE took ONE global MAX(classification_period) per principal and
-- applied it to every row regardless of the row's own planning_cycle_date — so an old cycle
-- (e.g. 2023-12) got tiered off 2026-02's run, a run that didn't exist yet at the time. The
-- join path never does this: recommendations.py resolves the ABC anchor PER CYCLE, at or
-- before that cycle's own month (fc21d1b). This migration does the same per row, inside
-- refresh_planning(): `cycle_abc` replaces `abc_latest`, keyed by (principal, cycle_month)
-- instead of principal alone.
--
-- Two further corrections, from reading what the join path actually serves (not just what it
-- resolves):
--   tier / tier_period  — the join path serves abc_last (classification_period <= the cycle
--                         anchor, carried forward when the exact period has no row for this
--                         product — recommendations.py:286-294). 0046's `tier`/`tier_period`
--                         came from the EXACT-period `abc` join instead, which is NULL
--                         whenever a product wasn't classified in that one run. tier/tier_period
--                         now come from abc_last; revenue_share (and therefore
--                         backend._to_item's tier_is_current = revenue_share is not None,
--                         recommendations.py:687) is unchanged — it still reads the exact
--                         join, which is the correct "is this the current run" signal.
--   tier_basis           — follows tier/tier_period: the method of the SAME row they came
--                         from (abc_last.method), not the exact join's.
--
-- mart.planning_mart.tier_period already exists as a column (0046); this migration does not
-- add one. backend/planning_mart.py's ROW_COLUMNS does not project tier_period into the API
-- response for mart-served rows (checked 2026-10-11, recommendations.py's per-row _to_item
-- reads r.get("tier_period"), which is always None for a mart row) — that is a backend fix,
-- out of scope for this SQL-only migration; flagged for a follow-up session.
--
-- Expected (live, 2026-10-11, read before writing this file): planning_mart holds 277 rows,
-- all Unilever (lp_recommendation has zero Del Monte rows — known, recommendations.py:559).
-- 147 of 277 stored (tier, tier_period) pairs diverge from the cycle-anchored value today.
-- After this migration's own rebuild, divergence must be 0 (enforced below: RAISE EXCEPTION
-- rolls the migration back if it isn't — self-check modelled on 0048's row-count guard).
--
-- Rollback: CREATE OR REPLACE FUNCTION mart.refresh_planning(...) from 0046's body (restores
-- the unanchored abc_latest CTE and the exact-join tier/tier_period); then
-- SELECT mart.refresh_planning('rollback 0049'); DELETE FROM schema_migrations WHERE filename
-- = '0049_planning_mart_tier_anchor.sql'.

-- Snapshot the correct (cycle-anchored) tier/tier_period for every lp_recommendation row,
-- against the OLD function's stored values, before replacing it — the "before" count below
-- would otherwise be unmeasurable once refresh_planning() has already rebuilt the mart.
CREATE TEMP VIEW _0049_correct AS
WITH lr AS (SELECT r.recommendation_key, r.product_key, r.planning_cycle_date FROM lp_recommendation r),
cycle_months AS (
    SELECT DISTINCT pd.principal, to_char(lr.planning_cycle_date, 'YYYY-MM') AS cycle_month
    FROM lr JOIN product_dimension pd ON pd.product_key = lr.product_key
),
cycle_abc AS (
    SELECT cm.principal, cm.cycle_month,
           (SELECT MAX(classification_period) FROM abc_classification ac
            WHERE ac.method = CASE cm.principal WHEN 'unilever' THEN 't12m_new' ELSE 'single' END
              AND ac.classification_period <= cm.cycle_month) AS period
    FROM cycle_months cm
)
SELECT lr.recommendation_key, abc_last.tier AS correct_tier,
       abc_last.classification_period AS correct_tier_period
FROM lr
JOIN product_dimension pd ON pd.product_key = lr.product_key
JOIN cycle_abc ca ON ca.principal = pd.principal AND ca.cycle_month = to_char(lr.planning_cycle_date, 'YYYY-MM')
LEFT JOIN LATERAL (
    SELECT ac2.tier, ac2.classification_period
    FROM abc_classification ac2
    WHERE ac2.product_key = lr.product_key
      AND ac2.method = CASE pd.principal WHEN 'unilever' THEN 't12m_new' ELSE 'single' END
      AND ac2.classification_period <= ca.period
    ORDER BY ac2.classification_period DESC LIMIT 1
) abc_last ON true;

CREATE TEMP TABLE _0049_before_count AS
SELECT count(*) AS n FROM mart.planning_mart pm JOIN _0049_correct c USING (recommendation_key)
WHERE pm.tier IS DISTINCT FROM c.correct_tier OR pm.tier_period IS DISTINCT FROM c.correct_tier_period;

CREATE OR REPLACE FUNCTION mart.refresh_planning(
    p_trigger text DEFAULT 'manual',
    p_cover_months integer DEFAULT 3,
    p_zero_omitting text[] DEFAULT ARRAY['unilever'],
    p_tier_a_basis text DEFAULT 't12m_new'
) RETURNS jsonb LANGUAGE plpgsql SET search_path = mart, public AS $$
DECLARE
    t0 timestamptz := clock_timestamp();
    v_counts jsonb;
BEGIN
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
    -- Each (principal, cycle month)'s own ABC anchor: the latest run AT OR BEFORE that row's
    -- own planning_cycle_date month, exactly as backend/principals.latest_abc_periods resolves
    -- it per request (recommendations.py:626) — never one global MAX applied to every cycle.
    cycle_months AS (
        SELECT DISTINCT pd.principal, to_char(lr.planning_cycle_date, 'YYYY-MM') AS cycle_month
        FROM lr JOIN product_dimension pd ON pd.product_key = lr.product_key
    ),
    cycle_abc AS (
        SELECT cm.principal, cm.cycle_month,
               (SELECT MAX(classification_period) FROM abc_classification ac
                WHERE ac.method = CASE cm.principal WHEN 'unilever' THEN p_tier_a_basis ELSE 'single' END
                  AND ac.classification_period <= cm.cycle_month) AS period
        FROM cycle_months cm
    ),
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
               abc_last.tier, abc.revenue_share,
               abc_last.method AS tier_basis, abc_last.classification_period AS tier_period,
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
        LEFT JOIN cycle_abc ON cycle_abc.principal = pd.principal
                            AND cycle_abc.cycle_month = to_char(lr.planning_cycle_date, 'YYYY-MM')
        -- The exact-period join (revenue_share only — the join path's own "is this run
        -- current" signal, recommendations.py:260,443-446).
        LEFT JOIN abc_classification abc
               ON abc.product_key = lr.product_key
              AND abc.method = CASE pd.principal WHEN 'unilever' THEN p_tier_a_basis ELSE 'single' END
              AND abc.classification_period = cycle_abc.period
        -- The carried-forward join (tier / tier_period as displayed — recommendations.py:286-294).
        LEFT JOIN LATERAL (
            SELECT ac2.tier, ac2.classification_period, ac2.method
            FROM abc_classification ac2
            WHERE ac2.product_key = lr.product_key
              AND ac2.method = CASE pd.principal WHEN 'unilever' THEN p_tier_a_basis ELSE 'single' END
              AND ac2.classification_period <= cycle_abc.period
            ORDER BY ac2.classification_period DESC LIMIT 1
        ) abc_last ON true
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
                               'zero_omitting', to_jsonb(p_zero_omitting), 'tier_a_basis', p_tier_a_basis));
    RETURN v_counts;
END
$$;

-- Rebuild now: existing rows do NOT self-heal on their own — they only change when
-- refresh_planning() runs again (analytics/marts.py's next full refresh, or an app edit/decide
-- call) — so without this call the fix sits inert in the function until something else
-- triggers a refresh. This call makes it immediate, as 0046 did for its own first build.
SELECT mart.refresh_planning('migration 0049');

-- Self-check (modelled on 0048's row-count guard): the rebuild above must have resolved every
-- divergence the before-snapshot found. A non-zero after-count means the fix is wrong — abort
-- and roll back rather than leave a migration on record that didn't do what it claims.
DO $do$
DECLARE
    before_n integer;
    after_n integer;
BEGIN
    SELECT n INTO before_n FROM _0049_before_count;
    SELECT count(*) INTO after_n
    FROM mart.planning_mart pm JOIN _0049_correct c USING (recommendation_key)
    WHERE pm.tier IS DISTINCT FROM c.correct_tier OR pm.tier_period IS DISTINCT FROM c.correct_tier_period;
    IF after_n <> 0 THEN
        RAISE EXCEPTION USING MESSAGE =
            '0049: ' || after_n || ' mart row(s) still diverge from the cycle-anchored tier/tier_period '
            || 'after refresh_planning() (before: ' || before_n || '). Rolling back.';
    END IF;
    RAISE NOTICE '0049: tier/tier_period divergence before % row(s), after % row(s)', before_n, after_n;
END
$do$;

DROP VIEW _0049_correct;
DROP TABLE _0049_before_count;
