-- 0048_app_schema.sql — DEC-39 group 1: the 6 account/audit tables move out of `public`
-- into a schema named `app`, and a compatibility view keeps each one reachable at its old
-- name. Plan: reports/SCHEMA_REORG_PLAN.md section 5 "Group 1 — app (0048)".
--
-- WHY
--   `public` holds three unrelated kinds of table — the warehouse (facts and dimensions),
--   the loader's bookkeeping, and the web app's own accounts, sessions, tokens and audit
--   trail. The third kind is read on every single request and has nothing to do with the
--   pipeline. DEC-39 (reports/SCHEMA_REORG_PLAN.md appendix, PROPOSED) puts it in `app`.
--
-- WHAT MOVES (6 tables, 0.35 MB live on 2026-10-08)
--   users, user_session, auth_token, user_mfa, user_permission_override, audit_log
--   Their 4 identity sequences, 13 indexes and 4 foreign keys (all 4 between two of these
--   six, so all 4 stay inside `app`) move with them — ALTER TABLE ... SET SCHEMA takes
--   owned sequences, indexes and constraints along.
--
-- WHAT DOES NOT MOVE, AND WHY NOTHING BREAKS
--   * No function body names any of the 6 (verified live 2026-10-08: 0 of the 7 functions
--     in `public`/`mart`). `mart.refresh_status` reads audit_log and follows it by object ID,
--     not by name, so the view keeps working with no change and no re-creation.
--   * Nothing in the codebase schema-qualifies these tables; every reference is the bare
--     name resolved through search_path. That is exactly what the compatibility views in
--     `public` keep answering, so backend, scripts, probes and tests keep working unchanged.
--     The views are a bridge, not the destination: section 5 group 5 drops them once the
--     app module's references are qualified.
--
-- THE VIEWS
--   One per moved table, in `public`, same name, columns listed explicitly in the table's
--   own order. `security_invoker = true` (Postgres 15+; live is 17.6) so the view reads with
--   the CALLER's privileges and row-level security, never the owner's — the default
--   (owner's rights) would turn a view on an RLS-protected table into a way around it.
--   Each view is a single-table SELECT of plain column references, which makes it
--   automatically updatable: INSERT, UPDATE, DELETE and INSERT ... ON CONFLICT pass through
--   to the table underneath, and an omitted column falls back to the base table's default,
--   including the identity sequence.
--
-- SECURITY
--   All 6 tables have row-level security on with 0 policies, and keep it (SET SCHEMA does
--   not touch RLS). Schema `app` is created with no privileges for anyone: the three
--   Supabase API roles (anon, authenticated, service_role) are revoked explicitly, and so is
--   PUBLIC, because USAGE held by PUBLIC would be inherited by all three and make the
--   revoke above pointless. The 6 tables arrive still carrying a leftover
--   REFERENCES/TRIGGER/TRUNCATE grant to service_role (live 2026-10-08; the 2026-09-28
--   lock-down revoked anon and authenticated but not service_role) — inert without schema
--   USAGE, revoked here anyway so `app` starts with no grant row at all. The views are
--   revoked from the same three roles: `public` is an API-exposed schema, and a view there
--   must not become a readable copy of a table that is not.
--
-- TIMEOUTS, AND WHY THEY MATTER MORE THAN THE WORK DOES
--   The catalog work is milliseconds. The risk is the wait: SET SCHEMA takes an ACCESS
--   EXCLUSIVE lock, and every signed-in request reads users and user_session, so a lock
--   this transaction cannot get immediately would queue every other session behind it.
--   lock_timeout = 5s makes it fail and roll back instead of stalling the app;
--   statement_timeout = 30s bounds the rest. Both are SET LOCAL: this transaction only.
--
-- THE COUNT CHECK IS INSIDE THIS TRANSACTION, NOT AGAINST A NUMBER WRITTEN HERE
--   An earlier draft said "afterwards, users must still have 3 rows" and listed the counts
--   read on 2026-10-08. That is the wrong test. These tables are live: user_session had
--   already gone 101 -> 103 between the plan being written and this file, every sign-in
--   moves it again, and a signed-in request can add an audit_log row while this migration
--   is being typed. A literal in a comment can only ever be stale, and comparing against a
--   stale literal either fails for the wrong reason or passes by luck.
--   So the migration counts all 6 tables into a temporary table immediately BEFORE the
--   moves and counts them again immediately AFTER, inside this one transaction, and raises
--   if any pair differs or if fewer than 6 pairs are compared. The transaction's snapshot
--   makes that exact: no other session's commit is visible to either count, so the two are
--   comparable in a way that a reading taken minutes earlier is not. A mismatch aborts and
--   rolls back the whole migration.
--   For orientation only, never asserted: on 2026-10-08 the counts were users 3,
--   user_session 103, auth_token 2, user_mfa 1, user_permission_override 0, audit_log 77,
--   and the object IDs were 17746 / 37442 / 43348 / 47415 / 46404 / 18050 in that order.
--   Object IDs are stable facts, not moving ones, and ARE checked after the apply
--   (scripts/sql/0048_verify.sql) — SET SCHEMA must not recreate a table.
--
-- ROLLBACK: 0049_app_schema_rollback.sql (written alongside this file, NOT applied) —
--           drops the 6 views, moves the 6 tables back to public, DROP SCHEMA app RESTRICT
--           so it refuses if anything else has since been put in app. The ledger keeps both
--           rows. This file cannot half-apply: the apply and its schema_migrations row are
--           one transaction (scripts/run_canonical_load.py:1569-1594).

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE SCHEMA app;

COMMENT ON SCHEMA app IS
    'DEC-39 group 1: the web app''s own tables — accounts, sessions, one-time tokens, '
    'two-step secrets, permission exceptions and the audit trail. Not the warehouse, not '
    'the loader''s bookkeeping. No privileges for the Supabase API roles. See '
    'reports/SCHEMA_REORG_PLAN.md section 5.';

REVOKE ALL ON SCHEMA app FROM anon, authenticated, service_role;
REVOKE ALL ON SCHEMA app FROM PUBLIC;

CREATE TEMP TABLE _0048_rowcount_before ON COMMIT DROP AS
    SELECT 'users'                    AS table_name, count(*) AS row_count FROM public.users
    UNION ALL SELECT 'user_session',             count(*) FROM public.user_session
    UNION ALL SELECT 'auth_token',               count(*) FROM public.auth_token
    UNION ALL SELECT 'user_mfa',                 count(*) FROM public.user_mfa
    UNION ALL SELECT 'user_permission_override', count(*) FROM public.user_permission_override
    UNION ALL SELECT 'audit_log',                count(*) FROM public.audit_log;

ALTER TABLE public.users                    SET SCHEMA app;
ALTER TABLE public.user_session             SET SCHEMA app;
ALTER TABLE public.auth_token               SET SCHEMA app;
ALTER TABLE public.user_mfa                 SET SCHEMA app;
ALTER TABLE public.user_permission_override SET SCHEMA app;
ALTER TABLE public.audit_log                SET SCHEMA app;

DO $do$
DECLARE
    compared integer;
    mismatch text;
BEGIN
    WITH after_move(table_name, row_count) AS (
                  SELECT 'users',                    count(*) FROM app.users
        UNION ALL SELECT 'user_session',             count(*) FROM app.user_session
        UNION ALL SELECT 'auth_token',               count(*) FROM app.auth_token
        UNION ALL SELECT 'user_mfa',                 count(*) FROM app.user_mfa
        UNION ALL SELECT 'user_permission_override', count(*) FROM app.user_permission_override
        UNION ALL SELECT 'audit_log',                count(*) FROM app.audit_log
    ), paired AS (
        SELECT b.table_name, b.row_count AS before_rows, a.row_count AS after_rows
          FROM _0048_rowcount_before b
          JOIN after_move a USING (table_name)
    )
    SELECT count(*),
           string_agg(table_name || ' before ' || before_rows || ' after ' || after_rows, '; '
                      ORDER BY table_name) FILTER (WHERE before_rows <> after_rows)
      INTO compared, mismatch
      FROM paired;

    IF compared <> 6 THEN
        RAISE EXCEPTION USING MESSAGE =
            '0048 row-count check compared ' || compared || ' of 6 tables - a name did not match '
            || 'between the before snapshot and the after query. Rolling back.';
    END IF;
    IF mismatch IS NOT NULL THEN
        RAISE EXCEPTION USING MESSAGE =
            '0048 row-count check failed, rows changed across SET SCHEMA: ' || mismatch
            || '. A schema move must not touch a single row. Rolling back.';
    END IF;
    RAISE NOTICE '0048: row counts identical across SET SCHEMA for all 6 tables';
END
$do$;

REVOKE ALL ON ALL TABLES    IN SCHEMA app FROM anon, authenticated, service_role;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA app FROM anon, authenticated, service_role;

CREATE VIEW public.users WITH (security_invoker = true) AS
    SELECT user_id, email, password_hash, role, created_at, full_name
      FROM app.users;

CREATE VIEW public.user_session WITH (security_invoker = true) AS
    SELECT session_key, session_id, user_id, user_email, user_name, role,
           started_at, last_seen_at, ended_at, end_reason, source
      FROM app.user_session;

CREATE VIEW public.auth_token WITH (security_invoker = true) AS
    SELECT token_key, token_hash, user_id, purpose, created_at, expires_at, used_at, created_by
      FROM app.auth_token;

CREATE VIEW public.user_mfa WITH (security_invoker = true) AS
    SELECT user_id, secret_encrypted, enabled_at, last_used_step, recovery_hashes, created_at
      FROM app.user_mfa;

CREATE VIEW public.user_permission_override WITH (security_invoker = true) AS
    SELECT user_id, permission_key, granted, set_by, set_at
      FROM app.user_permission_override;

CREATE VIEW public.audit_log WITH (security_invoker = true) AS
    SELECT audit_log_key, user_email, user_name, role, action, details, created_at
      FROM app.audit_log;

REVOKE ALL ON public.users                    FROM anon, authenticated, service_role;
REVOKE ALL ON public.user_session             FROM anon, authenticated, service_role;
REVOKE ALL ON public.auth_token               FROM anon, authenticated, service_role;
REVOKE ALL ON public.user_mfa                 FROM anon, authenticated, service_role;
REVOKE ALL ON public.user_permission_override FROM anon, authenticated, service_role;
REVOKE ALL ON public.audit_log                FROM anon, authenticated, service_role;

COMMENT ON TABLE app.users IS
    'Dashboard accounts (backend/routers/auth.py). Moved from public by 0048, DEC-39 group 1; '
    'public.users is a compatibility view onto this table.';
COMMENT ON TABLE app.user_session IS
    'One row per sign-in (backend/sessions.py); read on every signed-in request. Moved from '
    'public by 0048, DEC-39 group 1; public.user_session is a compatibility view onto this table.';
COMMENT ON TABLE app.auth_token IS
    'One-time invite / password-reset links (backend/account_links.py). Stores only the sha256 '
    'of each token. Moved from public by 0048, DEC-39 group 1; public.auth_token is a '
    'compatibility view onto this table.';
COMMENT ON TABLE app.user_mfa IS
    'Authenticator-app two-step sign-in. enabled_at NULL = setup not confirmed yet. Moved from '
    'public by 0048, DEC-39 group 1; public.user_mfa is a compatibility view onto this table.';
COMMENT ON TABLE app.user_permission_override IS
    'Per-user permission exceptions to the role preset (backend/permissions.py). granted=true '
    'adds, false removes. Moved from public by 0048, DEC-39 group 1; '
    'public.user_permission_override is a compatibility view onto this table.';
COMMENT ON TABLE app.audit_log IS
    'Who did what, when (backend/audit.py); also written by the ETL fill and slice loaders. '
    'mart.refresh_status reads it. Moved from public by 0048, DEC-39 group 1; public.audit_log '
    'is a compatibility view onto this table.';

COMMENT ON VIEW public.users IS
    'Compatibility view onto app.users (0048, DEC-39 group 1). security_invoker, no grants to '
    'the API roles. Temporary bridge for unqualified references; dropped once the app module '
    'names app.users directly (plan section 5 group 5). A column added to app.users is '
    'invisible here until this view is re-created.';
COMMENT ON VIEW public.user_session IS
    'Compatibility view onto app.user_session (0048, DEC-39 group 1). security_invoker, no '
    'grants to the API roles. Temporary bridge — see the comment on public.users.';
COMMENT ON VIEW public.auth_token IS
    'Compatibility view onto app.auth_token (0048, DEC-39 group 1). security_invoker, no '
    'grants to the API roles. Temporary bridge — see the comment on public.users.';
COMMENT ON VIEW public.user_mfa IS
    'Compatibility view onto app.user_mfa (0048, DEC-39 group 1). security_invoker, no grants '
    'to the API roles. Temporary bridge — see the comment on public.users.';
COMMENT ON VIEW public.user_permission_override IS
    'Compatibility view onto app.user_permission_override (0048, DEC-39 group 1). '
    'security_invoker, no grants to the API roles. Temporary bridge — see the comment on '
    'public.users.';
COMMENT ON VIEW public.audit_log IS
    'Compatibility view onto app.audit_log (0048, DEC-39 group 1). security_invoker, no grants '
    'to the API roles. Temporary bridge — see the comment on public.users.';
