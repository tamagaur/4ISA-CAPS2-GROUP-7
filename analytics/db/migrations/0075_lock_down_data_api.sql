-- 0075: lock the Supabase Data API out of the schema this migration is applied to.
--
-- Supabase serves every table of its exposed schema over REST/GraphQL to anyone holding the project's anon key (the
-- key shipped in the frontend bundle), gated only by table, sequence and function privileges and by row-level
-- security. The dashboard never uses that API: the frontend talks to the FastAPI backend, which connects as the
-- owner role (postgres). This brings scripts/sql/2026-09-28_lock_down_data_api.sql (a hand-run script that named 23
-- tables, 3 of which are views or gone now) into the migration chain, and reads the catalog instead of naming objects.
--
-- WHAT IT DOES, to whichever schema it is applied to (current_schema(); the live runner's search_path puts that at
-- the live schema; a scratch build sees its scratch schema, and a database without the Supabase roles skips every
-- role statement):
--   1. anon and authenticated: REVOKE ALL on every table, view, sequence and function of the schema.
--   2. service_role: REVOKE SELECT, INSERT, UPDATE, DELETE on every table and view, and ALL on every sequence. This is
--      what live already holds (read 2026-11-05: service_role keeps only TRUNCATE, REFERENCES, TRIGGER, MAINTAIN) and the
--      2026-09-28 script lacked. service_role bypasses row-level security, so a leaked service key would read everything.
--   3. PUBLIC: REVOKE EXECUTE on every function of the schema (Postgres grants it by default, so anon holds it through
--      PUBLIC; found 2026-11-05 on inventory_fact_count_month, a trigger function that returns nothing callable).
--      Triggers keep firing: a trigger does not need its caller to hold EXECUTE.
--   4. Defaults for objects this role creates later: no automatic grant to anon, authenticated, or (SELECT, INSERT,
--      UPDATE, DELETE) service_role on tables and sequences, and no EXECUTE for PUBLIC on functions. Default
--      privileges set for the role supabase_admin are not this role's to change and are left alone.
--   5. Row-level security ON for every ordinary and partitioned table, no policies, not FORCEd (the owner is unaffected).
--
-- AGAINST LIVE (catalog read 2026-11-05) this is NOT a no-op: steps 1, 2 and 5 find nothing to change (anon and
-- authenticated hold nothing; service_role holds no SELECT/INSERT/UPDATE/DELETE; 33 of 33 tables have row-level
-- security). Step 3 revokes PUBLIC's EXECUTE on one function, and step 4 adds the missing default for functions.
-- Nothing the backend reads changes: it connects as the owner.
--
-- Unqualified names on purpose: a scratch build refuses a migration that names the live schema explicitly.
-- Idempotent: every statement is a REVOKE or an ENABLE.
-- Rollback: GRANT back what you need; to undo step 4, ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO PUBLIC.
--           Then DELETE FROM schema_migrations WHERE filename = '0075_lock_down_data_api.sql'.

DO $lockdown$
DECLARE
    s text := current_schema();
    r text;
    t record;
BEGIN
    -- 1 and 3. anon, authenticated: nothing at all.
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM %I', s, r);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM %I', s, r);
            EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I FROM %I', s, r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON TABLES FROM %I', s, r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM %I', s, r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON FUNCTIONS FROM %I', s, r);
        END IF;
    END LOOP;

    -- 2. service_role: keeps no read or write right.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE format('REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I FROM service_role', s);
        EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM service_role', s);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM service_role', s);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM service_role', s);
    END IF;

    -- 3 and 4. PUBLIC may not execute functions, now or later.
    EXECUTE format('REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA %I FROM PUBLIC', s);
    ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

    -- 5. Row-level security on every table, no policies.
    FOR t IN
        SELECT c.relname
        FROM pg_class c
        WHERE c.relnamespace = s::regnamespace
          AND c.relkind IN ('r', 'p')
          AND NOT c.relrowsecurity
    LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', s, t.relname);
    END LOOP;
END
$lockdown$;
