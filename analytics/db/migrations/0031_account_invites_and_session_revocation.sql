-- analytics/db/migrations/0031_account_invites_and_session_revocation.sql
--
-- Numbered 0031: written as 0028, then renumbered twice because kelvin-etl's
-- migrations reached the public ledger first (2026-09-28):
-- 0028_value_source_rmr_returns_dm_brand_rule.sql, then
-- 0029_product_dimension_supersedes_product_key.sql and
-- 0030_product_dimension_sku_code_format.sql. run_canonical_load.py refuses
-- two files with one number. This file was applied to public by hand in the
-- SQL Editor on 2026-09-28 under its first name, so the ledger has no row for
-- it; it is safe to run again (see the last paragraph below).
--
-- Backs the 2026-09-28 sign-in changes (Part D of the security review):
--
-- 1. Invites. An admin no longer types a password for a new account: the
--    account starts with password_hash NULL ("invite pending") and its owner
--    sets one through a one-time emailed link. So password_hash may be NULL.
--
-- 2. auth_token: one row per invite or password-reset link. Only the
--    sha256 of the link's token is stored, so reading this table gives no
--    usable link. used_at is set when the link is used or replaced by a
--    newer one; a link past expires_at is dead either way. Rows go with
--    their user (ON DELETE CASCADE). Row-level security on and no grants to
--    the API roles, like every public table since
--    scripts/sql/2026-09-28_lock_down_data_api.sql.
--
-- 3. user_session.end_reason gains 'revoked': a session ended by the server
--    because an admin changed the account's role or email or deleted it, or
--    its password was set or reset. The backend now checks the session on
--    every request (backend/deps.py), so ending it signs that browser out.
--
-- Names are unqualified on purpose: run in the SQL Editor they land in
-- public; run by scripts/run_canonical_load.py they land in its scratch
-- schema, like every other migration. Safe to run twice.

BEGIN;

ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;

CREATE TABLE IF NOT EXISTS auth_token (
    token_key   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token_hash  TEXT NOT NULL UNIQUE,
    user_id     BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    purpose     TEXT NOT NULL CHECK (purpose IN ('invite', 'reset')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_by  BIGINT
);

CREATE INDEX IF NOT EXISTS ix_auth_token_user_id ON auth_token (user_id);

ALTER TABLE auth_token ENABLE ROW LEVEL SECURITY;

ALTER TABLE user_session DROP CONSTRAINT IF EXISTS user_session_end_reason_check;
ALTER TABLE user_session ADD CONSTRAINT user_session_end_reason_check
    CHECK (end_reason IN ('logout', 'idle', 'revoked'));

COMMENT ON TABLE auth_token IS
    'One-time invite / password-reset links (backend/account_links.py). Stores only the sha256 of each token.';

COMMIT;

-- Rollback (not run, kept for review). Fails while any account is still
-- invite-pending (password_hash NULL) or any session ended as 'revoked';
-- delete or update those rows first.
-- BEGIN;
-- ALTER TABLE user_session DROP CONSTRAINT IF EXISTS user_session_end_reason_check;
-- ALTER TABLE user_session ADD CONSTRAINT user_session_end_reason_check
--     CHECK (end_reason IN ('logout', 'idle'));
-- DROP TABLE IF EXISTS auth_token;
-- ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL;
-- COMMIT;
