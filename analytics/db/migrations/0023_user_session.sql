-- analytics/db/migrations/0023_user_session.sql
--
-- Adds user_session: one row per sign-in, backing the Audit Log page's
-- per-user summary (GET /audit-log/users) — how many times each user signed
-- in, and their longest single session.
--
-- Why a table and not audit_log: audit_log only ever received a 'Login' row,
-- posted by the browser. No 'Logout' row exists (people close the tab), so a
-- session's end — and therefore its length — was never recorded anywhere.
-- backend/routers/auth.py now writes these rows itself:
--   POST /auth/login      inserts the row, and its session_id goes in the JWT
--   POST /auth/heartbeat  (every 60s while the app is visible) moves last_seen_at
--   POST /auth/logout     sets ended_at
-- A session with no activity for 30 minutes is closed as 'idle' at its last
-- activity, so a tab left open overnight is not counted as one long session.
--
-- Session length = COALESCE(ended_at, last_seen_at) - started_at.
--
-- Backfill: every existing audit_log 'Login' row becomes a session with
-- source 'audit_log_backfill' and NULL last_seen_at, so login counts include
-- history while no length is invented for sign-ins nobody measured.
--
-- No foreign key to users on purpose, same as audit_log: deleting a user
-- must not delete their sign-in history. user_email/user_name/role are the
-- values at sign-in time.

BEGIN;

CREATE TABLE IF NOT EXISTS user_session (
    session_key   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id    TEXT NOT NULL UNIQUE,
    user_id       BIGINT,
    user_email    TEXT NOT NULL,
    user_name     TEXT,
    role          TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ,
    ended_at      TIMESTAMPTZ,
    end_reason    TEXT CHECK (end_reason IN ('logout', 'idle')),
    source        TEXT NOT NULL DEFAULT 'tracked' CHECK (source IN ('tracked', 'audit_log_backfill'))
);

CREATE INDEX IF NOT EXISTS ix_user_session_user_email ON user_session (user_email);

INSERT INTO user_session (session_id, user_id, user_email, user_name, role, started_at, source)
SELECT 'audit_log:' || a.audit_log_key, u.user_id, a.user_email, a.user_name, a.role, a.created_at, 'audit_log_backfill'
FROM audit_log a
LEFT JOIN users u ON u.email = a.user_email
WHERE a.action = 'Login'
ON CONFLICT (session_id) DO NOTHING;

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DROP INDEX IF EXISTS ix_user_session_user_email;
-- DROP TABLE IF EXISTS user_session;
-- COMMIT;
