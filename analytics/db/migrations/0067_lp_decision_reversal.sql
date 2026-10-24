-- 0067_lp_decision_reversal.sql - let an admin reverse an accepted or dismissed reorder decision, and keep it.
--
-- Until now a decision was final (backend/routers/recommendations.py, THE STATE MACHINE): a mis-click on Accept or
-- Dismiss had no way back, which also made the demonstration one-shot. POST /recommendations/{key}/reverse (admin
-- only) returns the row to pending. The decision it undoes is NOT deleted: this table keeps a copy of everything the
-- row held (the status, the quantity decided, the reason, who decided and when) next to who reversed it, when, and why.
-- lp_recommendation itself is reset to the pending shape (status pending and decided_at, decided_by, decided_q_i,
-- decision_reason all NULL), which ck_lp_decision_shape (0062) already allows. q_i, rop_i and ss_i are never touched.
--
-- One row per reversal. A row decided, reversed and decided again has one reversal row for each reversal.
-- Nothing in forecasting, safety stock, target stock or the LP reads this table.
--
-- Additive only. Expected on apply: 0 rows written, no existing row changed.
-- Until it is applied the endpoint answers 503 reversal_not_ready and nothing else changes.
--
-- Rollback: DROP TABLE IF EXISTS lp_decision_reversal.
--           DELETE FROM schema_migrations WHERE filename = '0067_lp_decision_reversal.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)

CREATE TABLE IF NOT EXISTS lp_decision_reversal (
    reversal_key        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recommendation_key  BIGINT NOT NULL REFERENCES lp_recommendation (recommendation_key),
    -- the decision that was undone, as the row held it
    prior_status        TEXT NOT NULL CHECK (prior_status IN ('accepted', 'dismissed')),
    prior_decided_q_i   NUMERIC(14,2),
    prior_reason        TEXT,
    prior_decided_by    TEXT,
    prior_decided_at    TIMESTAMPTZ,
    q_i                 NUMERIC(14,2) NOT NULL,
    -- the reversal
    reversed_by         TEXT NOT NULL,
    reversed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    reversal_reason     TEXT NOT NULL CHECK (length(btrim(reversal_reason)) > 0)
);

CREATE INDEX IF NOT EXISTS ix_lp_decision_reversal_rec ON lp_decision_reversal (recommendation_key, reversed_at);

ALTER TABLE lp_decision_reversal ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE lp_decision_reversal IS
    'One row per admin reversal of an accepted or dismissed reorder decision: the decision as it stood, who reversed it, when and why. The decision is kept here, not deleted.';
