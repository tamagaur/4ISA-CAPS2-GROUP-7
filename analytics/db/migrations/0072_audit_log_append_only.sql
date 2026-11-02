-- 0072_audit_log_append_only.sql - the audit trail cannot be changed or emptied, 2026-11-02 (docs/DATA_GOVERNANCE.md, G3).
--
-- Until now app.audit_log was append-only by convention: the server only INSERTs (backend/audit.py), no code path
-- updates or deletes a row (checked 2026-11-02 across backend/, analytics/ and scripts/), and 0048 revoked the
-- table from anon, authenticated and service_role. The database itself still allowed a superuser or a bad script
-- to rewrite history. These triggers make UPDATE, DELETE and TRUNCATE on the table fail for everyone, whatever
-- role runs them.
--
-- Not covered, on purpose: DROP TABLE and ALTER TABLE (the migration runner needs them, and 0048 moved the table
-- with SET SCHEMA). A deliberate purge under the retention schedule (docs/DATA_GOVERNANCE.md section 5) is done by
-- disabling the trigger in a reviewed script, which leaves a trace in the SQL log:
--   ALTER TABLE app.audit_log DISABLE TRIGGER trg_audit_log_no_update_delete
--   ALTER TABLE app.audit_log DISABLE TRIGGER trg_audit_log_no_truncate
--
-- Additive only. Expected on apply: 0 rows written, no existing row changed. The INSERT path is untouched.
-- Depends on 0048 (app.audit_log).
--
-- Rollback: DROP TRIGGER IF EXISTS trg_audit_log_no_update_delete ON app.audit_log
--           DROP TRIGGER IF EXISTS trg_audit_log_no_truncate ON app.audit_log
--           DROP FUNCTION IF EXISTS app.audit_log_refuse_change()
--           DELETE FROM schema_migrations WHERE filename = '0072_audit_log_append_only.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)

BEGIN;

CREATE OR REPLACE FUNCTION app.audit_log_refuse_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'app.audit_log is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

DROP TRIGGER IF EXISTS trg_audit_log_no_update_delete ON app.audit_log;
CREATE TRIGGER trg_audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON app.audit_log
    FOR EACH ROW EXECUTE FUNCTION app.audit_log_refuse_change();

DROP TRIGGER IF EXISTS trg_audit_log_no_truncate ON app.audit_log;
CREATE TRIGGER trg_audit_log_no_truncate
    BEFORE TRUNCATE ON app.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION app.audit_log_refuse_change();

COMMIT;
