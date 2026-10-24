-- 0069_rollover_ledger.sql - the receipt ledger, the cycle record and the opening-stock view (docs/ROLLOVER_DESIGN.md).
--
-- An accepted order fed nothing: run_lp read stock only from the count that opens the cycle, so the planning
-- period could not advance. This adds the pieces the approved design needs, and nothing reads them yet.
--
--   expected_receipt   one row per accepted order line: pieces = the accepted quantity (decided_q_i, else q_i),
--                      expected_on = the decision date + the product's lead time. States: expected,
--                      arrived_in_count (a count dated on or after expected_on exists, the pieces are inside it and
--                      are never added again), confirmed (a person said so, optional), cancelled (the decision was
--                      reversed or dismissed). not_visible_in_count marks a receipt settled by a count in which the
--                      product's stock did not rise: recorded, never corrected. One live (not cancelled) receipt per
--                      recommendation, which a changed quantity updates in place (revision_count).
--   planning_cycle     one row per principal and planning month: open, closing, closed, how the opening stock was
--                      obtained (count or projected), which steps of the close are done, who closed and reopened it.
--   lp_recommendation.closed_at   set when a cycle closes. The row is kept as it was, its status unchanged. Reopening
--                      puts it back to NULL.
--   stock_opening_v    per Unilever product and planning month: the count that opens the month, plus expected receipts
--                      still on the way, or - when that count is not loaded yet - the month before's count plus its
--                      receipts minus that month's sales (actual if loaded, else the stored forecast), labelled
--                      opening_basis = projected. A product with no row in a count that was taken has 0 on hand (the
--                      file omits zero rows) and a product whose stock is in cases with no usable pack size is NULL,
--                      the same two rules run_lp applies today. Receipts counted are those of EARLIER cycles only, so a
--                      cycle's own accepted orders never change that cycle's plan.
--
-- Additive only. Expected on apply: 3 new objects with 0 rows, 1 new nullable column, 1 view. With nothing decided
-- the view equals what run_lp reads today and the plan is unchanged. Del Monte has no per-product plan and is not in
-- the view. Receipt rows are written only by the decision endpoints, in the decision's own transaction.
--
-- Rollback: DROP VIEW IF EXISTS stock_opening_v. DROP TABLE IF EXISTS planning_cycle, expected_receipt.
--           ALTER TABLE lp_recommendation DROP COLUMN IF EXISTS closed_at.
--           DELETE FROM schema_migrations WHERE filename = '0069_rollover_ledger.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)

CREATE TABLE IF NOT EXISTS expected_receipt (
    receipt_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recommendation_key    BIGINT NOT NULL REFERENCES lp_recommendation (recommendation_key),
    product_key           BIGINT NOT NULL REFERENCES product_dimension (product_key),
    sku_code              TEXT,
    pieces                NUMERIC(14,2) NOT NULL CHECK (pieces >= 0),
    ordered_at            TIMESTAMPTZ NOT NULL,
    lead_days_used        NUMERIC(6,2) NOT NULL CHECK (lead_days_used >= 0),
    lead_time_source      TEXT NOT NULL CHECK (lead_time_source IN ('product', 'placeholder')),
    expected_on           DATE NOT NULL,
    state                 TEXT NOT NULL DEFAULT 'expected'
                              CHECK (state IN ('expected', 'arrived_in_count', 'confirmed', 'cancelled')),
    not_visible_in_count  BOOLEAN NOT NULL DEFAULT false,
    stock_change_pieces   NUMERIC,
    settled_by_period     TEXT CHECK (settled_by_period IS NULL OR settled_by_period ~ '^[0-9]{4}-[0-9]{2}$'),
    settled_by_count_date DATE,
    settled_at            TIMESTAMPTZ,
    confirmed_by          TEXT,
    voided_by_decision    TEXT CHECK (voided_by_decision IS NULL OR voided_by_decision IN ('dismissed', 'reversed')),
    voided_at             TIMESTAMPTZ,
    revision_count        INTEGER NOT NULL DEFAULT 0,
    revised_at            TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_expected_receipt_settled CHECK (
        (state IN ('arrived_in_count', 'confirmed') AND settled_at IS NOT NULL)
        OR (state NOT IN ('arrived_in_count', 'confirmed') AND settled_at IS NULL)),
    CONSTRAINT ck_expected_receipt_counted CHECK (
        state <> 'arrived_in_count' OR (settled_by_period IS NOT NULL AND settled_by_count_date IS NOT NULL)),
    CONSTRAINT ck_expected_receipt_cancelled CHECK (
        (state = 'cancelled' AND voided_by_decision IS NOT NULL AND voided_at IS NOT NULL)
        OR (state <> 'cancelled' AND voided_by_decision IS NULL AND voided_at IS NULL)),
    CONSTRAINT ck_expected_receipt_not_visible CHECK (not_visible_in_count = false OR state = 'arrived_in_count')
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_expected_receipt_one_live
    ON expected_receipt (recommendation_key) WHERE state <> 'cancelled';
CREATE INDEX IF NOT EXISTS ix_expected_receipt_open
    ON expected_receipt (product_key, expected_on) WHERE state = 'expected';
CREATE INDEX IF NOT EXISTS ix_expected_receipt_not_visible
    ON expected_receipt (settled_by_period) WHERE not_visible_in_count;

CREATE TABLE IF NOT EXISTS planning_cycle (
    principal             TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    cycle                 DATE NOT NULL,
    state                 TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'closing', 'closed')),
    opening_basis         TEXT CHECK (opening_basis IS NULL OR opening_basis IN ('count', 'projected')),
    opening_count_period  TEXT,
    opening_count_date    DATE,
    forecast_run_id       BIGINT,
    lp_run_key            BIGINT REFERENCES lp_run (run_key),
    steps_done            TEXT[] NOT NULL DEFAULT '{}',
    closing_started_by    TEXT,
    closing_started_at    TIMESTAMPTZ,
    closed_by             TEXT,
    closed_at             TIMESTAMPTZ,
    reopened_by           TEXT,
    reopened_at           TIMESTAMPTZ,
    reopen_count          INTEGER NOT NULL DEFAULT 0,
    note                  TEXT,
    PRIMARY KEY (principal, cycle),
    CONSTRAINT ck_planning_cycle_first_of_month CHECK (EXTRACT(DAY FROM cycle) = 1),
    CONSTRAINT ck_planning_cycle_closed CHECK (state <> 'closed' OR (closed_by IS NOT NULL AND closed_at IS NOT NULL))
);

ALTER TABLE lp_recommendation ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;

ALTER TABLE expected_receipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE planning_cycle ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE VIEW stock_opening_v WITH (security_invoker = true) AS
WITH counts AS (
    SELECT inv.principal, inv._period AS period, MAX(inv.snapshot_date) AS count_date
    FROM inventory_fact_real inv
    WHERE inv.principal = 'unilever' AND inv._period ~ '^[0-9]{4}-[0-9]{2}$'
    GROUP BY inv.principal, inv._period
),
cyc AS (
    SELECT c.principal, (to_date(c.period || '-01', 'YYYY-MM-DD') + interval '1 month')::date AS cycle,
           'count'::text AS opening_basis, c.period AS count_period, c.count_date
    FROM counts c
    UNION ALL
    SELECT c.principal, (to_date(c.period || '-01', 'YYYY-MM-DD') + interval '2 month')::date,
           'projected'::text, c.period, c.count_date
    FROM counts c
    WHERE NOT EXISTS (SELECT 1 FROM counts n WHERE n.principal = c.principal
                      AND n.period = to_char(to_date(c.period || '-01', 'YYYY-MM-DD') + interval '1 month', 'YYYY-MM'))
),
stock AS (
    SELECT inv.principal, inv._period AS period, inv.product_key,
           CASE WHEN pd.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd.pack_size::numeric > 0
                THEN SUM(inv.quantity_on_hand) * pd.pack_size::numeric + COALESCE(SUM(inv.quantity_pieces), 0)
           END AS pieces
    FROM inventory_fact_real inv
    JOIN product_dimension pd ON pd.product_key = inv.product_key
    WHERE inv.principal = 'unilever' AND inv._period ~ '^[0-9]{4}-[0-9]{2}$'
    GROUP BY inv.principal, inv._period, inv.product_key, pd.pack_size
),
rc AS (
    SELECT c.principal, c.cycle, er.product_key, SUM(er.pieces) AS pieces, COUNT(*) AS receipts
    FROM cyc c
    JOIN expected_receipt er ON er.state = 'expected' AND er.expected_on > c.count_date
    JOIN lp_recommendation lr ON lr.recommendation_key = er.recommendation_key AND lr.planning_cycle_date < c.cycle
    JOIN product_dimension pd ON pd.product_key = er.product_key AND pd.principal = c.principal
    GROUP BY c.principal, c.cycle, er.product_key
),
keys AS (
    SELECT c.principal, c.cycle, c.opening_basis, c.count_period, c.count_date, s.product_key
    FROM cyc c JOIN stock s ON s.principal = c.principal AND s.period = c.count_period
    UNION
    SELECT c.principal, c.cycle, c.opening_basis, c.count_period, c.count_date, rc.product_key
    FROM cyc c JOIN rc ON rc.principal = c.principal AND rc.cycle = c.cycle
),
loaded AS (SELECT DISTINCT calendar_month FROM Unilever_SKU_Demand_Fact_Real),
sold AS (
    SELECT product_key, calendar_month, GREATEST(SUM(quantity_sold), 0) AS pieces
    FROM Unilever_SKU_Demand_Fact_Real GROUP BY product_key, calendar_month
),
fc AS (
    SELECT DISTINCT ON (product_key, forecast_date) product_key, forecast_date, forecast_value
    FROM forecast_result WHERE status = 'ok'
    ORDER BY product_key, forecast_date, generated_at DESC
),
joined AS (
    SELECT k.principal, k.product_key, k.cycle, k.opening_basis, k.count_period, k.count_date,
           (s.product_key IS NOT NULL) AS in_stock_file, s.pieces AS count_pieces,
           COALESCE(rc.pieces, 0) AS expected_receipt_pieces, COALESCE(rc.receipts, 0) AS expected_receipts,
           to_char((k.cycle - interval '1 month'), 'YYYY-MM') AS sales_month,
           CASE WHEN k.opening_basis = 'count' THEN NULL
                WHEN EXISTS (SELECT 1 FROM loaded l WHERE l.calendar_month = to_char((k.cycle - interval '1 month'), 'YYYY-MM')) THEN 'actual'
                WHEN f.product_key IS NOT NULL THEN 'forecast'
                ELSE 'none' END AS sales_basis,
           sd.pieces AS sold_pieces, f.forecast_value
    FROM keys k
    LEFT JOIN stock s ON s.principal = k.principal AND s.period = k.count_period AND s.product_key = k.product_key
    LEFT JOIN rc ON rc.principal = k.principal AND rc.cycle = k.cycle AND rc.product_key = k.product_key
    LEFT JOIN sold sd ON sd.product_key = k.product_key AND sd.calendar_month = to_char((k.cycle - interval '1 month'), 'YYYY-MM')
    LEFT JOIN fc f ON f.product_key = k.product_key AND f.forecast_date = (k.cycle - interval '1 month')::date
)
SELECT j.principal, j.product_key, j.cycle, j.opening_basis, j.count_period, j.count_date, j.in_stock_file,
       j.count_pieces, j.expected_receipt_pieces, j.expected_receipts, j.sales_basis,
       CASE j.sales_basis WHEN 'actual' THEN COALESCE(j.sold_pieces, 0) WHEN 'forecast' THEN j.forecast_value END
           AS projected_sales_pieces,
       CASE WHEN j.in_stock_file AND j.count_pieces IS NULL THEN NULL
            WHEN j.opening_basis = 'count' THEN GREATEST(COALESCE(j.count_pieces, 0) + j.expected_receipt_pieces, 0)
            WHEN j.sales_basis = 'none' THEN NULL
            ELSE GREATEST(COALESCE(j.count_pieces, 0) + j.expected_receipt_pieces
                          - CASE j.sales_basis WHEN 'actual' THEN COALESCE(j.sold_pieces, 0) ELSE j.forecast_value END, 0)
       END AS opening_pieces
FROM joined j;

COMMENT ON TABLE expected_receipt IS
    'Accepted order lines as stock that is on the way (0069). One live row per recommendation. Settled only by a stock count dated on or after expected_on, never by the lead time alone.';
COMMENT ON TABLE planning_cycle IS
    'One row per principal and planning month: open, closing, closed, with how its opening stock was obtained and which close steps are done (0069).';
COMMENT ON COLUMN lp_recommendation.closed_at IS
    'Set when the planning cycle is closed (0069). The row and its decision are kept unchanged. NULL = still part of an open cycle.';
COMMENT ON VIEW stock_opening_v IS
    'Opening stock per Unilever product and planning month (0069): the opening count plus expected receipts on the way, or a labelled projection when that count is not loaded. Receipts counted are those of earlier cycles only.';
