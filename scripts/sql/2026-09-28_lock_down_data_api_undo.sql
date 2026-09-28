-- UNDO for 2026-09-28_lock_down_data_api.sql
-- Only if the lock-down breaks something. Run the same way, in the Supabase
-- SQL Editor. Puts back exactly the state recorded before it ran
-- (backups/full_backup_20260928T081914Z/structure/public.sql): anon and
-- authenticated get back TRUNCATE, REFERENCES, TRIGGER and MAINTAIN on every
-- public table and view (never SELECT/INSERT/UPDATE/DELETE - they had none),
-- new tables get the same by default again, and row-level security goes off.

BEGIN;

GRANT MAINTAIN, REFERENCES, TRIGGER, TRUNCATE ON ALL TABLES IN SCHEMA public TO anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT MAINTAIN, REFERENCES, TRIGGER, TRUNCATE ON TABLES TO anon, authenticated;

ALTER TABLE public.abc_classification DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_log DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.customer_dimension DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.date_dimension DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.etl_cutover_ledger DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.etl_quarantine DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.forecast_result DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.inventory_fact DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.lp_recommendation DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_dimension DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_dimension_backup_20260918 DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_fact DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.sales_fact DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.salesman_dimension DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.salesreturn_fact DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.schema_migrations DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.sellout_fact DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.sku_segment DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.sku_traits DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.supplier_dimension DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.unilever_sku_demand_fact DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_session DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.users DISABLE ROW LEVEL SECURITY;

COMMIT;
