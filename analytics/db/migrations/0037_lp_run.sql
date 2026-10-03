-- analytics/db/migrations/0037_lp_run.sql
--
-- NOT APPLIED. Written 2026-09-30 on feat/params-consolidation (item 8 of the
-- parameter consolidation). Applying it to public is Yuan's cutover call.
-- Numbered 0035: 0034 is reserved for Audrey's permissions migration, 0036
-- for security, 0037+ for format resilience.
--
-- What each LP run actually used. LP_Recommendation keeps only q_i / rop_i /
-- ss_i per product, so every screen describing the LP showed the current
-- defaults (backend/lp_cycle.lp_model_info), and a run with non-default
-- flags was invisible to the app (scripts/run_lp.py warned as much).
--
-- lp_run: one row per planning cycle a real (non --dry-run) run solves.
--   inputs  every run_lp.py flag's value as run: the keys of
--           analytics.params.PLACEHOLDERS (allocation %, review / lead days,
--           target weeks, cover rule, warehouse capacity, the two costs).
--   model   what the run fixed in code: the objective weights, Z and service
--           level, the MASE gate, the allocation basis year / unit / monthly
--           ceilings, and the safety-stock assumption text.
--   code_version  the git commit the run came from, when it could be read.
-- lp_recommendation.lp_run_key: the run whose numbers the row holds. A rerun
-- refreshes only pending rows, so an accepted or dismissed row keeps the key
-- of the run it was decided on.
--
-- scripts/run_lp.py refuses a real run while lp_run is missing (a dry run
-- only warns), and backend/lp_cycle.stored_run falls back to the defaults,
-- labelled inputs_source = 'defaults', until it exists.
--
-- Names are unqualified on purpose: run in the SQL Editor they land in
-- public; run by scripts/run_canonical_load.py they land in its scratch
-- schema, like every other migration. Row-level security on and no grants
-- to the API roles, like every public table since
-- scripts/sql/2026-09-28_lock_down_data_api.sql. Safe to run twice.

BEGIN;

CREATE TABLE IF NOT EXISTS lp_run (
    run_key              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    planning_cycle_date  DATE NOT NULL,
    principal_scope      TEXT NOT NULL CHECK (principal_scope IN ('both', 'unilever', 'delmonte')),
    inputs               JSONB NOT NULL,
    model                JSONB NOT NULL,
    code_version         TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_lp_run_cycle ON lp_run (planning_cycle_date, created_at DESC);

ALTER TABLE lp_recommendation
    ADD COLUMN IF NOT EXISTS lp_run_key BIGINT REFERENCES lp_run (run_key);

ALTER TABLE lp_run ENABLE ROW LEVEL SECURITY;

COMMIT;
