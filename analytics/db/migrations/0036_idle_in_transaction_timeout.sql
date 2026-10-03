-- analytics/db/migrations/0036_idle_in_transaction_timeout.sql
--
-- NOT APPLIED. X = 600 s (10 minutes), decided 2026-10-02; until then this
-- was 0036_...sql.draft with a placeholder value, kept out of the runner's
-- 0*.sql glob so no ledger row could record the placeholder's checksum.
--
-- Ends any postgres-role session that sits idle INSIDE an open transaction
-- for longer than X, releasing its locks (security audit 2026-09-30 #3: a
-- leaked test session held a lock on abc_classification). Idle sessions
-- outside a transaction are not affected.
--
-- Live before this migration (read-only, 2026-09-30):
--   idle_in_transaction_session_timeout = 0, source = default
--   postgres's role settings (pg_db_role_setting): search_path only
--   supabase_auth_admin (Supabase's own role): 60000 ms - a reference point,
--   not a decision.
-- X must exceed the longest legitimate idle-in-transaction gap of every tool
-- that logs in as postgres - backend, loader, backups, apply_* scripts, SQL
-- Editor (e.g. a backup_everything run, a loader slice).
--
-- Per role, not per database: ALTER DATABASE would also reach Supabase's own
-- roles (pg_net, realtime, storage).
--
-- GUARD: ALTER ROLE is cluster-wide, not per schema, so the runner's usual
-- scratch rehearsal would change the live role. The DO block does nothing
-- unless the target schema (current_schema(): the runner puts it first in
-- search_path) is public. On a scratch schema the ledger records it and
-- nothing changes.
--
-- Takes effect for NEW sessions only. Supavisor keeps its server connections
-- open, so after applying, restart the pooler (Supabase dashboard).
-- Check:    SELECT setconfig FROM pg_db_role_setting WHERE setrole = 'postgres'::regrole;
--           and SHOW idle_in_transaction_session_timeout on a fresh connection.
-- Rollback: ALTER ROLE postgres RESET idle_in_transaction_session_timeout;

DO $$
BEGIN
    IF current_schema() IS DISTINCT FROM 'public' THEN
        RAISE NOTICE '0036 skipped: target schema is %, and a role setting is cluster-wide', current_schema();
        RETURN;
    END IF;
    ALTER ROLE postgres SET idle_in_transaction_session_timeout = '600s';
END
$$;
