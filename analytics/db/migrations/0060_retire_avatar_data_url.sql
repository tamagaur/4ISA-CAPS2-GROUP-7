-- 0060_retire_avatar_data_url.sql — drops app.users.avatar_data_url: base64 image bytes in a
-- column are retired in favor of Supabase Storage (app.users.avatar_path, migration 0059).
--
-- WHY
--   0058_user_profile_picture.sql put the picture itself in Postgres as a data URL. By the time
--   this was noticed (merge of kelvin/merge-main-final-conflict, 2026-10-18) 0058 was already
--   applied to the live database, so deleting its file would not remove the column — a column
--   can only be un-applied by a migration, never by deleting the file that added it. 0058 is
--   therefore left exactly as applied; this file undoes its effect instead.
--   The reason to undo it: every data URL is read back out on every GET /auth/me and stored
--   again on every PATCH, so the row (and the page) carries the full image bytes, uncacheable —
--   roughly 400 MB/month even for one small image — against a Supabase free-tier egress budget
--   that was at 4.63 of 5 GB. Storage serves the same picture from its own URL, cacheable, and
--   never touches a Postgres row to do it. backend/avatar.py and backend/routers/users.py
--   already write POST /users/me/avatar's picture there, to avatar_path (0059); this migration
--   makes avatar_path the ONLY place a picture lives, for both entry points — PATCH /auth/me is
--   changed (not here, in backend/profile.py and backend/routers/auth.py) to decode the incoming
--   data URL, run it through the same validation, resize and Storage upload as the POST route,
--   and store the resulting path here too, never the bytes.
--
-- public.users must again list the COMPLETE current column set of app.users (see 0059's
-- comment on the same bug): after this file, that set is user_id, email, password_hash, role,
-- created_at, full_name, avatar_path — avatar_data_url removed.
--
-- No existing avatar_data_url value is migrated to Storage: every row is NULL in production
-- today (0058 only just reached the database, before any frontend wrote to it), so there is
-- nothing to carry over. If that stops being true before this runs, re-check with
-- `SELECT count(*) FROM app.users WHERE avatar_data_url IS NOT NULL` first.
--
-- Rollback: ALTER TABLE app.users ADD COLUMN avatar_data_url text (plus 0058's CHECK
--           constraint), then CREATE OR REPLACE VIEW public.users as in 0059 (with
--           avatar_data_url restored). The dropped column's data cannot be restored.

ALTER TABLE app.users DROP COLUMN IF EXISTS avatar_data_url;

CREATE OR REPLACE VIEW public.users WITH (security_invoker = true) AS
    SELECT user_id, email, password_hash, role, created_at, full_name, avatar_path
      FROM app.users;

COMMENT ON VIEW public.users IS
    'Compatibility view onto app.users (0048, DEC-39 group 1; avatar_path added by 0059; '
    'avatar_data_url added by 0058 and retired by this file — Storage only, see 0059). '
    'security_invoker, no grants to the API roles. Temporary bridge for unqualified references; '
    'dropped once the app module names app.users directly (plan section 5 group 5). MUST list '
    'every column of app.users: tests/backend/test_migrations.py enforces this.';
