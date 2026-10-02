-- analytics/db/migrations/0034_user_permissions.sql
--
-- Numbered 0034 at Kelvin's request (his loader work uses 0032 and 0033).
-- Written on Audrey's branch; applied by Kelvin through the runner, not by
-- hand and not from Audrey's side.
--
-- Backs Yuan's permissions proposal (revised 2026-09-30), backend step 2,
-- plus one account per email. Two roles only, admin and staff: the
-- proposal's Manager role was dropped (Audrey, 2026-10-01), so users.role's
-- CHECK is left as it is:
--
-- 1. user_permission_override: one row per (user, permission) where that
--    user differs from their role's preset. granted = true adds the
--    permission, false removes it; a key equal to the preset is never
--    stored (backend/permissions.normalize). The catalog of keys lives in
--    code (backend/permissions.py), and PUT /admin/users/{id}/permissions
--    refuses a key it doesn't list (422 unknown_permission), so there is no
--    CHECK on permission_key here: a new permission needs no migration.
--    Rows go with their user (ON DELETE CASCADE); set_by survives the
--    deletion of whoever set it (SET NULL). Row-level security on and no
--    grants to the API roles, like every public table since
--    scripts/sql/2026-09-28_lock_down_data_api.sql and migration 0031.
--
-- 2. One account per email in any capitalisation: a unique index on
--    lower(email). The existing UNIQUE (email) only catches exact matches,
--    so Ana@x.com and ana@x.com could be two accounts. Checked read-only
--    on the live database first (2026-09-30): no two users share an email
--    in any case, so creating the index cannot fail on existing rows.
--
-- Additive only: no existing row is changed or deleted, and nothing in the
-- warehouse (facts, dimensions, ABC, forecasts, LP) is touched. Until this
-- is applied the backend behaves exactly as before (backend/permissions.py,
-- BEFORE MIGRATION 0034 IS APPLIED). Names are unqualified, like 0031.
-- Safe to run twice.

BEGIN;

CREATE TABLE IF NOT EXISTS user_permission_override (
    user_id         BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    permission_key  TEXT NOT NULL,
    granted         BOOLEAN NOT NULL,
    set_by          BIGINT REFERENCES users (user_id) ON DELETE SET NULL,
    set_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, permission_key)
);

ALTER TABLE user_permission_override ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE user_permission_override IS
    'Per-user permission exceptions to the role preset (backend/permissions.py). granted=true adds, false removes.';

CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_key ON users (lower(email));

COMMIT;

-- Rollback (not run, kept for review).
-- BEGIN;
-- DROP INDEX IF EXISTS users_email_lower_key;
-- DROP TABLE IF EXISTS user_permission_override;
-- COMMIT;
