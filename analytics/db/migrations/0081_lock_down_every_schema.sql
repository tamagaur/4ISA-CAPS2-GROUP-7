-- 0081: take PUBLIC's EXECUTE (and everything 0075 removes from anon, authenticated and service_role) off the functions,
-- tables and sequences of EVERY schema this role owns, not only the one 0075 happened to be applied to.
--
-- Why. 0075 is catalog-driven but acts on current_schema(), and the live runner's search_path makes that public, which holds no
-- function. Read on live 2026-11-16: 8 functions still carry EXECUTE for PUBLIC (Postgres grants it by default, so anon holds it
-- through PUBLIC): 1 in the app schema (the audit-log trigger function) and 7 in the mart schema (capture_forecast_result,
-- data_kind, month_add, refresh, refresh_error_decomposition, refresh_planning, source_tag). The Data API exposes public only, so
-- none was reachable that way today; this removes the second layer's dependence on that single setting. Nothing the backend runs
-- changes: it connects as the owner (postgres), which keeps EXECUTE on what it owns, and a trigger fires without its caller
-- holding EXECUTE.
--
-- WHAT IT DOES, to each schema that (a) is owned by the role running the migration and (b) hosts no extension (so Supabase's own
-- schemas, auth, storage, realtime, graphql, vault, and extensions are never touched; pg_catalog and information_schema never):
--   1. anon, authenticated: REVOKE ALL on every table, sequence and function.
--   2. service_role: REVOKE SELECT, INSERT, UPDATE, DELETE on tables, ALL on sequences.
--   3. PUBLIC: REVOKE EXECUTE on every function the role owns that is not a member of an extension.
--   4. Row-level security ON for every ordinary and partitioned table, no policies, not FORCEd (the owner is unaffected).
-- Every role statement is skipped when the role does not exist (a database without the Supabase roles).
-- No ALTER DEFAULT PRIVILEGES: 0075 already set the role's default for functions, database-wide; this adds nothing database-wide.
--
-- It only acts when current_schema() is the live schema. A scratch build of the migration chain runs in a scratch schema of the SAME
-- database as live, where this loop would reach the live schemas; there it does nothing and says so.
-- Names no table and no live schema explicitly (a scratch build refuses a migration that does).
-- Idempotent: every statement is a REVOKE or an ENABLE.
-- Rollback: GRANT EXECUTE ON FUNCTION <function> TO PUBLIC for each of the eight functions above;
--           then DELETE FROM schema_migrations WHERE filename = '0081_lock_down_every_schema.sql'.

DO $lock_every_schema$
DECLARE
    s record;
    f record;
    t record;
    r text;
BEGIN
    IF current_schema() <> 'public' THEN
        RAISE NOTICE '0081: current_schema() is %, not the live schema; nothing to do', current_schema();
        RETURN;
    END IF;
    FOR s IN
        SELECT n.nspname AS name
        FROM pg_namespace n
        WHERE n.nspowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
          AND n.nspname NOT LIKE 'pg\_%'
          AND n.nspname <> 'information_schema'
          AND NOT EXISTS (SELECT 1 FROM pg_extension e WHERE e.extnamespace = n.oid)
        UNION
        SELECT current_schema()
        ORDER BY 1
    LOOP
        -- 1. anon, authenticated: nothing at all.
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM %I', s.name, r);
                EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM %I', s.name, r);
                EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I FROM %I', s.name, r);
            END IF;
        END LOOP;

        -- 2. service_role: no read or write right.
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I FROM service_role', s.name);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM service_role', s.name);
        END IF;

        -- 3. PUBLIC may not execute the functions this role owns (an extension's own functions are left alone).
        FOR f IN
            SELECT p.oid::regprocedure AS sig
            FROM pg_proc p
            WHERE p.pronamespace = s.name::regnamespace
              AND p.proowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
              AND NOT EXISTS (SELECT 1 FROM pg_depend d
                              WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')
        LOOP
            EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC', f.sig);
        END LOOP;

        -- 4. Row-level security on every table, no policies.
        FOR t IN
            SELECT c.relname
            FROM pg_class c
            WHERE c.relnamespace = s.name::regnamespace
              AND c.relkind IN ('r', 'p')
              AND NOT c.relrowsecurity
        LOOP
            EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', s.name, t.relname);
        END LOOP;
    END LOOP;
END
$lock_every_schema$;
