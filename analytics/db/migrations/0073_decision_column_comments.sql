-- 0073_decision_column_comments.sql - correct two column comments migration 0062 left on the live columns, 2026-11-03.
--
-- 0062 says of lp_recommendation.decided_q_i and decision_reason "Capture only: nothing reads it". That stopped being
-- true: an accepted row's COALESCE(decided_q_i, q_i) becomes an expected receipt (backend/expected_receipts.py) and so
-- part of the next cycle's opening stock (stock_opening_v), which the optimisation reads. decision_reason is shown on
-- GET /recommendations and enters no computation. Neither reaches the forecast or the safety stock
-- (tests/backend/test_recommendation_decisions.py). An applied migration is not edited, so this one replaces the text.
--
-- COMMENT ON only. Expected on apply: 0 rows written, no schema change other than the two comments.
--
-- Rollback: put back the two COMMENT ON statements at the end of 0062, then
--           DELETE FROM schema_migrations WHERE filename = '0073_decision_column_comments.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)

COMMENT ON COLUMN lp_recommendation.decided_q_i IS
    'Quantity the planner decided to order when it differs from q_i. NULL = no override. On an accepted row, this else q_i becomes an expected receipt and so part of the next cycle opening stock, which the optimisation reads. The forecast and the safety stock never read it.';
COMMENT ON COLUMN lp_recommendation.decision_reason IS
    'Why the planner dismissed (required) or overrode the quantity (optional). Shown on GET /recommendations. Enters no computation.';
