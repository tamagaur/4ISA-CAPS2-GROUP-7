-- analytics/db/migrations/0035_user_two_factor.sql
--
-- Numbered 0035 after 0034_user_permissions.sql. Kelvin's 0032 and 0033 are
-- still pending on public, so this file is applied on its own (one file,
-- one transaction, plus its schema_migrations row), not through a runner
-- pass that would also apply his.
--
-- Two-step sign-in with an authenticator app (backend/mfa.py,
-- reports/TWO_FACTOR_SIGN_IN_2026-10-02.md):
--
-- user_mfa: at most one row per user.
--   secret_encrypted  the authenticator secret, encrypted with the server's
--                     MFA_ENCRYPTION_KEY (Fernet), so reading this table
--                     alone can't produce a code.
--   enabled_at        NULL while setup is started but not yet confirmed with
--                     a first code; sign-in asks for a code only once set.
--   last_used_step    the 30-second step of the last code accepted, so the
--                     same code can't be used twice.
--   recovery_hashes   sha256 of each unused one-time recovery code. A used
--                     code is removed from the array.
-- The row goes with its user (ON DELETE CASCADE). Row-level security on and
-- no grants to the API roles, like every public table since
-- scripts/sql/2026-09-28_lock_down_data_api.sql.
--
-- Additive only: no existing row is changed or deleted, and nothing in the
-- warehouse (facts, dimensions, ABC, forecasts, LP) is touched. Until this
-- is applied the backend signs everyone in with a password alone, as now
-- (backend/mfa.py, BEFORE MIGRATION 0035 IS APPLIED). Names are
-- unqualified, like 0031 and 0034. Safe to run twice.

BEGIN;

CREATE TABLE IF NOT EXISTS user_mfa (
    user_id           BIGINT PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
    secret_encrypted  TEXT NOT NULL,
    enabled_at        TIMESTAMPTZ,
    last_used_step    BIGINT,
    recovery_hashes   TEXT[] NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE user_mfa ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE user_mfa IS
    'Authenticator-app two-step sign-in (backend/mfa.py). enabled_at NULL = setup not confirmed yet.';

COMMIT;

-- Rollback (not run, kept for review). Everyone goes back to password-only
-- sign-in; restart the backend afterwards, since it remembers "0035 is
-- applied" until then.
-- BEGIN;
-- DROP TABLE IF EXISTS user_mfa;
-- COMMIT;
