-- 0062_lp_recommendation_decision_capture.sql - record what the planner decided, and why.
--
-- CAPTURE ONLY. A planner can accept or dismiss a recommendation. They could not record a different quantity,
-- and a dismissal kept no reason on the row (it went to the audit log text only). Two columns now hold both:
--   decided_q_i      the quantity the planner actually decided to order, ONLY when it differs from the
--                    recommendation. NULL means no override (accepted as recommended, dismissed, or pending).
--   decision_reason  why. Required on dismiss (enforced by the check below and by the API), optional on an
--                    accept with an overridden quantity.
-- Who decided and when already exist: decided_by and decided_at (schema.sql, LP_Recommendation).
-- q_i, rop_i and ss_i are NEVER written by a decision: the recommended quantity stays as the LP produced it,
-- so the gap between q_i and decided_q_i is something that can be measured later.
--
-- Nothing in forecasting, safety stock, target stock or the LP reads these columns. They feed no loop.
--
-- The dismiss-needs-a-reason check is NOT VALID: the rows already dismissed (none on 2026-10-21) are not
-- re-checked, every new decision is. The mart (mart.planning_mart) is untouched: GET /recommendations reads
-- these two columns from lp_recommendation for decided rows.
--
-- Expected on apply: 0 rows written. 289 lp_recommendation rows as of 2026-10-21 (288 pending, 1 accepted) keep
-- every value, and decided_q_i and decision_reason are NULL on all of them.
--
-- Rollback: ALTER TABLE lp_recommendation DROP CONSTRAINT IF EXISTS ck_lp_decided_q_i_nonneg, DROP CONSTRAINT IF EXISTS
--           ck_lp_decision_shape, DROP COLUMN IF EXISTS decided_q_i, DROP COLUMN IF EXISTS decision_reason.
--           DELETE FROM schema_migrations WHERE filename = '0062_lp_recommendation_decision_capture.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)

ALTER TABLE lp_recommendation
    ADD COLUMN IF NOT EXISTS decided_q_i NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS decision_reason TEXT;

ALTER TABLE lp_recommendation DROP CONSTRAINT IF EXISTS ck_lp_decided_q_i_nonneg;
ALTER TABLE lp_recommendation ADD CONSTRAINT ck_lp_decided_q_i_nonneg
    CHECK (decided_q_i IS NULL OR decided_q_i >= 0);

-- An overridden quantity belongs to an accepted row only, and a dismissal carries a non-blank reason.
ALTER TABLE lp_recommendation DROP CONSTRAINT IF EXISTS ck_lp_decision_shape;
ALTER TABLE lp_recommendation ADD CONSTRAINT ck_lp_decision_shape
    CHECK ((decided_q_i IS NULL OR status = 'accepted')
           AND (status <> 'dismissed' OR length(btrim(COALESCE(decision_reason, ''))) > 0)) NOT VALID;

COMMENT ON COLUMN lp_recommendation.decided_q_i IS
    'Quantity the planner decided to order when it differs from q_i. NULL = no override. Capture only: nothing reads it.';
COMMENT ON COLUMN lp_recommendation.decision_reason IS
    'Why the planner dismissed (required) or overrode the quantity (optional). Capture only: nothing reads it.';
