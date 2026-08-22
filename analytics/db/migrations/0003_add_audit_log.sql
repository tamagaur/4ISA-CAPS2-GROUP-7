-- analytics/db/migrations/0003_add_audit_log.sql
--
-- Adds Audit_Log, backing GET/POST /audit-log (backend/routers/audit_log.py)
-- and frontend/src/utils/auditLogger.js. Replaces the previous
-- localStorage-only audit log, which never left the reporting browser and
-- reset on cache clear — a real audit trail needs to survive that and be
-- visible across users.
--
-- NOT YET APPLIED to Supabase — run this by hand (Supabase SQL editor or
-- psql against SUPABASE_DB_URL) before deploying backend/routers/audit_log.py.
-- schema.sql's from-scratch definition has been updated to match.

BEGIN;

CREATE TABLE IF NOT EXISTS Audit_Log (
    audit_log_key   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_email      TEXT NOT NULL,
    user_name       TEXT,
    role            TEXT,
    action          TEXT NOT NULL,
    details         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON Audit_Log (created_at DESC);

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DROP INDEX IF EXISTS ix_audit_log_created_at;
-- DROP TABLE IF EXISTS Audit_Log;
-- COMMIT;
