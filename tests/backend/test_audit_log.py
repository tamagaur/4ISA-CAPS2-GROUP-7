"""
tests/backend/test_audit_log.py — GET /audit-log/users (backend/routers/audit_log.py).

The Audit Log page's per-user summary: one row per user with sign-in count
and longest session, read from user_session (migration 0023). Admin-only,
like GET /audit-log. The
aggregation itself is SQL (grouping, FULL OUTER JOIN to users, ordering), so
this FakeSession returns rows already in the shape the query produces; the
query is checked against real Postgres by running it in a rolled-back
transaction, not here.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError

from backend import auth_utils
from backend.deps import get_db
from backend.main import app


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows=None, missing_table=False, log_rows=None, log_error=False):
        self.rows = rows or []
        self.log_error = log_error
        self.missing_table = missing_table
        self.rolled_back = False
        # audit_log rows for GET /audit-log, newest first.
        self.log_rows = log_rows or []
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, dict(params)))
        if "SELECT * FROM audit_log" in sql:
            if self.log_error:
                raise ProgrammingError(sql, params, Exception("connection reset"))
            rows = [r for r in self.log_rows if r["action"] not in params.get("exclude_action", [])]
            return FakeResult(rows[: params["limit"]])
        if "FROM user_session" in sql:
            if self.missing_table:
                raise ProgrammingError(sql, params, Exception('relation "user_session" does not exist'))
            return FakeResult(self.rows)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def staff_token():
    return auth_utils.create_access_token(
        user_id=2, email="staff@ssmcapstone.com", role="staff", full_name="Staff User"
    )


def admin_token():
    return auth_utils.create_access_token(
        user_id=1, email="admin@ssmcapstone.com", role="admin", full_name="Admin User"
    )




def _get(session, headers=None):
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        resp = c.get("/audit-log/users", headers=headers or {})
    app.dependency_overrides.clear()
    return resp


T0 = datetime.datetime(2026, 9, 21, 1, 0, tzinfo=datetime.timezone.utc)

SUMMARY_ROWS = [
    {"user_email": "admin@ssmcapstone.com", "user_name": "Admin User", "role": "admin",
     "login_count": 40, "timed_session_count": 3, "longest_session_seconds": 5400.0,
     "longest_session_started_at": T0, "last_login_at": T0},
    # Signed in, but only before session tracking: counted, no length.
    {"user_email": "staff@ssmcapstone.com", "user_name": "Staff User", "role": "staff",
     "login_count": 17, "timed_session_count": 0, "longest_session_seconds": None,
     "longest_session_started_at": None, "last_login_at": T0},
    # Never signed in.
    {"user_email": "new@ssmcapstone.com", "user_name": "New User", "role": "staff",
     "login_count": 0, "timed_session_count": 0, "longest_session_seconds": None,
     "longest_session_started_at": None, "last_login_at": None},
]


def test_requires_auth():
    assert _get(FakeSession(SUMMARY_ROWS)).status_code == 401


@pytest.mark.parametrize("path", ["/audit-log/users", "/audit-log"])
def test_staff_cannot_read_the_audit_log(path):
    """The Audit Log page is admin-only; the API enforces it, not just the
    hidden sidebar link."""
    app.dependency_overrides[get_db] = lambda: FakeSession(SUMMARY_ROWS)
    with TestClient(app) as c:
        resp = c.get(path, headers={"Authorization": f"Bearer {staff_token()}"})
    app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_one_row_per_user_in_query_order():
    resp = _get(FakeSession(SUMMARY_ROWS), {"Authorization": f"Bearer {admin_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert [i["user_email"] for i in body["items"]] == [r["user_email"] for r in SUMMARY_ROWS]
    top = body["items"][0]
    assert top["login_count"] == 40
    assert top["longest_session_seconds"] == 5400.0


def test_unmeasured_and_never_signed_in_users_keep_null_lengths():
    body = _get(FakeSession(SUMMARY_ROWS), {"Authorization": f"Bearer {admin_token()}"}).json()
    staff, new = body["items"][1], body["items"][2]
    assert staff["login_count"] == 17 and staff["longest_session_seconds"] is None
    assert new["login_count"] == 0 and new["last_login_at"] is None


def test_missing_session_table_is_a_503_not_an_empty_list():
    """An empty list would read as 'nobody has signed in'."""
    session = FakeSession(missing_table=True)
    resp = _get(session, {"Authorization": f"Bearer {admin_token()}"})
    assert resp.status_code == 503
    assert "0023" in resp.json()["detail"]
    assert session.rolled_back


# ---- GET /audit-log: the Recent changes list --------------------------------


def _log(key, action, minutes_ago, details=None):
    return {"audit_log_key": key, "user_email": "admin@ssmcapstone.com", "user_name": "Admin User",
            "role": "admin", "action": action, "details": details,
            "created_at": T0 - datetime.timedelta(minutes=minutes_ago)}


LOG_ROWS = [  # newest first, as ORDER BY created_at DESC returns them
    _log(5, "Login", 1),
    _log(4, "Edit SKU", 2, "Updated SKU 123"),
    _log(3, "Login", 3),
    _log(2, "Reorder Recommendation Dismissed", 4, "SKU 9: overstocked"),
    _log(1, "Logout", 5),
]


def test_recent_changes_leaves_out_sign_ins():
    session = FakeSession(log_rows=LOG_ROWS)
    resp = _get_path(session, "/audit-log?exclude_action=Login&exclude_action=Logout&limit=10")
    assert resp.status_code == 200
    assert [i["action"] for i in resp.json()["items"]] == ["Edit SKU", "Reorder Recommendation Dismissed"]
    sql, params = session.calls[-1]
    assert "action <> ALL(:exclude_action)" in sql
    assert params["exclude_action"] == ["Login", "Logout"]


def test_recent_changes_respects_the_limit():
    session = FakeSession(log_rows=LOG_ROWS)
    body = _get_path(session, "/audit-log?exclude_action=Login&exclude_action=Logout&limit=1").json()
    assert [i["audit_log_key"] for i in body["items"]] == [4]


def test_log_without_exclusions_is_unchanged():
    session = FakeSession(log_rows=LOG_ROWS)
    body = _get_path(session, "/audit-log?limit=10").json()
    assert body["count"] == 5
    assert "exclude_action" not in session.calls[-1][1]


def _get_path(session, path):
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        resp = c.get(path, headers={"Authorization": f"Bearer {admin_token()}"})
    app.dependency_overrides.clear()
    return resp


def test_audit_log_read_error_is_a_503_not_an_empty_list():
    """An empty list would read as 'No changes recorded yet' (2026-10-02)."""
    session = FakeSession(log_error=True)
    resp = _get_path(session, "/audit-log?limit=10")
    assert resp.status_code == 503
    assert "couldn't be read" in resp.json()["detail"]
    assert session.rolled_back


def test_summary_states_the_span_the_counts_cover():
    """A sign-in count with no period read as "ever" (2026-10-03): the
    response carries the first and latest recorded sign-in across users."""
    t_first = datetime.datetime(2026, 8, 23, 9, 28, tzinfo=datetime.timezone.utc)
    rows = [
        {**SUMMARY_ROWS[0], "first_login_at": t_first},
        {**SUMMARY_ROWS[1], "first_login_at": T0},
        {**SUMMARY_ROWS[2], "first_login_at": None},
    ]
    body = _get(FakeSession(rows), {"Authorization": f"Bearer {admin_token()}"}).json()
    assert body["first_login_at"].startswith("2026-08-23T09:28")
    assert body["last_login_at"].startswith("2026-09-21T01:00")
    assert body["items"][0]["first_login_at"].startswith("2026-08-23")


def test_summary_query_reads_each_users_first_sign_in():
    session = FakeSession(SUMMARY_ROWS)
    _get(session, {"Authorization": f"Bearer {admin_token()}"})
    sql = next(s for s, _ in session.calls if "FROM user_session" in s)
    assert "MIN(started_at) AS first_login_at" in sql and "s.first_login_at" in sql


def test_session_length_sql_caps_at_last_activity_plus_the_idle_limit():
    """D1 (2026-10-28): a revoked or backfilled row read as 1,277 hours. The summary caps a session at its last
    activity + SESSION_IDLE_MINUTES and leaves a row with no recorded activity untimed."""
    from backend.routers.audit_log import USER_SUMMARY_SQL
    assert "last_seen_at + make_interval(mins => :cap_minutes)" in USER_SUMMARY_SQL
    assert "WHEN last_seen_at IS NULL THEN NULL" in USER_SUMMARY_SQL
    assert "COALESCE(ended_at, last_seen_at) - started_at" not in USER_SUMMARY_SQL, "the uncapped length is back"
