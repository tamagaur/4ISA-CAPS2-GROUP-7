-- 0071_user_notification.sql - the notification bell: an admin is told a staff request is waiting, and the staff
-- member is told when an admin approves or rejects it. 2026-10-28.
--
-- One row per recipient per event, never deleted. Written in the SAME transaction as the request or decision it is
-- about (backend/notifications.py), so a request and its notifications cannot come apart.
--   kind                     quantity_change_requested | dismissal_requested       (to every admin but the requester)
--                            quantity_change_approved | quantity_change_rejected   (to the requester)
--                            dismissal_approved | dismissal_rejected               (to the requester)
--   quantity_change_key /
--   dismissal_request_key    the request it is about (exactly one is set)
--   actor_email              who did it: the requester, or the admin who decided
--   summary                  a short line built from the request's own fields (SKU, quantities), no free text
--   read_at                  NULL until the recipient opens it or marks it read
-- Reading a notification sets read_at and nothing else: the request's state lives only on its own row.
-- The unique indexes make a repeated write for the same recipient, event and request a no-op (ON CONFLICT DO NOTHING).
--
-- recipient_user_id has no foreign key, as lp_direct_apply_grant.user_id (0068): users are app.users behind the
-- public.users view (0048). This migration does not touch app.users, so public.users is not re-created.
-- Depends on 0068 (lp_quantity_change) and 0070 (lp_dismissal_request).
--
-- Additive only. Expected on apply: 0 rows written, no existing row changed.
-- Until it is applied the bell answers ready=false and requests and decisions behave exactly as before.
--
-- Rollback: DROP TABLE IF EXISTS user_notification.
--           DELETE FROM schema_migrations WHERE filename = '0071_user_notification.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)

CREATE TABLE IF NOT EXISTS user_notification (
    notification_key       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipient_user_id      BIGINT NOT NULL,
    kind                   TEXT NOT NULL CHECK (kind IN (
                               'quantity_change_requested', 'dismissal_requested',
                               'quantity_change_approved', 'quantity_change_rejected',
                               'dismissal_approved', 'dismissal_rejected')),
    quantity_change_key    BIGINT REFERENCES lp_quantity_change (change_key),
    dismissal_request_key  BIGINT REFERENCES lp_dismissal_request (request_key),
    actor_email            TEXT NOT NULL,
    summary                TEXT NOT NULL CHECK (length(btrim(summary)) > 0),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at                TIMESTAMPTZ,
    CONSTRAINT ck_user_notification_one_request CHECK (
        (quantity_change_key IS NOT NULL AND dismissal_request_key IS NULL AND kind LIKE 'quantity_change_%')
        OR (dismissal_request_key IS NOT NULL AND quantity_change_key IS NULL AND kind LIKE 'dismissal_%'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_user_notification_change
    ON user_notification (recipient_user_id, kind, quantity_change_key) WHERE quantity_change_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_user_notification_dismissal
    ON user_notification (recipient_user_id, kind, dismissal_request_key) WHERE dismissal_request_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_user_notification_inbox
    ON user_notification (recipient_user_id, created_at DESC);

ALTER TABLE user_notification ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE user_notification IS
    'The notification bell: one row per recipient per staff request or decision (backend/notifications.py). read_at is the recipient''s own read mark and never changes the request. Never deleted.';
