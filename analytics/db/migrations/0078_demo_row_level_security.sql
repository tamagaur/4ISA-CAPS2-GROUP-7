-- 0078_demo_row_level_security.sql - row-level security ON for every table of the demo schema, as every table of public,
-- app and mart already has.
--
-- Read on live 2026-11-11: demo holds 11 tables, row-level security off on all 11; public 33 of 33, app 6 of 6, mart 13 of 13
-- on. The demo tables are not reachable through the Supabase Data API today: only postgres holds USAGE on schema demo, every
-- table grant in it is postgres's, and the API exposes public only. So this closes no open door; it removes the one schema
-- whose safety rests on a single layer (the schema grant), so a later GRANT USAGE ON SCHEMA demo, or exposing the schema in
-- the API settings, does not by itself publish generated rows.
--
-- No policies, not FORCEd: the owner (postgres, the role the backend and every script connect as) is unaffected, exactly as
-- migration 0075 step 5 does for the schema it is applied to. Catalog-driven, so a demo table added later by a migration
-- that forgets this is caught by tests/test_lockdown_migration.py, not silently left open.
-- Idempotent: ENABLE on a table that already has it is a no-op.
-- Rollback: ALTER TABLE demo.<table> DISABLE ROW LEVEL SECURITY for each; DELETE FROM schema_migrations WHERE filename =
-- '0078_demo_row_level_security.sql'.

DO $demo_rls$
DECLARE
    t record;
BEGIN
    IF to_regnamespace('demo') IS NULL THEN
        RAISE NOTICE '0078: schema demo does not exist here; nothing to do';
        RETURN;
    END IF;
    FOR t IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'demo' AND c.relkind IN ('r', 'p') AND NOT c.relrowsecurity LOOP
        EXECUTE format('ALTER TABLE demo.%I ENABLE ROW LEVEL SECURITY', t.relname);
    END LOOP;
END
$demo_rls$;
