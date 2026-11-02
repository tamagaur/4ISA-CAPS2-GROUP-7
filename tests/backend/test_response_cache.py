"""
tests/backend/test_response_cache.py — backend/response_cache.py and what feeds it.

The cache key holds the user's effective permission set, so a response built for a
user with lp.view (LP figures included) can never be served to one without it; the
data version read with the session check clears it; preview mode is never cached.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import deps, permissions, response_cache
from backend.auth_utils import TokenPayload, create_access_token
from backend.data_mode import PREVIEW, REAL
from backend.deps import get_current_user, get_db
from backend.main import app
from tests.backend.test_dashboard import FakeSession


@pytest.fixture(autouse=True)
def _empty_cache():
    response_cache.invalidate()
    yield
    response_cache.invalidate()


class _Db:
    def __init__(self, version):
        self.info = {"data_version": version}


def _user(*keys):
    return TokenPayload(user_id=1, email="a@x", role="staff", full_name="A", permissions=frozenset(keys))


def _route():
    calls = []

    @response_cache.cached("GET /thing")
    def route(principal=None, mode=REAL, db=None, current_user=None):
        calls.append(principal)
        return {"principal": principal, "n": len(calls)}

    return route, calls


def test_same_request_same_permissions_is_served_from_memory():
    route, calls = _route()
    hits = response_cache.stats()["hits"]
    first = route(principal="unilever", db=_Db("v1"), current_user=_user("dashboard.view"))
    again = route(principal="unilever", db=_Db("v1"), current_user=_user("dashboard.view"))
    assert again is first and calls == ["unilever"]
    assert response_cache.stats()["hits"] == hits + 1


def test_parameters_and_permission_sets_have_entries_of_their_own():
    route, calls = _route()
    route(principal="unilever", db=_Db("v1"), current_user=_user("dashboard.view", "lp.view"))
    route(principal="delmonte", db=_Db("v1"), current_user=_user("dashboard.view", "lp.view"))
    route(principal="unilever", db=_Db("v1"), current_user=_user("dashboard.view"))
    assert calls == ["unilever", "delmonte", "unilever"]


def test_a_new_data_version_clears_every_entry():
    route, calls = _route()
    route(principal="unilever", db=_Db("v1"), current_user=_user("dashboard.view"))
    route(principal="unilever", db=_Db("v2"), current_user=_user("dashboard.view"))
    assert calls == ["unilever", "unilever"]
    assert response_cache.stats()["entries"] == 1


def test_an_app_write_clears_it_at_once():
    route, calls = _route()
    route(principal="unilever", db=_Db("v1"), current_user=_user("dashboard.view"))
    response_cache.invalidate()
    route(principal="unilever", db=_Db("v1"), current_user=_user("dashboard.view"))
    assert calls == ["unilever", "unilever"]


@pytest.mark.parametrize("db, user, mode", [
    (_Db(None), _user("dashboard.view"), REAL),                     # no data version (before 0041)
    (_Db("v1"), TokenPayload(1, "a@x", "staff", "A"), REAL),         # permissions not read with the session
    (_Db("v1"), _user("dashboard.view"), PREVIEW),                  # preview reads files too
])
def test_not_cached_without_a_version_a_permission_set_or_in_preview(db, user, mode):
    route, calls = _route()
    route(principal="unilever", mode=mode, db=db, current_user=user)
    route(principal="unilever", mode=mode, db=db, current_user=user)
    assert calls == ["unilever", "unilever"]


def test_the_dashboard_never_serves_lp_figures_to_a_user_without_lp_view():
    """An admin's dashboard (LP figures in) is cached; a staff user without lp.view,
    same data version, same range, gets the LP-stripped page, not the cached one."""
    staff_without_lp = frozenset(permissions.PRESETS["staff"]) - {"lp.view"}
    who = {}

    def current_user():
        return who["user"]

    def fake_db():
        db = FakeSession(recommendation_count=7)
        db.info["data_version"] = "v1"
        yield db

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = current_user
    before = response_cache.stats()
    try:
        with TestClient(app) as c:
            headers = {"Authorization": f"Bearer {create_access_token(user_id=1, email='a@x', role='admin', full_name='A')}"}
            url = "/dashboard?period=2026-02&start_period=2025-03&principal=unilever"
            who["user"] = TokenPayload(1, "a@x", "admin", "A", permissions=frozenset(permissions.ALL_KEYS))
            admin = c.get(url, headers=headers).json()
            who["user"] = TokenPayload(2, "s@x", "staff", "S", permissions=staff_without_lp)
            staff = c.get(url, headers=headers).json()
            who["user"] = TokenPayload(1, "a@x", "admin", "A", permissions=frozenset(permissions.ALL_KEYS))
            admin_again = c.get(url, headers=headers).json()
    finally:
        app.dependency_overrides.clear()
    assert admin["lp_hidden"] is False and admin["recommendations"]["product_count"] == 7
    assert staff["lp_hidden"] is True and staff["recommendations"]["product_count"] is None
    assert staff["reorder_preview"] is None and staff["lp"] is None
    assert admin_again == admin
    after = response_cache.stats()
    assert after["entries"] == 2  # one per permission set
    assert (after["hits"] - before["hits"], after["misses"] - before["misses"]) == (1, 2)


# ---- the session check that feeds the key (backend/deps.py) ------------------

def test_the_session_check_reads_permissions_and_the_version_once_their_tables_are_known(monkeypatch):
    class Db:
        info = {"read_request": True}

    monkeypatch.setattr(permissions, "permissions_ready_known", lambda: True)
    from backend import marts
    monkeypatch.setattr(marts, "present_known", lambda: True)
    sql = deps._principal_sql(Db())
    assert "FROM users u" in sql and "LEFT JOIN user_session s" in sql
    assert "AS permission_overrides" in sql and "AS data_version" in sql

    Db.info = {"read_request": False}  # a write: nothing is cached, so no version
    assert "data_version" not in deps._principal_sql(Db())

    monkeypatch.setattr(permissions, "permissions_ready_known", lambda: False)
    monkeypatch.setattr(marts, "present_known", lambda: False)
    Db.info = {"read_request": True}
    assert deps._principal_sql(Db()) == deps.ACTIVE_PRINCIPAL_SQL.format(extra="")


def test_the_permission_set_comes_from_the_database_row_not_the_token():
    class Db:
        info: dict = {}

    token = TokenPayload(5, "s@x", "admin", "S", session_id="abc")  # the token claims admin
    row = {"email": "s@x", "full_name": "S", "role": "staff", "session_id": "abc",
           "permission_overrides": {"lp.view": False, "audit_log.view": True}, "data_version": "v9"}
    db = Db()
    user = deps._principal_from_row(db, token, row)
    assert user.role == "staff"
    assert user.permissions == frozenset(set(permissions.PRESETS["staff"]) - {"lp.view"} | {"audit_log.view"})
    assert permissions.permissions_for(db, user) == set(user.permissions)
    assert db.info["data_version"] == "v9"


def test_get_requests_read_through_the_autocommit_pool(monkeypatch):
    """GET/HEAD: no BEGIN or ROLLBACK round trips. Anything else, and a caller
    outside a request, keeps the transactional pool. No connection is opened:
    create_engine connects on first use."""
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql+psycopg2://u:p@localhost:1/none")
    for name in ("_engine", "_read_engine", "_SessionLocal", "_ReadSessionLocal"):
        monkeypatch.setattr(deps, name, None)

    class Req:
        def __init__(self, method):
            self.method = method

    def session_for(request):
        gen = deps.get_db(request)
        db = next(gen)
        gen.close()
        return db

    for method, autocommit in (("GET", True), ("HEAD", True), ("POST", False), ("PATCH", False)):
        db = session_for(Req(method))
        # create_engine(isolation_level=...) is applied to each new connection from here.
        level = db.get_bind().dialect._on_connect_isolation_level
        assert (level == "AUTOCOMMIT") is autocommit, method
        assert db.info["read_request"] is autocommit
    assert session_for(None).info["read_request"] is False
    assert deps._get_engine().pool._pre_ping is False
    assert deps._get_read_engine().pool._pre_ping is False


def test_every_dashboard_range_card_is_cached_and_keyed_by_endpoint_and_permissions():
    """D4 (2026-10-28): GET /dashboard/<card> took 0.4 to 10 s a request. Each route in dashboard_range is behind
    @cached, whose key is endpoint + every query/path parameter + the effective permission set (tests above), so a
    response built for a user with lp.view is never served to one without it."""
    from backend.routers import dashboard_range
    routes = [r for r in dashboard_range.router.routes if hasattr(r, "endpoint")]
    assert len(routes) == 12
    uncached = [r.path for r in routes if not hasattr(r.endpoint, "cache_endpoint")]
    assert not uncached, f"range cards served without the cache: {uncached}"
    assert len({r.endpoint.cache_endpoint for r in routes}) == len(routes), "two cards share one cache endpoint name"


def test_the_data_version_the_cache_clears_on_moves_with_an_etl_load_and_an_lp_run():
    """The version is the marts' refresh status as JSON (backend/deps.DATA_VERSION_COLUMN); mart.refresh_status carries
    latest_load (etl_load_event) and latest_lp_run (lp_run), so a new load or LP run changes it and clears every entry."""
    assert "row_to_json(r)::text FROM mart.refresh_status r" in deps.DATA_VERSION_COLUMN
    view = open("analytics/db/migrations/0061_planning_stale_review_flags.sql", encoding="utf-8").read()
    assert "SELECT MAX(finished_at) FROM etl_load_event" in view and "SELECT MAX(created_at) FROM lp_run" in view
    assert "src.latest_load" in view and "src.latest_lp_run" in view
