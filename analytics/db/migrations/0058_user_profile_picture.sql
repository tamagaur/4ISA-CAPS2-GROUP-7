-- 0058_user_profile_picture.sql — a profile picture on each account, for the My profile page
-- (frontend/src/components/ProfilePage.jsx, PATCH /auth/me; Audrey, 2026-10-16).
--
-- app.users.avatar_data_url: the picture itself, as a data URL ("data:image/jpeg;base64,…"), small
-- on purpose: the browser squares and shrinks it to 192 x 192 before upload (10-30 KB as JPEG), and
-- the API refuses anything over 200,000 characters (backend/profile.py). NULL = no picture, the
-- sidebar shows the person's initials as before. Stored inline rather than in object storage so
-- nothing new has to be hosted, served or secured; a picture is read only through /auth/me, by the
-- account's owner.
--
-- public.users is a compatibility view onto app.users (0048) and "a column added to app.users is
-- invisible here until this view is re-created", so the view is re-created with the new column
-- appended. CREATE OR REPLACE VIEW keeps the view's grants and REVOKEs (0048: nothing for anon,
-- authenticated, service_role) and its security_invoker setting.
--
-- Expected after applying: app.users and public.users gain avatar_data_url, NULL on every row; no
-- row count changes anywhere; GET /auth/me reports profile_pictures: true.
-- Until it is applied the API still works: names can be changed, and a picture upload answers 503
-- profile_pictures_not_ready (backend/profile.py probes information_schema for the column).
-- Rollback: CREATE OR REPLACE VIEW public.users ... without the column is not possible (a view's
-- columns can't be dropped in place), so: DROP VIEW public.users; recreate it as in 0048;
-- ALTER TABLE app.users DROP COLUMN avatar_data_url.

ALTER TABLE app.users
    ADD COLUMN IF NOT EXISTS avatar_data_url text
        CONSTRAINT users_avatar_data_url_small CHECK (
            avatar_data_url IS NULL
            OR (length(avatar_data_url) <= 200000 AND avatar_data_url LIKE 'data:image/%;base64,%')
        );

CREATE OR REPLACE VIEW public.users WITH (security_invoker = true) AS
    SELECT user_id, email, password_hash, role, created_at, full_name, avatar_data_url
      FROM app.users;

COMMENT ON COLUMN app.users.avatar_data_url IS
    'Profile picture as a data URL (image/jpeg|png|webp, base64), 192 x 192 at most, NULL = none. '
    'Set by its owner through PATCH /auth/me (0058).';
