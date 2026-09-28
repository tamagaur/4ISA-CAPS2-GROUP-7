-- Lock down Supabase's automatic API (the "Data API") over the public schema
-- Prepared 2026-09-28 (Audrey; Part B of the security review, OK'd by Yuan).
-- Run once, in the Supabase SQL Editor: New query -> paste this whole file -> Run.
-- (Or: python scripts/run_sql.py scripts/sql/2026-09-28_lock_down_data_api.sql)
-- Safe to run twice. Undo: 2026-09-28_lock_down_data_api_undo.sql.
--
-- WHY: Supabase serves every public table over its own REST/GraphQL API to
-- anyone holding the project's anon key, gated only by table privileges and
-- row-level security. The dashboard never uses that API - the frontend talks
-- only to the FastAPI backend, which connects straight to Postgres as postgres.
--
-- STATE BEFORE (read 2026-09-28 from the live catalog; recorded in
-- backups/full_backup_20260928T081914Z/structure/public.sql):
--   * anon and authenticated had NO SELECT/INSERT/UPDATE/DELETE on any of the
--     23 tables or 9 views, so no rows were readable through the API. They
--     still held TRUNCATE, REFERENCES, TRIGGER and MAINTAIN on all 32, and
--     every new table postgres creates got the same (default privileges).
--   * Row-level security was off on all 23 tables.
--
-- WHAT THIS DOES:
--   1. Revokes everything anon and authenticated still hold on public
--      tables, views and sequences.
--   2. Stops tables and sequences that postgres creates later (SQL Editor,
--      migrations, the ETL) from being granted to them automatically.
--   3. Turns row-level security ON for every table, with no policies: a
--      second lock, so if a grant is ever added back by mistake the API
--      still sees zero rows.
--
-- WHY THE APP KEEPS WORKING: all 23 tables are owned by postgres - the role
-- the backend and the pipeline log in as - and row-level security does not
-- apply to a table's owner (this script does not FORCE it). service_role is
-- left alone: its key is a server-side secret the app does not use.
--
-- Not in analytics/db/migrations/ on purpose: run_canonical_load.py re-applies
-- every file there to its scratch schema and never touches public, while this
-- concerns public only.

BEGIN;

-- 1. Remove the API roles' remaining rights.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;

-- 2. Nothing created later is granted to them automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;

-- 3. Row-level security on every table, no policies.
ALTER TABLE public.abc_classification ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.customer_dimension ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.date_dimension ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.etl_cutover_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.etl_quarantine ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.forecast_result ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inventory_fact ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lp_recommendation ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_dimension ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_dimension_backup_20260918 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_fact ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sales_fact ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.salesman_dimension ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.salesreturn_fact ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sellout_fact ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sku_segment ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sku_traits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.supplier_dimension ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.unilever_sku_demand_fact ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_session ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

COMMIT;

-- Check (read-only). Expect one row: tables 23, tables_with_rls 23, api_role_grants_left 0.
SELECT
    count(*) FILTER (WHERE c.relkind = 'r') AS tables,
    count(*) FILTER (WHERE c.relkind = 'r' AND c.relrowsecurity) AS tables_with_rls,
    count(*) FILTER (WHERE
        has_table_privilege('anon', c.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN')
        OR has_table_privilege('authenticated', c.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN')
    ) AS api_role_grants_left
FROM pg_class c
WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'v');
