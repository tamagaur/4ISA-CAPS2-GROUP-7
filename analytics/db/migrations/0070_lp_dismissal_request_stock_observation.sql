-- 0070_lp_dismissal_request_stock_observation.sql - a staff member asks for a dismissal, and reports stock counted.
--
-- 0068 held a planner's QUANTITY edit for an admin. This migration does the same for a DISMISSAL, and adds a place
-- to keep the stock someone says they counted on the shelf, without touching the stock the plan is made from.
--
-- lp_dismissal_request: one row per request to dismiss a recommendation, never deleted.
--   (staff with lp.propose asks)               --> pending_approval
--   pending_approval --approve (admin)--> approved   and the recommendation becomes dismissed (the ordinary dismiss)
--   pending_approval --reject  (admin)--> rejected   and the recommendation stays pending, active
--   recommended_q_i   q_i when the request was made. Approval is refused if q_i has moved since (an LP rerun).
-- At most one dismissal request per recommendation can be pending_approval (the partial unique index). The backend
-- also refuses a dismissal request while a quantity change is open on the row, and the other way round, under a
-- row lock (backend/routers/reorder_requests.py).
--
-- lp_stock_observation: stock someone REPORTS counting. It is an observation, not the stock on hand.
--   Inventory_Fact (the SSM stock-on-hand file) stays the only stock the order plan reads. Nothing in forecasting,
--   safety stock, target stock, the LP or the dashboards reads this table. Verifying an observation records that an
--   admin checked it, and nothing more: turning a verified count into stock on hand would be a new Inventory_Fact
--   load, which is a pipeline decision (Yuan) and is not made here.
--   quantity_entered + unit_entered    what was typed, in pieces or cases
--   pieces_per_case                    Product_Dimension.pack_size used for a cases entry (NULL for pieces)
--   quantity_pieces                    the same amount in pieces, the plan's unit (checked by ck_lp_stock_obs_pieces)
--   context                            which action it came with: a quantity change, a dismissal request, or an
--                                      direct dismissal (an admin, or a user with lp.decide)
--
-- Additive only. Expected on apply: 0 rows written, no existing row changed.
-- Until it is applied the new endpoints answer 503 requests_not_ready and nothing else changes.
--
-- Rollback: DROP TABLE IF EXISTS lp_stock_observation, lp_dismissal_request.
--           DELETE FROM schema_migrations WHERE filename = '0070_lp_dismissal_request_stock_observation.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)

CREATE TABLE IF NOT EXISTS lp_dismissal_request (
    request_key         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recommendation_key  BIGINT NOT NULL REFERENCES lp_recommendation (recommendation_key),
    recommended_q_i     NUMERIC(14,2) NOT NULL,
    request_reason      TEXT NOT NULL CHECK (length(btrim(request_reason)) > 0),
    requested_by        TEXT NOT NULL,
    requested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    state               TEXT NOT NULL DEFAULT 'pending_approval'
                            CHECK (state IN ('pending_approval', 'approved', 'rejected')),
    resolved_by         TEXT,
    resolved_at         TIMESTAMPTZ,
    resolution_note     TEXT,
    CONSTRAINT ck_lp_dismissal_request_resolved CHECK (
        (state = 'pending_approval' AND resolved_by IS NULL AND resolved_at IS NULL)
        OR (state <> 'pending_approval' AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL)),
    CONSTRAINT ck_lp_dismissal_request_rejection_note CHECK (
        state <> 'rejected' OR length(btrim(COALESCE(resolution_note, ''))) > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_lp_dismissal_request_one_open
    ON lp_dismissal_request (recommendation_key) WHERE state = 'pending_approval';
CREATE INDEX IF NOT EXISTS ix_lp_dismissal_request_state ON lp_dismissal_request (state, requested_at);

CREATE TABLE IF NOT EXISTS lp_stock_observation (
    observation_key        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_key            BIGINT NOT NULL REFERENCES product_dimension (product_key),
    recommendation_key     BIGINT REFERENCES lp_recommendation (recommendation_key),
    quantity_entered       NUMERIC(14,2) NOT NULL CHECK (quantity_entered >= 0),
    unit_entered           TEXT NOT NULL CHECK (unit_entered IN ('pieces', 'cases')),
    pieces_per_case        NUMERIC(14,4),
    quantity_pieces        NUMERIC(14,2) NOT NULL CHECK (quantity_pieces >= 0),
    counted_at             TIMESTAMPTZ,
    location               TEXT,
    notes                  TEXT,
    context                TEXT NOT NULL CHECK (context IN ('quantity_change', 'dismissal_request', 'direct_dismissal')),
    quantity_change_key    BIGINT REFERENCES lp_quantity_change (change_key),
    dismissal_request_key  BIGINT REFERENCES lp_dismissal_request (request_key),
    reported_by            TEXT NOT NULL,
    reporter_role          TEXT,
    reported_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    verification_state     TEXT NOT NULL DEFAULT 'unverified'
                               CHECK (verification_state IN ('unverified', 'verified', 'rejected')),
    verified_by            TEXT,
    verified_at            TIMESTAMPTZ,
    verification_note      TEXT,
    CONSTRAINT ck_lp_stock_obs_pieces CHECK (
        (unit_entered = 'pieces' AND pieces_per_case IS NULL AND quantity_pieces = quantity_entered)
        OR (unit_entered = 'cases' AND pieces_per_case > 0
            AND quantity_pieces = ROUND(quantity_entered * pieces_per_case, 2))),
    CONSTRAINT ck_lp_stock_obs_verified CHECK (
        (verification_state = 'unverified' AND verified_by IS NULL AND verified_at IS NULL)
        OR (verification_state <> 'unverified' AND verified_by IS NOT NULL AND verified_at IS NOT NULL)),
    CONSTRAINT ck_lp_stock_obs_context CHECK (
        (context = 'quantity_change' AND quantity_change_key IS NOT NULL AND dismissal_request_key IS NULL)
        OR (context = 'dismissal_request' AND dismissal_request_key IS NOT NULL AND quantity_change_key IS NULL)
        OR (context = 'direct_dismissal' AND quantity_change_key IS NULL AND dismissal_request_key IS NULL))
);

CREATE INDEX IF NOT EXISTS ix_lp_stock_observation_rec ON lp_stock_observation (recommendation_key, reported_at);
CREATE INDEX IF NOT EXISTS ix_lp_stock_observation_product ON lp_stock_observation (product_key, reported_at);

ALTER TABLE lp_dismissal_request ENABLE ROW LEVEL SECURITY;
ALTER TABLE lp_stock_observation ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE lp_dismissal_request IS
    'A staff request to dismiss a reorder recommendation, held until an admin approves (the ordinary dismiss) or rejects it (the recommendation stays active). Never deleted.';
COMMENT ON TABLE lp_stock_observation IS
    'Stock someone reports counting, with who, when, where and the unit typed. An observation only: Inventory_Fact stays the stock on hand, and nothing in forecasting, safety stock or the LP reads this table.';
