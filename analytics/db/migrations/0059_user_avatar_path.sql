-- 0059_user_avatar_path.sql — app.users.avatar_path: a Storage object path, not image bytes.
--
-- RENUMBERED FROM 0058 (merge of kelvin/merge-main-final-conflict, 2026-10-18): this file and
-- Audrey's 0058_user_profile_picture.sql were both written as "0058" independently and collided
-- on the same number (caught by scripts/run_canonical_load._assert_no_new_number_collision).
-- Audrey's file reached the live database first (schema_migrations.applied_at 2026-10-16 11:01Z,
-- confirmed from the ledger before this merge touched anything) and is left exactly as applied —
-- a migration already live is never edited or renumbered. This one was never applied (also
-- confirmed from the ledger), so it is the one that moves, to the next free number. See
-- 0060_retire_avatar_data_url.sql for how the two columns this leaves on app.users (0058's
-- avatar_data_url, this file's avatar_path) are reconciled into Supabase Storage only.
--
-- WHY
--   Profile pictures are added to the backend. Per the project's Supabase free-tier egress
--   budget (4.63/5 GB used at the time this was written), image bytes are never stored in
--   Postgres and never served through the API from the database: the file lives in Supabase
--   Storage (bucket `avatars`), and this column holds only its storage path. NULLABLE, no
--   default: every existing account has no picture today and must keep working unchanged.
--
-- app.users, NOT public.users: migration 0048 (DEC-39) moved the real table to schema `app`
-- and left public.users as a compatibility view with an explicit column list ("A column added
-- to app.users is invisible here until this view is re-created" — 0048's own comment on
-- public.users). This migration adds the column to app.users and re-creates the view with the
-- COMPLETE current column set of app.users (this is the bug 0058 and this file collided on:
-- each migration listing only its own column means whichever applies second silently drops the
-- other's). At this point in the migration order avatar_data_url (0058) already exists and
-- avatar_data_url is not yet dropped (0060 does that), so both appear here. CREATE OR REPLACE
-- VIEW keeps the view's OID and existing ACL (anon, authenticated and service_role stay revoked
-- from it; no re-GRANT is issued here).
--
-- Rollback: CREATE OR REPLACE VIEW public.users back to the 7-column list from 0058
--           (…, avatar_data_url), then ALTER TABLE app.users DROP COLUMN avatar_path.

ALTER TABLE app.users ADD COLUMN IF NOT EXISTS avatar_path TEXT;

COMMENT ON COLUMN app.users.avatar_path IS
    'Path of the account''s profile picture inside the Supabase Storage "avatars" bucket '
    '(e.g. "<user_id>/<random>.webp"). NULL = no picture, frontend shows the initials '
    'fallback. Never image bytes. Set only by POST /users/me/avatar (backend/avatar.py) and, '
    'from 0060, PATCH /auth/me too, to a 128x128 WebP re-encoded from the upload. Migration 0059.';

CREATE OR REPLACE VIEW public.users WITH (security_invoker = true) AS
    SELECT user_id, email, password_hash, role, created_at, full_name, avatar_data_url, avatar_path
      FROM app.users;

COMMENT ON VIEW public.users IS
    'Compatibility view onto app.users (0048, DEC-39 group 1; avatar_data_url added by 0058, '
    'avatar_path by 0059 — see 0060 for avatar_data_url''s retirement). security_invoker, no '
    'grants to the API roles. Temporary bridge for unqualified references; dropped once the app '
    'module names app.users directly (plan section 5 group 5). MUST list every column of '
    'app.users: a migration that lists only its own column silently drops whichever other '
    'column the previous migration added (the 0058/0059 numbering collision this file was '
    'renumbered to fix). tests/backend/test_migrations.py enforces this.';
