"""
tests/backend/test_notifications.py - the notification bell (migration 0071): backend/notifications.py writes,
backend/routers/notifications.py reads and marks read.

Like the other request tests, the fake session answers by SQL text, so these check which statements run, with what
values, and in what order against the commit. Migration 0071 is NOT applied to the live database: the SQL itself has
not run against Postgres.
"""
from __future__ import annotations

import datetime
import pathlib

import pytest

from backend import notifications
from backend.api_errors import ApiError
from backend.routers import notifications as nr
from backend.schemas.recommendations import DismissalRequestIn, RejectRequest
from tests.backend.test_recommendations import FakeResult
from tests.backend import test_reorder_requests as trr

REPO = pathlib.Path(__file__).resolve().parents[2]
AT = datetime.datetime(2026, 10, 28, 9, 0, tzinfo=datetime.timezone.utc)


class _Bell:
    """A session for the bell routes: `rows` are the caller's notifications."""

    def __init__(self, *, ready=True, rows=(), unread=0, own=True, updated=1):
        self.ready, self.rows, self.unread, self.own, self.updated = ready, list(rows), unread, own, updated
        self.sql: list[tuple[str, dict]] = []
        self.commits = 0

    def execute(self, stmt, params=None):
        raw, params = str(stmt), dict(params or {})
        self.sql.append((raw, params))
        sql = " ".join(raw.split())
        if "to_regclass('user_notification')" in sql:
            return FakeResult([{"ready": self.ready}])
        if sql.startswith("SELECT COUNT(*) AS n FROM user_notification"):
            return FakeResult([{"n": self.unread}])
        if sql.startswith("SELECT read_at FROM user_notification"):
            return FakeResult([{"read_at": None}] if self.own else [])
        if sql.startswith("UPDATE user_notification"):
            return FakeResult([{"notification_key": 1}] * self.updated)
        if "FROM user_notification n" in sql:
            return FakeResult(self.rows)
        return FakeResult([])

    def commit(self):
        self.commits += 1


def _row(**over):
    row = {"notification_key": 1, "kind": "quantity_change_requested", "request_kind": "quantity_change",
           "request_key": 7, "recommendation_key": 1, "sku_code": "U-1", "product_name": "Uni One",
           "actor_email": "staff@ssmcapstone.com", "actor_name": "Staff One", "summary": "SKU U-1: quantity 1 -> 2",
           "created_at": AT, "read_at": None, "request_state": "pending_approval"}
    return {**row, **over}


# ── the routes: own rows only, read changes read_at only ─────────────────────────────────────────────────────

def test_the_list_is_the_callers_own_rows_with_the_unread_count():
    db = _Bell(rows=[_row()], unread=1)
    out = nr.list_notifications(limit=30, db=db, current_user=trr.ADMIN)
    assert out.ready and out.unread_count == 1 and out.items[0].request_state == "pending_approval"
    listing = next(p for s, p in db.sql if "FROM user_notification n" in s)
    assert listing == {"me": trr.ADMIN.user_id, "limit": 30}
    assert "WHERE n.recipient_user_id = :me" in " ".join(next(s for s, _ in db.sql if "FROM user_notification n" in s).split())


def test_before_the_migration_the_bell_is_empty_and_the_writes_answer_503():
    db = _Bell(ready=False)
    out = nr.list_notifications(limit=30, db=db, current_user=trr.STAFF)
    assert not out.ready and out.items == [] and out.unread_count == 0
    for call in (lambda: nr.mark_read(1, db=db, current_user=trr.STAFF),
                 lambda: nr.mark_all_read(db=db, current_user=trr.STAFF)):
        with pytest.raises(ApiError) as err:
            call()
        assert err.value.status_code == 503 and err.value.code == "notifications_not_ready"


def test_someone_elses_notification_is_not_found_and_nothing_is_written():
    db = _Bell(own=False)
    with pytest.raises(ApiError) as err:
        nr.mark_read(5, db=db, current_user=trr.STAFF)
    assert err.value.status_code == 404
    assert not any(s.lstrip().startswith("UPDATE") for s, _ in db.sql) and db.commits == 0


def test_marking_read_sets_read_at_only_never_the_request():
    db = _Bell(unread=0)
    out = nr.mark_read(1, db=db, current_user=trr.ADMIN)
    assert out.updated == 1 and out.unread_count == 0 and db.commits == 1
    updates = [" ".join(s.split()) for s, _ in db.sql if s.lstrip().startswith("UPDATE")]
    assert updates == ["UPDATE user_notification SET read_at = now() WHERE notification_key = :key "
                       "AND recipient_user_id = :me AND read_at IS NULL RETURNING notification_key"]
    db = _Bell(updated=3)
    assert nr.mark_all_read(db=db, current_user=trr.ADMIN).updated == 3
    assert not any("lp_quantity_change" in s or "lp_dismissal_request" in s
                   for s, _ in db.sql if s.lstrip().startswith("UPDATE"))


# ── the writes: inside the request's transaction, to the right people ───────────────────────────────────────

class _Ready(trr._DB):
    """A dismissal-request session with migration 0071 present; records the bell's inserts and when commits run."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.events: list[str] = []
        self.notified: list[dict] = []

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if "to_regclass('user_notification')" in sql:
            self.sql.append((str(stmt), dict(params or {})))
            return FakeResult([{"ready": True}])
        if sql.startswith("INSERT INTO user_notification"):
            self.sql.append((str(stmt), dict(params or {})))
            self.notified.append({**dict(params or {}), "to_admins": "u.role = 'admin'" in sql})
            self.events.append("notify")
            return FakeResult([])
        return super().execute(stmt, params)

    def commit(self):
        self.events.append("commit")
        super().commit()


def test_a_staff_request_notifies_every_admin_but_the_requester_before_the_commit():
    db = _Ready(request=trr._request_row())
    trr.rr.request_dismissal(1, DismissalRequestIn(reason="Still 30 cases"), db=db, current_user=trr.STAFF)
    assert db.events == ["notify", "commit"]
    sent = db.notified[0]
    assert sent["to_admins"] and sent["kind"] == "dismissal_requested" and sent["request_key"] == 4
    assert sent["actor"] == "staff@ssmcapstone.com" and sent["change_key"] is None
    insert = next(s for s, _ in db.sql if s.lstrip().startswith("INSERT INTO user_notification"))
    assert "lower(u.email) <> lower(:actor)" in insert and "ON CONFLICT DO NOTHING" in insert


def test_a_rejection_notifies_the_requester_only():
    db = _Ready(request=trr._request_row())
    trr.rr.reject_dismissal(4, RejectRequest(reason="Stock is fine"), db=db, admin=trr.ADMIN)
    assert db.events[-2:] == ["notify", "commit"]
    sent = db.notified[0]
    assert not sent["to_admins"] and sent["kind"] == "dismissal_rejected"
    assert sent["requester"] == "staff@ssmcapstone.com" and sent["actor"] == "admin@ssmcapstone.com"
    assert sent["summary"] == "SKU U-1: dismissal request rejected"


def test_a_refused_request_writes_no_notification():
    db = _Ready(request=trr._request_row(), insert_wins=False)   # lost the race on the one-open index
    with pytest.raises(Exception):
        trr.rr.request_dismissal(1, DismissalRequestIn(reason="Still 30 cases"), db=db, current_user=trr.STAFF)
    assert db.notified == [] and "commit" not in db.events


def test_without_the_table_requests_and_decisions_run_as_before():
    db = trr._DB(request=trr._request_row())
    trr.rr.request_dismissal(1, DismissalRequestIn(reason="Still 30 cases"), db=db, current_user=trr.STAFF)
    assert db.commits == 1
    assert not any("INSERT INTO user_notification" in s for s, _ in db.sql)


def test_the_summary_is_built_from_the_request_fields_only():
    class _S:
        def __init__(self):
            self.params = None

        def execute(self, stmt, params=None):
            if "to_regclass" in str(stmt):
                return FakeResult([{"ready": True}])
            self.params = params
            return FakeResult([])
    s = _S()
    notifications.request_made(s, kind="quantity_change_requested", actor=trr.STAFF, sku="U-1",
                               recommended=47160.0, proposed=48000.0, change_key=7)
    assert s.params["summary"] == "SKU U-1: quantity 47,160 pcs -> 48,000 pcs"
    assert s.params["change_key"] == 7 and s.params["request_key"] is None


# ── the migration ───────────────────────────────────────────────────────────────────────────────────────────

def test_the_migration_is_additive_and_keeps_one_row_per_recipient_and_event():
    sql = (REPO / "analytics/db/migrations/0071_user_notification.sql").read_text(encoding="utf-8")
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    statements = body.split("COMMENT ON TABLE")[0].upper()   # the table comment's text is prose
    assert not any(word in statements for word in ("DELETE", "DROP", "UPDATE", "TRUNCATE"))
    assert all(";" not in l for l in sql.splitlines() if l.strip().startswith("--"))
    assert "ux_user_notification_change" in sql and "ux_user_notification_dismissal" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    # Every kind the backend writes is one the table accepts.
    for kind in notifications.KINDS:
        assert f"'{kind}'" in sql
