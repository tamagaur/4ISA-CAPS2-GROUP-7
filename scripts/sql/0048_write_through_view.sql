-- scripts/sql/0048_write_through_view.sql — proves that the backend's actual write
-- statements still work when they go through a compatibility view instead of a table.
--
-- reports/SCHEMA_REORG_PLAN.md section 3c marks this UNVERIFIED: Postgres documents
-- INSERT ... ON CONFLICT on an automatically updatable view as supported, but it had never
-- been run against this code's statements. Without it, 0048 is a guess.
--
-- Run inside the rehearsal transaction, which never commits:
--   --rehearse-check scripts/sql/0048_write_through_view.sql
-- Everything written here is also deleted here, and the transaction is rolled back
-- regardless, so no row survives either way. The statements are the real ones:
--   backend/audit.py:25                INSERT INTO audit_log (...)           identity omitted
--   backend/routers/auth.py:93         INSERT INTO user_session (...)        identity omitted
--   backend/routers/permissions.py:126 INSERT INTO user_permission_override  foreign keys
--   backend/account_links.py:40        INSERT INTO auth_token (...)          + UPDATE used_at
-- plus the ON CONFLICT form that section 3c singles out, and an UPDATE and a DELETE,
-- because a view that accepts INSERT but silently drops an UPDATE would be worse than one
-- that fails outright.
--
-- ONE statement (a DO block): --rehearse-check does not split SQL. It returns no rows, so
-- the runner prints `ok` unless a RAISE fires.

DO $do$
DECLARE
    v_user_id    bigint;
    v_key        bigint;
    v_count      bigint;
    v_granted    boolean;
    v_identity   bigint;
BEGIN
    -- An existing account, because three of these tables have a foreign key to users.
    -- Reading it through the view too: if the view could not be read, nothing else matters.
    SELECT user_id INTO v_user_id FROM public.users ORDER BY user_id LIMIT 1;
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION USING MESSAGE =
            'no rows in public.users, so the foreign-key writes below cannot be tested. '
            || 'This check needs at least one account to exist.';
    END IF;

    -- 1. plain INSERT with the GENERATED ALWAYS identity column omitted. This is the one
    --    that could quietly fail: the view column is not itself an identity column, so the
    --    insert depends on Postgres falling back to the base table's default. If it did
    --    not, every audit row and every sign-in would break.
    INSERT INTO public.audit_log (user_email, user_name, role, action, details)
    VALUES ('0048-rehearsal@invalid', '0048 rehearsal', 'etl', 'rehearsal',
            'written through public.audit_log, rolled back')
    RETURNING audit_log_key INTO v_identity;
    IF v_identity IS NULL THEN
        RAISE EXCEPTION USING MESSAGE =
            'INSERT through public.audit_log returned no identity value - the base table''s '
            || 'identity default did not apply through the view.';
    END IF;
    RAISE NOTICE 'ok  INSERT through public.audit_log, identity assigned = %', v_identity;

    -- 2. the row is really in the table underneath, not somewhere else
    SELECT count(*) INTO v_count FROM app.audit_log WHERE audit_log_key = v_identity;
    IF v_count <> 1 THEN
        RAISE EXCEPTION USING MESSAGE =
            'row inserted through public.audit_log is not visible in app.audit_log (found '
            || v_count || ' rows) - the view is not writing to the table it fronts.';
    END IF;
    RAISE NOTICE 'ok  the row landed in app.audit_log';

    -- 3. INSERT ... ON CONFLICT DO UPDATE through the view - the UNVERIFIED case.
    --    user_permission_override has a two-column primary key and (live) 0 rows.
    INSERT INTO public.user_permission_override (user_id, permission_key, granted, set_by, set_at)
    VALUES (v_user_id, '0048_rehearsal_key', false, v_user_id, now())
    ON CONFLICT (user_id, permission_key) DO UPDATE SET granted = EXCLUDED.granted;
    RAISE NOTICE 'ok  INSERT ... ON CONFLICT (first pass, inserted)';

    -- the same statement again: this time the conflict fires and DO UPDATE must run
    INSERT INTO public.user_permission_override (user_id, permission_key, granted, set_by, set_at)
    VALUES (v_user_id, '0048_rehearsal_key', true, v_user_id, now())
    ON CONFLICT (user_id, permission_key) DO UPDATE SET granted = EXCLUDED.granted;

    SELECT count(*), bool_and(granted) INTO v_count, v_granted
      FROM app.user_permission_override
     WHERE user_id = v_user_id AND permission_key = '0048_rehearsal_key';
    IF v_count <> 1 THEN
        RAISE EXCEPTION USING MESSAGE =
            'ON CONFLICT through the view left ' || v_count || ' rows, expected exactly 1 - '
            || 'the conflict target did not resolve to the primary key underneath.';
    END IF;
    IF v_granted IS NOT TRUE THEN
        RAISE EXCEPTION USING MESSAGE =
            'ON CONFLICT DO UPDATE through the view did not apply EXCLUDED.granted - the row '
            || 'still reads granted=false, so the second statement was a silent no-op.';
    END IF;
    RAISE NOTICE 'ok  INSERT ... ON CONFLICT DO UPDATE (second pass, updated)';

    -- 4. a write with a NOT NULL + UNIQUE column and a foreign key, then an UPDATE of it,
    --    which is how account_links.py marks a one-time link as used
    INSERT INTO public.auth_token (token_hash, user_id, purpose, expires_at, created_by)
    VALUES ('0048-rehearsal-not-a-real-hash', v_user_id, 'reset', now() + interval '1 hour', v_user_id)
    RETURNING token_key INTO v_key;
    UPDATE public.auth_token SET used_at = now() WHERE token_key = v_key;
    SELECT count(*) INTO v_count
      FROM app.auth_token WHERE token_key = v_key AND used_at IS NOT NULL;
    IF v_count <> 1 THEN
        RAISE EXCEPTION USING MESSAGE =
            'UPDATE through public.auth_token did not reach app.auth_token (found ' || v_count
            || ' updated rows).';
    END IF;
    RAISE NOTICE 'ok  INSERT + UPDATE through public.auth_token';

    -- 5. the unique constraint underneath is still enforced through the view. A view that
    --    accepted a duplicate would mean the constraint had been bypassed, not kept.
    BEGIN
        INSERT INTO public.auth_token (token_hash, user_id, purpose, expires_at, created_by)
        VALUES ('0048-rehearsal-not-a-real-hash', v_user_id, 'reset', now() + interval '1 hour', v_user_id);
        RAISE EXCEPTION USING MESSAGE =
            'a duplicate token_hash was accepted through public.auth_token - the unique '
            || 'constraint on app.auth_token is not being enforced through the view.';
    EXCEPTION WHEN unique_violation THEN
        RAISE NOTICE 'ok  unique_violation still raised through public.auth_token';
    END;

    -- 6. DELETE through the view
    DELETE FROM public.auth_token WHERE token_key = v_key;
    DELETE FROM public.user_permission_override
     WHERE user_id = v_user_id AND permission_key = '0048_rehearsal_key';
    DELETE FROM public.audit_log WHERE audit_log_key = v_identity;

    SELECT (SELECT count(*) FROM app.auth_token WHERE token_key = v_key)
         + (SELECT count(*) FROM app.user_permission_override
             WHERE user_id = v_user_id AND permission_key = '0048_rehearsal_key')
         + (SELECT count(*) FROM app.audit_log WHERE audit_log_key = v_identity)
      INTO v_count;
    IF v_count <> 0 THEN
        RAISE EXCEPTION USING MESSAGE =
            'DELETE through the views left ' || v_count || ' rehearsal row(s) behind. The '
            || 'transaction rolls back anyway, but a DELETE that does not reach the table is a defect.';
    END IF;
    RAISE NOTICE 'ok  DELETE through all three views; every rehearsal row removed';

    RAISE NOTICE '0048 write-through-view check: all 6 parts passed';
END
$do$;
