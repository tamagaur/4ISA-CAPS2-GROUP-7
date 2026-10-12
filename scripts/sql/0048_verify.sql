-- scripts/sql/0048_verify.sql — the catalog half of 0048's verification.
--
-- Run INSIDE the rehearsal transaction, where the moved objects exist but nothing is
-- committed, and again after the real apply:
--
--   python -m scripts.run_canonical_load --schema public --target-public --schema-only \
--       --rehearse --lock-timeout-ms 5000 --statement-timeout-ms 30000 \
--       --rehearse-check scripts/sql/0048_verify.sql
--
-- ONE statement on purpose: --rehearse-check does not split SQL, and one statement means
-- every check sees exactly the same snapshot. Every row has an `ok` column; the runner
-- fails the rehearsal on any row where it is not true.
--
-- Covers checks 1, 3, 4, 5, 6 and 7 of reports/SCHEMA_REORG_PLAN.md section 5 group 1.
-- Check 2 (row counts) is NOT here: it lives inside 0048 itself, comparing a count taken
-- immediately before SET SCHEMA with one taken immediately after, in the same snapshot —
-- these tables are live, so a count from any earlier moment is already out of date.
-- Check 8 (smoke_api, a real sign-in, GET /audit-log) cannot run here at all: those are
-- separate processes on their own connections, and they cannot see an uncommitted schema.

WITH moved(table_name, expected_oid) AS (
    -- Object IDs read live 2026-10-08 (see the migration header). SET SCHEMA is a catalog
    -- update, not a rebuild, so each table must keep the same ID. A changed ID would mean
    -- the table was recreated and every dependency repointed - exactly what must not happen.
              SELECT 'users'::text,                    17746::oid
    UNION ALL SELECT 'user_session',                   37442
    UNION ALL SELECT 'auth_token',                     43348
    UNION ALL SELECT 'user_mfa',                       47415
    UNION ALL SELECT 'user_permission_override',       46404
    UNION ALL SELECT 'audit_log',                      18050
), api_roles(role_name) AS (
    VALUES ('anon'), ('authenticated'), ('service_role')
),

-- 1. object ID unchanged, namespace now app
check_1 AS (
    SELECT '1. ' || m.table_name || ' oid + namespace' AS check_name,
           (c.oid IS NOT NULL AND c.oid = m.expected_oid AND n.nspname = 'app'
            AND c.relkind = 'r') AS ok,
           coalesce('oid=' || c.oid || ' expected=' || m.expected_oid
                    || ' ns=' || n.nspname || ' kind=' || c.relkind::text,
                    'app.' || m.table_name || ' does not exist') AS detail
      FROM moved m
      LEFT JOIN pg_class c ON c.oid = to_regclass('app.' || quote_ident(m.table_name))
      LEFT JOIN pg_namespace n ON n.oid = c.relnamespace
),

-- 3. row-level security still on, still 0 policies
check_3 AS (
    SELECT '3. ' || m.table_name || ' rls on, 0 policies' AS check_name,
           (c.relrowsecurity AND pol.n = 0) AS ok,
           'rls=' || c.relrowsecurity || ' forced=' || c.relforcerowsecurity
               || ' policies=' || pol.n AS detail
      FROM moved m
      JOIN pg_class c ON c.oid = to_regclass('app.' || quote_ident(m.table_name))
      CROSS JOIN LATERAL (SELECT count(*) AS n FROM pg_policy p WHERE p.polrelid = c.oid) pol
),

-- 4a. no API role has any privilege on schema app (USAGE or CREATE, direct or inherited)
check_4a AS (
    SELECT '4a. schema app privileges for ' || r.role_name AS check_name,
           (NOT has_schema_privilege(r.role_name, 'app', 'USAGE')
            AND NOT has_schema_privilege(r.role_name, 'app', 'CREATE')) AS ok,
           'usage=' || has_schema_privilege(r.role_name, 'app', 'USAGE')
               || ' create=' || has_schema_privilege(r.role_name, 'app', 'CREATE') AS detail
      FROM api_roles r
),

-- 4b. zero grant rows for the API roles anywhere in app
check_4b AS (
    SELECT '4b. grant rows on app.* for the 3 API roles' AS check_name,
           count(*) = 0 AS ok,
           'rows=' || count(*) || coalesce(': ' || string_agg(
               grantee || ' ' || privilege_type, ', ' ORDER BY grantee, privilege_type), '') AS detail
      FROM information_schema.role_table_grants
     WHERE table_schema = 'app' AND grantee IN ('anon', 'authenticated', 'service_role')
),

-- 4c. zero grant rows for the API roles on the 6 compatibility views
check_4c AS (
    SELECT '4c. grant rows on the 6 public views for the 3 API roles' AS check_name,
           count(*) = 0 AS ok,
           'rows=' || count(*) || coalesce(': ' || string_agg(
               table_name || ' ' || grantee || ' ' || privilege_type, ', '), '') AS detail
      FROM information_schema.role_table_grants
     WHERE table_schema = 'public'
       AND table_name IN (SELECT table_name FROM moved)
       AND grantee IN ('anon', 'authenticated', 'service_role')
),

-- 5. each view: a view, security_invoker on, and writable through
check_5 AS (
    SELECT '5. public.' || m.table_name || ' view options' AS check_name,
           (c.relkind = 'v'
            AND c.reloptions @> ARRAY['security_invoker=true']
            AND v.is_insertable_into = 'YES'
            AND v.is_updatable = 'YES') AS ok,
           coalesce('kind=' || c.relkind::text || ' options=' || coalesce(c.reloptions::text, 'NULL')
                    || ' insertable=' || coalesce(v.is_insertable_into, '?')
                    || ' updatable=' || coalesce(v.is_updatable, '?'),
                    'public.' || m.table_name || ' does not exist') AS detail
      FROM moved m
      LEFT JOIN pg_class c ON c.oid = to_regclass('public.' || quote_ident(m.table_name))
      LEFT JOIN information_schema.views v
             ON v.table_schema = 'public' AND v.table_name = m.table_name
),

-- 5b. the view's column list matches the table it fronts, in order
check_5b AS (
    SELECT '5b. public.' || m.table_name || ' columns match app.' || m.table_name AS check_name,
           vc.cols IS NOT NULL AND vc.cols = tc.cols AS ok,
           'view=' || coalesce(vc.cols::text, 'NULL') || ' table=' || coalesce(tc.cols::text, 'NULL') AS detail
      FROM moved m
      CROSS JOIN LATERAL (
          SELECT array_agg(column_name::text ORDER BY ordinal_position) AS cols
            FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = m.table_name) vc
      CROSS JOIN LATERAL (
          SELECT array_agg(column_name::text ORDER BY ordinal_position) AS cols
            FROM information_schema.columns
           WHERE table_schema = 'app' AND table_name = m.table_name) tc
),

-- 5c. the 4 identity sequences came along with their tables
check_5c AS (
    SELECT '5c. identity sequences in app' AS check_name,
           count(*) = 4 AS ok,
           'count=' || count(*) || ': ' || coalesce(string_agg(
               seq_schema || '.' || seq_name, ', ' ORDER BY seq_name), 'none') AS detail
      FROM (
          SELECT sn.nspname AS seq_schema, s.relname AS seq_name
            FROM pg_depend d
            JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
            JOIN pg_namespace sn ON sn.oid = s.relnamespace
            JOIN pg_class t ON t.oid = d.refobjid
            JOIN pg_namespace tn ON tn.oid = t.relnamespace
           WHERE d.deptype IN ('a', 'i') AND tn.nspname = 'app'
             AND t.relname IN (SELECT table_name FROM moved)
             AND sn.nspname = 'app') q
),

-- 6. the bare name still resolves through search_path (backend/permissions.py:probe)
check_6 AS (
    SELECT '6. to_regclass(''user_permission_override'') resolves' AS check_name,
           to_regclass('user_permission_override') IS NOT NULL AS ok,
           coalesce(to_regclass('user_permission_override')::text, 'NULL')
               || ' (search_path=' || current_setting('search_path') || ')' AS detail
),

-- 7. mart.refresh_status still answers, and now reads app.audit_log
check_7a AS (
    SELECT '7a. mart.refresh_status row count' AS check_name,
           count(*) = 1 AS ok, 'rows=' || count(*) AS detail
      FROM mart.refresh_status
),
check_7b AS (
    SELECT '7b. mart.refresh_status depends on app.audit_log' AS check_name,
           count(*) > 0 AS ok,
           'dependency rows=' || count(*) || ' (one per referenced column, so >1 is normal)' AS detail
      FROM pg_depend d
      JOIN pg_rewrite rw ON rw.oid = d.objid
     WHERE rw.ev_class = 'mart.refresh_status'::regclass
       AND d.refobjid = to_regclass('app.audit_log')
),

-- 8. not runnable here, reported so the list is complete rather than silently short
check_8 AS (
    SELECT '8. smoke_api 17/17, sign-in, GET /audit-log' AS check_name,
           true AS ok,
           'DEFERRED: separate processes on their own connections cannot see an uncommitted '
               || 'schema. Phase 3 only, after the apply commits.' AS detail
)

SELECT check_name, ok, detail FROM (
    SELECT * FROM check_1
    UNION ALL SELECT * FROM check_3
    UNION ALL SELECT * FROM check_4a
    UNION ALL SELECT * FROM check_4b
    UNION ALL SELECT * FROM check_4c
    UNION ALL SELECT * FROM check_5
    UNION ALL SELECT * FROM check_5b
    UNION ALL SELECT * FROM check_5c
    UNION ALL SELECT * FROM check_6
    UNION ALL SELECT * FROM check_7a
    UNION ALL SELECT * FROM check_7b
    UNION ALL SELECT * FROM check_8
) all_checks
ORDER BY check_name;
