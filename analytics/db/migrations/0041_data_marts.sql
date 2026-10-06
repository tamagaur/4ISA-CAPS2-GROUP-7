-- 0041_data_marts.sql — schema `mart`: one row per product x month (sales), product x
-- stock count (inventory), product x month x forecast run (accuracy), plus idle stock and
-- the month-level flows (purchases, estimated receipts, returns). Built so every dashboard
-- card can answer for the selected date range from small pre-summed tables.
--
-- WHAT IS IN IT
--   sales_mart       product x month, pieces + pesos. Unilever: unilever_sku_demand_fact (SKU
--                    grain). Del Monte: sellout_fact (category grain, its real sales) and
--                    sku_demand_fill (the DEC-31 product split; level 'product', never in a
--                    principal total: it re-divides the same real sell-out pesos).
--   flow_month       principal x month: purchases (purchase_fact, on the sales line's tax basis,
--                    the dashboard's _received_by_period rule), estimated receipts
--                    (derived_receipt_fact), returns (salesreturn_fact, Net Amount as recorded).
--   inventory_mart   product x stock count: count date, cases, loose pieces, pieces (Unilever:
--                    cases x pack size + loose; Del Monte: NULL, flag 'no_pack_size'), pesos at
--                    last purchase price (valuation, else cases x unit cost), previous count.
--   idle_stock       Unilever products in a real count with no piece sold in the
--                    p_idle_months (analytics.params.DEAD_SKU_MONTHS = 6) real sales months
--                    ending at the latest sales month on or before the count.
--   forecast_run /   forecast history. NEVER rebuilt by refresh(): a stored run is captured
--   forecast_run_value from forecast_result (capture_forecast_result), a recreated backtest is
--                    written by scripts/backtest_forecast_run.py. Each run keeps its own rows,
--                    so a new forecast run no longer overwrites the last one.
--   accuracy_mart    product x month x run: forecast, actual (real only), signed miss in
--                    pieces and pesos (selling price, VAT-inclusive), direction, run length,
--                    possibly_stock_limited.
--
-- data_kind ON EVERY ROW: 'real' (is_demo = false), 'generated' (synthetic_v2, the
-- placeholder generator) or 'filled' (every other fill_source: DEC-31 fills, derived
-- receipts, the product split, gap and branch copies). KPIs, Pareto and accuracy read real
-- rows only, through the *_real views; charts may show filled rows labelled as estimated.
--
-- refresh(): DELETE + INSERT of every derived mart in ONE transaction (readers keep the old
-- rows until it commits), logged in mart.refresh_log. Called after every data load (the
-- slice loader), every fill run, forecast run and LP run (analytics/marts.py). Sources are
-- read from public; nothing outside this schema is written.
--
-- possibly_stock_limited (accuracy_mart) has NO rule on record before this migration
-- (kelvin/forecast-error-business README: "a stock-out can't be told apart from lost
-- demand", prose only). Defined here without a threshold: over-forecast AND the product
-- had 0 pieces at the count that opens or closes the month (a Unilever product missing
-- from a count that was taken = 0 on hand, backend/stock_status.py; missing from a
-- possibly-partial count = unknown). PENDING Yuan's review.
--
-- Rollback: DROP SCHEMA mart CASCADE; DELETE FROM schema_migrations WHERE filename =
-- '0041_data_marts.sql'; (drops the forecast history captured since, back it up first).

CREATE SCHEMA IF NOT EXISTS mart;

CREATE OR REPLACE FUNCTION mart.data_kind(p_is_demo boolean, p_fill_source text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_is_demo IS NOT TRUE THEN 'real'
        WHEN p_fill_source IS NULL OR p_fill_source = 'synthetic_v2' THEN 'generated'
        ELSE 'filled'
    END
$$;

CREATE OR REPLACE FUNCTION mart.source_tag(p_is_demo boolean, p_fill_source text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_is_demo IS NOT TRUE THEN 'real'
        ELSE COALESCE(p_fill_source, 'demo_untagged')
    END
$$;

CREATE OR REPLACE FUNCTION mart.month_add(p_period text, p_months int)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT to_char(to_date(p_period, 'YYYY-MM') + make_interval(months => p_months), 'YYYY-MM')
$$;

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

CREATE TABLE mart.sales_mart (
    principal                  text    NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    level                      text    NOT NULL CHECK (level IN ('product', 'category')),
    product_key                bigint  NOT NULL,
    category_path              text,
    period                     text    NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    data_kind                  text    NOT NULL CHECK (data_kind IN ('real', 'filled', 'generated')),
    source_tag                 text    NOT NULL,
    in_principal_total         boolean NOT NULL,
    preview_placeholder        boolean NOT NULL,
    pieces                     numeric,
    pieces_null_rows           integer NOT NULL,
    pieces_unit_confirmed      boolean NOT NULL,
    pesos                      numeric,
    pesos_basis                text    NOT NULL,
    gsv                        numeric,
    source_rows                integer NOT NULL,
    PRIMARY KEY (level, product_key, period, source_tag)
);

CREATE TABLE mart.flow_month (
    principal      text    NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    period         text    NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    flow           text    NOT NULL CHECK (flow IN ('purchases', 'estimated_receipts', 'returns')),
    data_kind      text    NOT NULL CHECK (data_kind IN ('real', 'filled', 'generated')),
    source_tag     text    NOT NULL,
    pesos          numeric,
    pieces         numeric,
    cases          numeric,
    pesos_basis    text    NOT NULL,
    source_rows    integer NOT NULL,
    negative_rows  integer NOT NULL,
    products       integer,
    PRIMARY KEY (principal, period, flow, source_tag)
);

CREATE TABLE mart.inventory_mart (
    principal         text    NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    product_key       bigint  NOT NULL,
    period            text    NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    count_date        date,
    demand_period     text,
    data_kind         text    NOT NULL CHECK (data_kind IN ('real', 'filled', 'generated')),
    source_tag        text    NOT NULL,
    cases             numeric,
    loose_pieces      numeric,
    pack_size         numeric,
    pieces            numeric,
    pieces_flag       text    CHECK (pieces_flag IN ('no_pack_size')),
    pesos             numeric,
    any_active        boolean,
    any_inactive      boolean,
    prev_period       text,
    prev_in_count     boolean,
    prev_pieces       numeric,
    prev_pesos        numeric,
    source_rows       integer NOT NULL,
    PRIMARY KEY (product_key, period, source_tag)
);

CREATE TABLE mart.idle_stock (
    principal          text    NOT NULL,
    count_period       text    NOT NULL,
    count_date         date,
    product_key        bigint  NOT NULL,
    pesos              numeric,
    pieces             numeric,
    cases              numeric,
    last_sale_period   text,
    never_sold         boolean NOT NULL,
    window_start       text    NOT NULL,
    window_end         text    NOT NULL,
    window_months      integer NOT NULL,
    PRIMARY KEY (count_period, product_key)
);

CREATE TABLE mart.forecast_run (
    run_id               bigserial PRIMARY KEY,
    kind                 text NOT NULL CHECK (kind IN ('stored_run', 'backtest_recreated')),
    label                text NOT NULL UNIQUE,
    cohort               text,
    window_start         text,
    window_end           text,
    source_generated_at  timestamptz,
    code_version         text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    created_by           text,
    notes                jsonb
);
CREATE UNIQUE INDEX forecast_run_stored_once ON mart.forecast_run (source_generated_at) WHERE kind = 'stored_run';

CREATE TABLE mart.forecast_run_value (
    run_id            bigint  NOT NULL REFERENCES mart.forecast_run (run_id) ON DELETE CASCADE,
    product_key       bigint  NOT NULL,
    month             text    NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    forecast_pieces   numeric,
    confidence_lower  numeric,
    confidence_upper  numeric,
    status            text,
    method            text,
    bin               text,
    ma3_pieces        numeric,
    mase              numeric,
    backup_fired      boolean,
    PRIMARY KEY (run_id, product_key, month)
);

CREATE TABLE mart.accuracy_mart (
    run_id                  bigint  NOT NULL,
    forecast_source         text    NOT NULL CHECK (forecast_source IN ('stored_run', 'backtest_recreated')),
    run_label               text    NOT NULL,
    cohort                  text,
    principal               text    NOT NULL,
    product_key             bigint  NOT NULL,
    category_path           text,
    month                   text    NOT NULL,
    forecast_pieces         numeric,
    actual_pieces           numeric,
    ma3_pieces              numeric,
    miss_pieces             numeric,
    abs_miss_pieces         numeric,
    direction               text    CHECK (direction IN ('over', 'under', 'exact')),
    run_length              integer,
    price_per_piece         numeric,
    miss_pesos              numeric,
    abs_miss_pesos          numeric,
    surplus_pesos           numeric,
    shortage_pesos          numeric,
    opening_count_period    text,
    opening_pieces          numeric,
    closing_pieces          numeric,
    possibly_stock_limited  boolean,
    method                  text,
    bin                     text,
    status                  text,
    PRIMARY KEY (run_id, product_key, month)
);
CREATE INDEX accuracy_mart_month ON mart.accuracy_mart (run_id, month);

CREATE TABLE mart.refresh_log (
    refresh_id    bigserial PRIMARY KEY,
    refreshed_at  timestamptz NOT NULL DEFAULT now(),
    trigger       text NOT NULL,
    duration_ms   integer NOT NULL,
    row_counts    jsonb NOT NULL,
    params        jsonb NOT NULL
);

-- Every public table has row-level security on; the marts match. No policy: only the
-- owning role (the backend's and the pipeline's) reads or writes them.
ALTER TABLE mart.sales_mart ENABLE ROW LEVEL SECURITY;
ALTER TABLE mart.flow_month ENABLE ROW LEVEL SECURITY;
ALTER TABLE mart.inventory_mart ENABLE ROW LEVEL SECURITY;
ALTER TABLE mart.idle_stock ENABLE ROW LEVEL SECURITY;
ALTER TABLE mart.forecast_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE mart.forecast_run_value ENABLE ROW LEVEL SECURITY;
ALTER TABLE mart.accuracy_mart ENABLE ROW LEVEL SECURITY;
ALTER TABLE mart.refresh_log ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- Views: the real-only reads (the _Real convention) and the rollups
-- ---------------------------------------------------------------------------

CREATE VIEW mart.sales_mart_real AS
    SELECT * FROM mart.sales_mart WHERE data_kind = 'real';

CREATE VIEW mart.inventory_mart_real AS
    SELECT * FROM mart.inventory_mart WHERE data_kind = 'real';

-- Principal x month totals. Only rows that count in the principal's total (Del Monte's
-- product split re-divides the same sell-out pesos and would count them twice).
CREATE VIEW mart.sales_month AS
    SELECT principal, period, data_kind,
           SUM(pesos) AS pesos, SUM(pieces) AS pieces,
           COUNT(DISTINCT product_key) AS products,
           bool_and(pieces_unit_confirmed) AS pieces_unit_confirmed,
           bool_or(pesos_basis = 'vat_inclusive_recorded_with_tax') AS any_recorded_with_tax,
           bool_or(preview_placeholder) AS preview_placeholder,
           SUM(source_rows) AS source_rows
    FROM mart.sales_mart
    WHERE in_principal_total
    GROUP BY principal, period, data_kind;

CREATE VIEW mart.sales_category_month AS
    SELECT principal, COALESCE(category_path, 'UNCLASSIFIED') AS category_path, period, data_kind,
           SUM(pesos) AS pesos, SUM(pieces) AS pieces, COUNT(DISTINCT product_key) AS products
    FROM mart.sales_mart
    WHERE in_principal_total
    GROUP BY principal, COALESCE(category_path, 'UNCLASSIFIED'), period, data_kind;

CREATE VIEW mart.inventory_count AS
    SELECT principal, period, data_kind,
           MIN(count_date) AS first_count_date, MAX(count_date) AS count_date,
           CASE WHEN principal <> 'unilever'
                THEN 'count date not loaded (DEC-12): the stored date is a 1st-of-month placeholder' END AS count_date_note,
           'last_purchase_price' AS pesos_basis,
           SUM(pesos) AS pesos, SUM(pieces) AS pieces, SUM(cases) AS cases,
           COUNT(*) AS products,
           COUNT(*) FILTER (WHERE pieces_flag = 'no_pack_size') AS products_no_pack_size,
           SUM(source_rows) AS source_rows
    FROM mart.inventory_mart
    GROUP BY principal, period, data_kind;

CREATE VIEW mart.accuracy_category_month AS
    SELECT run_id, forecast_source, run_label, principal, COALESCE(category_path, 'UNCLASSIFIED') AS category_path,
           month, COUNT(*) AS products,
           SUM(forecast_pieces) AS forecast_pieces, SUM(actual_pieces) AS actual_pieces,
           SUM(miss_pieces) AS net_miss_pieces, SUM(abs_miss_pieces) AS abs_miss_pieces,
           SUM(surplus_pesos) AS surplus_pesos, SUM(shortage_pesos) AS shortage_pesos,
           SUM(abs_miss_pesos) AS abs_miss_pesos, SUM(miss_pesos) AS net_miss_pesos,
           COUNT(*) FILTER (WHERE price_per_piece IS NULL) AS products_without_price
    FROM mart.accuracy_mart
    WHERE actual_pieces IS NOT NULL
    GROUP BY run_id, forecast_source, run_label, principal, COALESCE(category_path, 'UNCLASSIFIED'), month;

CREATE VIEW mart.accuracy_total_month AS
    SELECT run_id, forecast_source, run_label, principal, month, COUNT(*) AS products,
           SUM(forecast_pieces) AS forecast_pieces, SUM(actual_pieces) AS actual_pieces,
           SUM(miss_pieces) AS net_miss_pieces, SUM(abs_miss_pieces) AS abs_miss_pieces,
           SUM(surplus_pesos) AS surplus_pesos, SUM(shortage_pesos) AS shortage_pesos,
           SUM(abs_miss_pesos) AS abs_miss_pesos, SUM(miss_pesos) AS net_miss_pesos,
           COUNT(*) FILTER (WHERE price_per_piece IS NULL) AS products_without_price
    FROM mart.accuracy_mart
    WHERE actual_pieces IS NOT NULL
    GROUP BY run_id, forecast_source, run_label, principal, month;

-- Whether a source changed after the last refresh (the dashboard says so instead of
-- serving stale sums silently).
CREATE VIEW mart.refresh_status AS
    SELECT r.refreshed_at, r.trigger,
           src.latest_load, src.latest_fill, src.latest_forecast, src.latest_lp_run,
           (r.refreshed_at IS NULL
            OR GREATEST(src.latest_load, src.latest_fill, src.latest_forecast, src.latest_lp_run) > r.refreshed_at) AS stale
    FROM (SELECT 1) one
    LEFT JOIN LATERAL (SELECT refreshed_at, trigger FROM mart.refresh_log ORDER BY refresh_id DESC LIMIT 1) r ON true
    CROSS JOIN LATERAL (
        SELECT (SELECT MAX(finished_at) FROM etl_load_event
                WHERE NOT dry_run
                  AND COALESCE(real_rows_added, 0) + COALESCE(real_rows_removed, 0)
                      + COALESCE(fill_rows_added, 0) + COALESCE(fill_rows_removed, 0) > 0) AS latest_load,
               GREATEST((SELECT MAX(computed_at) FROM derived_receipt_fact), (SELECT MAX(computed_at) FROM sku_demand_fill)) AS latest_fill,
               (SELECT MAX(generated_at) FROM forecast_result) AS latest_forecast,
               (SELECT MAX(created_at) FROM lp_run) AS latest_lp_run
    ) src;

-- ---------------------------------------------------------------------------
-- Forecast history capture
-- ---------------------------------------------------------------------------

-- One stored_run per forecast_result state, keyed by its newest generated_at: calling it
-- twice for the same forecasts returns the same run_id and writes nothing.
CREATE OR REPLACE FUNCTION mart.capture_forecast_result(p_code_version text DEFAULT NULL, p_created_by text DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql SET search_path = mart, public AS $$
DECLARE
    v_generated timestamptz;
    v_run bigint;
BEGIN
    SELECT MAX(generated_at) INTO v_generated FROM forecast_result;
    IF v_generated IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT run_id INTO v_run FROM mart.forecast_run WHERE kind = 'stored_run' AND source_generated_at = v_generated;
    IF v_run IS NOT NULL THEN
        RETURN v_run;
    END IF;
    INSERT INTO mart.forecast_run (kind, label, cohort, window_start, window_end, source_generated_at,
                                   code_version, created_by, notes)
    SELECT 'stored_run', 'forecast_result generated ' || to_char(v_generated AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || ' UTC',
           'every product in forecast_result',
           to_char(MIN(forecast_date), 'YYYY-MM'), to_char(MAX(forecast_date), 'YYYY-MM'), v_generated,
           p_code_version, p_created_by,
           jsonb_build_object('rows', COUNT(*), 'generated_at_values', COUNT(DISTINCT generated_at))
    FROM forecast_result
    RETURNING run_id INTO v_run;
    INSERT INTO mart.forecast_run_value (run_id, product_key, month, forecast_pieces, confidence_lower,
                                         confidence_upper, status, method, bin, ma3_pieces, mase, backup_fired)
    SELECT v_run, product_key, to_char(forecast_date, 'YYYY-MM'), forecast_value, confidence_lower,
           confidence_upper, status, model_params ->> 'method', model_params ->> 'bin',
           NULLIF(model_params ->> 'ma3_value', '')::numeric, mase,
           NULLIF(model_params ->> 'backup_fired', '')::boolean
    FROM forecast_result;
    RETURN v_run;
END
$$;

-- ---------------------------------------------------------------------------
-- refresh(): rebuild every derived mart in one transaction
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION mart.refresh(
    p_trigger text DEFAULT 'manual',
    p_idle_months integer DEFAULT 6,
    p_partial_counts text[] DEFAULT ARRAY['2025-05']
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

    INSERT INTO mart.accuracy_mart
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
    stock AS (
        -- Missing from a count that was taken = 0 on hand (Unilever files omit zero rows,
        -- backend/stock_status.py), except a count on record as possibly partial.
        SELECT v.*,
               CASE WHEN NOT opening_counted THEN NULL WHEN opening_listed THEN opening_row_pieces
                    WHEN opening_period = ANY(p_partial_counts) THEN NULL ELSE 0 END AS opening_pieces,
               CASE WHEN NOT closing_counted THEN NULL WHEN closing_listed THEN closing_row_pieces
                    WHEN month = ANY(p_partial_counts) THEN NULL ELSE 0 END AS closing_pieces,
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
    SELECT s.run_id, s.kind, s.label, s.cohort, COALESCE(s.principal, 'unilever'), s.product_key,
           s.category_path, s.month,
           s.forecast_pieces, s.actual_pieces, s.ma3_pieces, s.miss_pieces, abs(s.miss_pieces), s.direction,
           rl.run_length, p.price_per_piece,
           s.miss_pieces * p.price_per_piece, abs(s.miss_pieces) * p.price_per_piece,
           GREATEST(s.miss_pieces, 0) * p.price_per_piece, GREATEST(-s.miss_pieces, 0) * p.price_per_piece,
           s.opening_period, s.opening_pieces, s.closing_pieces,
           CASE WHEN s.direction IS NULL THEN NULL
                WHEN s.direction <> 'over' THEN false
                WHEN s.opening_pieces = 0 OR s.closing_pieces = 0 THEN true
                WHEN s.opening_pieces IS NULL OR s.closing_pieces IS NULL THEN NULL
                ELSE false END,
           s.method, s.bin, s.status
    FROM stock s
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
            jsonb_build_object('idle_months', p_idle_months, 'partial_counts', to_jsonb(p_partial_counts)));
    RETURN v_counts;
END
$$;

-- Seed: today's forecast_result becomes stored run 1, then the first build.
SELECT mart.capture_forecast_result(NULL, 'migration 0041');
SELECT mart.refresh('migration 0041');
