-- 0058_user_avatar_path.sql — app.users.avatar_path: a Storage object path, not image bytes.
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
-- same security_invoker=true plus the new column appended. CREATE OR REPLACE VIEW keeps the
-- view's OID and existing ACL (anon, authenticated and service_role stay revoked from it; no
-- re-GRANT is issued here).
--
-- Rollback: CREATE OR REPLACE VIEW public.users back to the 6-column list from 0048, then
--           ALTER TABLE app.users DROP COLUMN avatar_path.

ALTER TABLE app.users ADD COLUMN IF NOT EXISTS avatar_path TEXT;

COMMENT ON COLUMN app.users.avatar_path IS
    'Path of the account''s profile picture inside the Supabase Storage "avatars" bucket '
    '(e.g. "<user_id>/<random>.webp"). NULL = no picture, frontend shows the initials '
    'fallback. Never image bytes. Set only by POST /users/me/avatar (backend/avatar.py), to '
    'a 128x128 WebP it re-encoded itself from the upload. Migration 0058.';

CREATE OR REPLACE VIEW public.users WITH (security_invoker = true) AS
    SELECT user_id, email, password_hash, role, created_at, full_name, avatar_path
      FROM app.users;

COMMENT ON VIEW public.users IS
    'Compatibility view onto app.users (0048, DEC-39 group 1; avatar_path added by 0058). '
    'security_invoker, no grants to the API roles. Temporary bridge for unqualified '
    'references; dropped once the app module names app.users directly (plan section 5 group 5).';
