-- scripts/sql/0048_app_schema_undo.sql — undoes 0048_app_schema.sql (DEC-39 group 1).
-- WRITTEN BUT NOT APPLIED (2026-10-09). Nothing here has ever run against a database.
--
-- Puts the six account/audit tables back in `public` as base tables, removes the six
-- compatibility views, and drops schema `app`. Follows the same shape as
-- scripts/sql/2026-09-28_lock_down_data_api_undo.sql: an undo kept beside the change it
-- reverses, applied only if the change breaks something.
--
-- WHY IT IS NOT A NUMBERED MIGRATION
--   scripts/run_canonical_load.py applies every `0*.sql` in analytics/db/migrations that the
--   ledger does not list. A file named `0049_...` sitting there would be applied by the next
--   routine `--schema-only` run, undoing 0048 on a database nobody meant to change. So it
--   lives here instead. To actually use it: copy it to
--   analytics/db/migrations/00NN_app_schema_rollback.sql with the next free number, rehearse
--   it (`--rehearse --rehearse-check`), then apply it through the runner so the ledger records
--   it. Both rows stay in schema_migrations - the ledger is a history, not a current state.
--
-- ONE DIFFERENCE FROM THE STATE BEFORE 0048, ON PURPOSE
--   Before 0048 all six tables carried a leftover grant of REFERENCES, TRIGGER and TRUNCATE to
--   `service_role` (the 2026-09-28 lock-down revoked anon and authenticated but not
--   service_role). 0048 revoked it, and this file does NOT put it back: it is a privilege
--   nothing uses, on tables holding accounts and session records, and re-granting it to undo an
--   unrelated change would be a quiet security regression. Everything else - owner, columns,
--   indexes, constraints, identity sequences, row-level security, object IDs and every row - is
--   restored exactly, because SET SCHEMA moves all of it and touches no data.
--
-- EXPECTED: 6 views dropped, 6 tables back in `public` with their object IDs unchanged
--   (SET SCHEMA is a catalog update, not a rebuild), schema `app` gone, 0 rows changed. The
--   row-count guard below proves the last of those rather than asserting it.
--
--   DROP SCHEMA app RESTRICT is deliberate: RESTRICT, not CASCADE, so that if anything else has
--   since been created in `app` - a group 2 table, someone's scratch object - this file fails
--   loudly instead of silently destroying it. If that happens, look at what is in `app` and
--   decide; do not reach for CASCADE.
--
-- MUST BE ONE TRANSACTION. Through the runner that is automatic. By hand in psql, wrap it:
--   BEGIN; \i scripts/sql/0048_app_schema_undo.sql  -- then check the output, then COMMIT;
-- Halfway through, `public` has neither the tables nor the views and every signed-in request
-- fails, so this must not be left open.

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TEMP TABLE _0048_undo_rowcount_before ON COMMIT DROP AS
    SELECT 'users'                    AS table_name, count(*) AS row_count FROM app.users
    UNION ALL SELECT 'user_session',             count(*) FROM app.user_session
    UNION ALL SELECT 'auth_token',               count(*) FROM app.auth_token
    UNION ALL SELECT 'user_mfa',                 count(*) FROM app.user_mfa
    UNION ALL SELECT 'user_permission_override', count(*) FROM app.user_permission_override
    UNION ALL SELECT 'audit_log',                count(*) FROM app.audit_log;

-- The views first: a view onto app.users blocks nothing, but dropping it afterwards would
-- mean the name `public.users` briefly refers to a view and a table at once, which it cannot.
DROP VIEW public.users;
DROP VIEW public.user_session;
DROP VIEW public.auth_token;
DROP VIEW public.user_mfa;
DROP VIEW public.user_permission_override;
DROP VIEW public.audit_log;

ALTER TABLE app.users                    SET SCHEMA public;
ALTER TABLE app.user_session             SET SCHEMA public;
ALTER TABLE app.auth_token               SET SCHEMA public;
ALTER TABLE app.user_mfa                 SET SCHEMA public;
ALTER TABLE app.user_permission_override SET SCHEMA public;
ALTER TABLE app.audit_log                SET SCHEMA public;

DO $do$
DECLARE
    compared integer;
    mismatch text;
BEGIN
    WITH after_move(table_name, row_count) AS (
                  SELECT 'users',                    count(*) FROM public.users
        UNION ALL SELECT 'user_session',             count(*) FROM public.user_session
        UNION ALL SELECT 'auth_token',               count(*) FROM public.auth_token
        UNION ALL SELECT 'user_mfa',                 count(*) FROM public.user_mfa
        UNION ALL SELECT 'user_permission_override', count(*) FROM public.user_permission_override
        UNION ALL SELECT 'audit_log',                count(*) FROM public.audit_log
    ), paired AS (
        SELECT b.table_name, b.row_count AS before_rows, a.row_count AS after_rows
          FROM _0048_undo_rowcount_before b
          JOIN after_move a USING (table_name)
    )
    SELECT count(*),
           string_agg(table_name || ' before ' || before_rows || ' after ' || after_rows, '; '
                      ORDER BY table_name) FILTER (WHERE before_rows <> after_rows)
      INTO compared, mismatch
      FROM paired;

    IF compared <> 6 THEN
        RAISE EXCEPTION USING MESSAGE =
            '0048 undo: row-count check compared ' || compared || ' of 6 tables. Rolling back.';
    END IF;
    IF mismatch IS NOT NULL THEN
        RAISE EXCEPTION USING MESSAGE =
            '0048 undo: rows changed across SET SCHEMA: ' || mismatch || '. Rolling back.';
    END IF;
    RAISE NOTICE '0048 undo: row counts identical across SET SCHEMA for all 6 tables';
END
$do$;

-- The comments as they were before 0048: three tables had one, three had none.
COMMENT ON TABLE public.auth_token IS
    'One-time invite / password-reset links (backend/account_links.py). Stores only the sha256 of each token.';
COMMENT ON TABLE public.user_mfa IS
    'Authenticator-app two-step sign-in (backend/mfa.py). enabled_at NULL = setup not confirmed yet.';
COMMENT ON TABLE public.user_permission_override IS
    'Per-user permission exceptions to the role preset (backend/permissions.py). granted=true adds, false removes.';
COMMENT ON TABLE public.users IS NULL;
COMMENT ON TABLE public.user_session IS NULL;
COMMENT ON TABLE public.audit_log IS NULL;

DROP SCHEMA app RESTRICT;

-- No code change is needed alongside this. scripts/rehearse_fills.py's SOURCE_SCHEMAS keeps
-- ("public", "app"), and its catalog queries filter on nspname, so a schema that no longer
-- exists simply contributes no tables rather than raising - the clone list goes back to being
-- public's alone on its own.
