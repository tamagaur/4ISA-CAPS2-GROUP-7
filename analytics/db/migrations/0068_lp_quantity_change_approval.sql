-- 0068_lp_quantity_change_approval.sql - a planner's edit to the recommended quantity is held for an admin.
--
-- Today a planner can accept a recommendation with a different quantity (decided_q_i, 0062) and it applies at once.
-- With this migration an edit to the quantity is a PROPOSED CHANGE: it is stored here in the state pending_approval,
-- the recommendation row stays pending and untouched, and an admin approves or rejects it. Approving makes the
-- ordinary accept: lp_recommendation gets status accepted, decided_q_i = the proposed quantity, decision_reason = the
-- proposal's reason, decided_by = the proposer, decided_at = the approval time. The approver, the time and the note
-- are kept on the change row and in the audit log. Rejecting leaves the recommendation pending and the change row
-- as the record. A change is never deleted.
--   recommended_q_i   q_i when the change was proposed. Approval is refused if q_i has moved since.
--   proposed_q_i      the quantity the planner wants. Never equal to recommended_q_i.
-- At most one change per recommendation can be pending_approval at a time (the partial unique index).
--
-- lp_direct_apply_grant lists the users an admin has allowed to apply a quantity change directly, with no approval.
-- An admin always can. Removing the row removes the permission. Who granted it and when is kept, and every grant and
-- revoke also goes to the audit log.
--
-- Additive only. Expected on apply: 0 rows written, no existing row changed. Until it is applied the backend behaves
-- as before (a quantity edit applies at once) and the new endpoints answer 503 approval_not_ready.
-- Nothing in forecasting, safety stock, target stock or the LP reads these tables.
--
-- Rollback: DROP TABLE IF EXISTS lp_quantity_change, lp_direct_apply_grant.
--           DELETE FROM schema_migrations WHERE filename = '0068_lp_quantity_change_approval.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)

CREATE TABLE IF NOT EXISTS lp_quantity_change (
    change_key          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recommendation_key  BIGINT NOT NULL REFERENCES lp_recommendation (recommendation_key),
    recommended_q_i     NUMERIC(14,2) NOT NULL,
    proposed_q_i        NUMERIC(14,2) NOT NULL CHECK (proposed_q_i >= 0),
    proposal_reason     TEXT,
    reviewed            BOOLEAN NOT NULL DEFAULT false,
    proposed_by         TEXT NOT NULL,
    proposed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    state               TEXT NOT NULL DEFAULT 'pending_approval'
                            CHECK (state IN ('pending_approval', 'approved', 'rejected')),
    resolved_by         TEXT,
    resolved_at         TIMESTAMPTZ,
    resolution_note     TEXT,
    CONSTRAINT ck_lp_quantity_change_differs CHECK (proposed_q_i <> recommended_q_i),
    CONSTRAINT ck_lp_quantity_change_resolved CHECK (
        (state = 'pending_approval' AND resolved_by IS NULL AND resolved_at IS NULL)
        OR (state <> 'pending_approval' AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL)),
    CONSTRAINT ck_lp_quantity_change_rejection_note CHECK (
        state <> 'rejected' OR length(btrim(COALESCE(resolution_note, ''))) > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_lp_quantity_change_one_open
    ON lp_quantity_change (recommendation_key) WHERE state = 'pending_approval';
CREATE INDEX IF NOT EXISTS ix_lp_quantity_change_state ON lp_quantity_change (state, proposed_at);

CREATE TABLE IF NOT EXISTS lp_direct_apply_grant (
    user_id     BIGINT PRIMARY KEY,
    granted_by  TEXT NOT NULL,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE lp_quantity_change ENABLE ROW LEVEL SECURITY;
ALTER TABLE lp_direct_apply_grant ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE lp_quantity_change IS
    'A planner''s proposed order quantity for a recommendation, held until an admin approves or rejects it. Never deleted. Approval makes the ordinary accept on lp_recommendation.';
COMMENT ON TABLE lp_direct_apply_grant IS
    'Users an admin allowed to apply a reorder quantity change without approval. Admins always can. Row present = allowed.';
