"""
tests/backend/test_permissions.py — the backend half of Yuan's permissions
proposal (revised 2026-09-30): backend/permissions.py, GET /auth/me and the
/admin permission endpoints (backend/routers/permissions.py).

Kelvin's review conditions, and where each is checked:
  - per-request database check: test_an_unticked_box_applies_on_the_next_request,
    test_the_role_comes_from_the_database_not_the_token
  - any-of keys: test_any_of_keys_passes_on_either, and the page smoke test
  - LP fields stripped server-side: the ..._without_lp_view tests in
    test_dashboard.py, test_abc.py and test_sku.py
  - page smoke test: test_every_page_works_for_each_preset_with_any_one_box_unticked
    and test_each_page_works_on_its_own_permission_alone
  - Postman-style: no, malformed, expired, tampered, foreign-key and unsigned
    tokens get 401; self-promotion is refused (the SELF-PROMOTION section)
  - safe to deploy before migration 0034: the BEFORE MIGRATION 0034 section

No test touches a database. FakeStore holds the users table and
user_permission_override in memory and answers the permission queries.
"""
from __future__ import annotations

import base64
import json
import pathlib
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend import auth_utils, permissions
from backend.api_errors import ApiError, api_error_handler
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.permissions import (
    ALL_KEYS, CATALOG, MISSING_PERMISSION, NOT_READY, PRESETS, effective, normalize, preset, require_permission,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
SECRET = "test-only-secret-do-not-use-in-prod"
CREATED = datetime(2026, 9, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def token(user_id: int, role: str) -> str:
    return auth_utils.create_access_token(
        user_id=user_id, email=f"user{user_id}@ssmcapstone.com", role=role,
        full_name=f"User {user_id}", session_id=f"s-{user_id}",
    )


def auth(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {token(user_id, role)}"}


def user(user_id: int, role: str) -> dict:
    return {"user_id": user_id, "email": f"user{user_id}@ssmcapstone.com", "full_name": f"User {user_id}",
            "role": role, "created_at": CREATED}


def team() -> list[dict]:
    """One admin (1) and two staff (2, 3), like the live table today."""
    return [user(1, "admin"), user(2, "staff"), user(3, "staff")]


class Result:
    def __init__(self, rows=(), scalar=None):
        self._rows = list(rows)
        self._scalar = scalar
        self.rowcount = len(self._rows)

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    fetchall = all

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._rows)


class FakeStore:
    """The users table and user_permission_override, in memory. strict=True
    fails the test on any other query; strict=False answers it with no rows,
    for tests that only look at whether a request got past the permission
    check (the endpoint behind it may then 200, 404, 422 or 500 on the empty
    data, which is not what they test)."""

    def __init__(self, users, overrides=None, *, table_exists=True, strict=True):
        self.users = {u["user_id"]: dict(u) for u in users}
        self.overrides = {uid: dict(o) for uid, o in (overrides or {}).items()}
        self.table_exists = table_exists
        self.strict = strict
        self.queries: list[str] = []
        self.audit: list[dict] = []
        self.revoked: list[int] = []
        self.commits = 0

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = dict(params or {})
        self.queries.append(sql)
        if sql == "SELECT to_regclass('public.user_permission_override') IS NOT NULL":
            return Result(scalar=self.table_exists)
        if sql.startswith("SELECT permission_key, granted FROM user_permission_override"):
            assert self.table_exists, "read user_permission_override before migration 0034 created it"
            return Result(rows=list(self.overrides.get(p["user_id"], {}).items()))
        if "FROM users u LEFT JOIN user_session s" in sql:  # deps.ACTIVE_PRINCIPAL_SQL
            u = self.users.get(p["user_id"])
            if u is None:
                return Result()
            return Result([{"email": u["email"], "full_name": u["full_name"], "role": u["role"],
                            "session_id": p["session_id"], "ended_at": None, "idle": False}])
        if "FROM users WHERE role = 'admin' FOR UPDATE" in sql:
            return Result(scalar=sum(u["role"] == "admin" for u in self.users.values()))
        if sql.startswith("SELECT") and sql.endswith("FROM users WHERE user_id = :user_id"):
            u = self.users.get(p["user_id"])
            return Result([{**u, "status": "active"}] if u else [])
        if sql == "UPDATE users SET role = :role WHERE user_id = :user_id":
            self.users[p["user_id"]]["role"] = p["role"]
            return Result()
        if sql == "DELETE FROM user_permission_override WHERE user_id = :user_id":
            self.overrides.pop(p["user_id"], None)
            return Result()
        if sql.startswith("INSERT INTO user_permission_override"):
            assert p["set_by"] is not None
            self.overrides.setdefault(p["user_id"], {})[p["key"]] = p["granted"]
            return Result()
        if "end_reason = 'revoked'" in sql:
            self.revoked.append(p["user_id"])
            return Result()
        if sql.startswith("INSERT INTO audit_log"):
            self.audit.append(p)
            return Result()
        if self.strict:
            raise AssertionError(f"Unexpected query: {sql}")
        return Result()

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


@contextmanager
def client_for(store: FakeStore, *, raise_errors: bool = True):
    # get_db is overridden before the app starts, so its startup database
    # check is skipped (backend/main.py lifespan).
    app.dependency_overrides[get_db] = lambda: store
    with TestClient(app, raise_server_exceptions=raise_errors) as c:
        yield c
    app.dependency_overrides.clear()


def missing(permission: str) -> dict:
    return {"detail": MISSING_PERMISSION, "code": "missing_permission", "permission": permission}


# ═══ THE RULE ════════════════════════════════════════════════════════════════

def test_admin_has_everything_and_overrides_do_not_apply():
    assert effective("admin", {"lp.view": False, "users.manage": False}) == set(ALL_KEYS)
    assert normalize("admin", {"lp.view": False}) == {}


def test_role_preset_plus_grants_minus_removals():
    staff = set(PRESETS["staff"])
    assert effective("staff", {}) == staff
    assert effective("staff", {"audit_log.view": True, "lp.view": False}) == (staff | {"audit_log.view"}) - {"lp.view"}


def test_only_differences_from_the_preset_are_stored():
    assert normalize("staff", {"lp.view": True, "audit_log.view": True, "sku.edit": False}) == {"audit_log.view": True}
    assert normalize("staff", {"lp.view": False}) == {"lp.view": False}


def test_deny_by_default():
    """A key outside the catalog grants nothing, and a role without a preset has nothing."""
    assert effective("staff", {"everything.all": True}) == set(PRESETS["staff"])
    assert preset("superuser") == set() and effective("superuser", {"lp.view": True}) == {"lp.view"}


def test_require_permission_only_takes_catalog_keys():
    with pytest.raises(ValueError):
        require_permission("lp.veiw")
    with pytest.raises(ValueError):
        require_permission()


def test_the_presets_are_the_proposals_design_table():
    staff = {"dashboard.view", "abc.view", "forecast.view", "category_trends.view", "sku.view", "lp.view"}
    assert set(PRESETS["staff"]) == staff
    assert set(PRESETS) == {"staff"}  # admin has everything; there is no Manager
    assert len(ALL_KEYS) == len(set(ALL_KEYS)) == 11


# ═══ THE FRONTEND'S COPY MATCHES ═════════════════════════════════════════════
# The frontend reads the catalog from GET /admin/permissions/catalog, but keeps
# a copy for its legacy mode (before /auth/me exists) and its dev mock.

KEYS_JS = (REPO / "frontend/src/permissions/keys.js").read_text(encoding="utf-8")
MOCK_JS = (REPO / "frontend/src/api/mocks/permissionsMock.js").read_text(encoding="utf-8")
FRONTEND_P = dict(re.findall(r"^\s+(\w+): '([a-z_]+\.[a-z_]+)',$",
                             re.search(r"export const P = \{(.*?)\};", KEYS_JS, re.S).group(1), re.M))


def _p_names(block: str) -> set[str]:
    return {FRONTEND_P[name] for name in re.findall(r"P\.(\w+)", block)}


def test_frontend_keys_are_the_catalog():
    assert sorted(FRONTEND_P.values()) == sorted(ALL_KEYS)


def test_frontend_legacy_catalog_matches_word_for_word():
    entries = re.findall(
        r"\{ key: P\.(\w+), label: '([^']*)', group: '([^']*)', description: '([^']*)' \}", KEYS_JS
    )
    assert [{"key": FRONTEND_P[n], "label": l, "group": g, "description": d} for n, l, g, d in entries] == CATALOG


def test_frontend_legacy_staff_access_is_the_staff_preset():
    block = re.search(r"export const LEGACY_STAFF_ACCESS = \[(.*?)\];", KEYS_JS, re.S).group(1)
    assert _p_names(block) == set(PRESETS["staff"])


def test_frontend_dev_mock_presets_match():
    assert not re.search(r"^\s+manager:", MOCK_JS, re.M)
    for role in ("staff",):
        block = re.search(rf"^\s+{role}: \[(.*?)\],$", MOCK_JS, re.M).group(1)
        assert set(re.findall(r"'([a-z_]+\.[a-z_]+)'", block)) == set(PRESETS[role]), role


# ═══ EVERY ROUTE IS GUARDED ══════════════════════════════════════════════════
# A new route fails test_every_route_is_guarded until it declares its
# permission or is added to one of these two lists on purpose.

SIGN_IN_ONLY = {
    ("GET", "/auth/me"), ("POST", "/auth/heartbeat"), ("POST", "/auth/logout"),
    ("GET", "/data-mode"),  # the data-mode banner on every page
    # Your own two-step sign-in (backend/routers/two_factor.py).
    ("GET", "/auth/mfa"), ("POST", "/auth/mfa/setup"), ("POST", "/auth/mfa/confirm"),
    ("POST", "/auth/mfa/recovery-codes"), ("POST", "/auth/mfa/disable"),
}
PUBLIC = {
    ("POST", "/auth/login"), ("GET", "/auth/forgot-password"), ("POST", "/auth/forgot-password"),
    # Sign-in's second step: carries the 5-minute mfa_token instead of a session.
    ("POST", "/auth/login/verify"), ("POST", "/auth/login/setup"), ("POST", "/auth/login/setup/confirm"),
    ("POST", "/auth/link-info"), ("POST", "/auth/set-password"), ("GET", "/status"), ("GET", "/health"),
}


def _dependency_calls(dependant) -> list:
    calls = []
    for dep in dependant.dependencies:
        calls.append(dep.call)
        calls.extend(_dependency_calls(dep))
    return calls


def _api_routes():
    """Every API route the app serves, as served (prefix and include-level
    dependencies applied). fastapi 0.141 keeps an included router as one
    nested entry in app.routes instead of copying its routes up, so a flat
    walk finds none of them; the nested entry lists them through
    effective_route_contexts(), which also recurses into routers it includes."""
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "effective_route_contexts"):
            for context in route.effective_route_contexts():
                if isinstance(context.original_route, APIRoute):
                    yield context


def _routes():
    for route in _api_routes():
        calls = _dependency_calls(route.dependant)
        keys = [call.permission_keys for call in calls if hasattr(call, "permission_keys")]
        for method in route.methods:
            yield method, route.path, keys, calls


# Method/path pairs the app serves: 37 = what a flat app.routes walk found under
# fastapi 0.115.5 at the UIFixes_Audrey merge (2026-10-02), plus the 9 two-step
# sign-in routes (/auth/login/verify, /auth/login/setup[/confirm], /auth/mfa*,
# /users/{user_id}/mfa/reset) merged in 2026-10-03, plus the seven GET /dashboard/*
# range routes the data marts added (2026-10-04/05). Change it when a route is
# added or removed.
ROUTE_COUNT = 53


def test_the_walk_finds_every_route():
    """Guards the walk itself: one that finds nothing passes
    test_every_route_is_guarded on an empty list, which the flat walk did
    after the fastapi 0.141 upgrade."""
    assert len(set((method, path) for method, path, _, _ in _routes())) == ROUTE_COUNT


def test_every_route_is_guarded():
    unguarded = []
    for method, path, keys, calls in _routes():
        if keys or (method, path) in PUBLIC:
            continue
        if (method, path) in SIGN_IN_ONLY:
            assert get_current_user in calls, f"{method} {path} is listed as sign-in only but has no sign-in check"
            continue
        unguarded.append(f"{method} {path}")
    assert unguarded == []


def test_the_lists_name_real_routes():
    routes = {(method, path) for method, path, _, _ in _routes()}
    assert SIGN_IN_ONLY <= routes and PUBLIC <= routes


# Before 2026-09-30 these needed an admin; every other route needed sign-in only.
ADMIN_ONLY_BEFORE = {
    ("POST", "/auth/register"), ("GET", "/users"), ("PATCH", "/users/{user_id}"),
    ("DELETE", "/users/{user_id}"), ("POST", "/users/{user_id}/send-link"),
    ("POST", "/sku"), ("PATCH", "/sku/{product_key}"), ("PATCH", "/recommendations/{recommendation_key}"),
    ("GET", "/audit-log"), ("GET", "/audit-log/users"),
}
NEW_ROUTES = {("GET", "/admin/permissions/catalog"), ("GET", "/admin/users/{user_id}/permissions"),
              ("PUT", "/admin/users/{user_id}/permissions"),
              ("POST", "/users/{user_id}/mfa/reset")}  # 2026-10-02, users.manage like the rest of /users


def test_the_staff_preset_opens_exactly_what_staff_could_open_before():
    """Why deploying this code changes nobody's access until an admin ticks
    a box: staff = today's staff, admin = everything."""
    staff = preset("staff")
    for method, path, keys, _ in _routes():
        if not keys or (method, path) in NEW_ROUTES:
            continue
        opens = all(set(any_of) & staff for any_of in keys)
        assert opens == ((method, path) not in ADMIN_ONLY_BEFORE), f"{method} {path}"


# ═══ THE 403 CONTRACT AND ANY-OF KEYS ════════════════════════════════════════

@pytest.fixture
def probe():
    """A one-route app guarded by require_permission("forecast.view", "lp.view")."""
    probe_app = FastAPI()
    probe_app.add_exception_handler(ApiError, api_error_handler)

    @probe_app.get("/probe")
    def _probe(current_user=Depends(require_permission("forecast.view", "lp.view"))):
        return {"user_id": current_user.user_id}

    probe_app.dependency_overrides[get_db] = lambda: None
    with TestClient(probe_app) as c:
        yield c


def test_any_of_keys_passes_on_either(probe, monkeypatch):
    staff = auth(2, "staff")
    assert probe.get("/probe", headers=staff).status_code == 200
    monkeypatch.setattr(permissions, "load_overrides", lambda db, user_id: {"lp.view": False})
    assert probe.get("/probe", headers=staff).status_code == 200
    monkeypatch.setattr(permissions, "load_overrides", lambda db, user_id: {"forecast.view": False})
    assert probe.get("/probe", headers=staff).status_code == 200


def test_the_403_names_the_first_key(probe, monkeypatch):
    monkeypatch.setattr(permissions, "load_overrides",
                        lambda db, user_id: {"forecast.view": False, "lp.view": False})
    resp = probe.get("/probe", headers=auth(2, "staff"))
    assert resp.status_code == 403
    assert resp.json() == missing("forecast.view")


# ═══ PER-REQUEST DATABASE CHECK ══════════════════════════════════════════════

@pytest.mark.real_permission_store
def test_an_unticked_box_applies_on_the_next_request():
    """Nothing about permissions is in the token: the same token loses LP on
    its very next request after the admin saves, and gets it back after."""
    store = FakeStore(team(), strict=False)
    staff, admin = auth(2, "staff"), auth(1, "admin")
    with client_for(store, raise_errors=False) as c:
        assert "lp.view" in c.get("/auth/me", headers=staff).json()["permissions"]
        assert c.get("/recommendations", headers=staff).status_code != 403

        saved = c.put("/admin/users/2/permissions", json={"role": "staff", "overrides": {"lp.view": False}},
                      headers=admin)
        assert saved.status_code == 200
        assert "lp.view" not in c.get("/auth/me", headers=staff).json()["permissions"]
        denied = c.get("/recommendations", headers=staff)
        assert denied.status_code == 403 and denied.json() == missing("lp.view")

        c.put("/admin/users/2/permissions", json={"role": "staff", "overrides": {}}, headers=admin)
        assert c.get("/recommendations", headers=staff).status_code != 403
    assert store.revoked == []  # ticks alone sign nobody out


@pytest.mark.real_session_check
@pytest.mark.real_permission_store
def test_the_role_comes_from_the_database_not_the_token():
    """A token still saying admin, for an account the database says is staff
    (demoted after signing in), gets staff's access."""
    store = FakeStore(team())
    with client_for(store) as c:
        resp = c.get("/users", headers=auth(2, "admin"))
        me = c.get("/auth/me", headers=auth(2, "admin")).json()
    assert resp.status_code == 403 and resp.json() == missing("users.manage")
    assert me["role"] == "staff" and "users.manage" not in me["permissions"]


# ═══ GET /auth/me ════════════════════════════════════════════════════════════

@pytest.mark.real_permission_store
def test_me_lists_the_effective_permissions():
    store = FakeStore(team(), overrides={2: {"audit_log.view": True, "lp.view": False}})
    with client_for(store) as c:
        body = c.get("/auth/me", headers=auth(2, "staff")).json()
    assert body == {
        "user_id": 2, "email": "user2@ssmcapstone.com", "full_name": "User 2", "role": "staff",
        "permissions": sorted((set(PRESETS["staff"]) | {"audit_log.view"}) - {"lp.view"}),
    }


@pytest.mark.real_permission_store
def test_me_for_an_admin_lists_everything():
    with client_for(FakeStore(team())) as c:
        assert c.get("/auth/me", headers=auth(1, "admin")).json()["permissions"] == sorted(ALL_KEYS)


# ═══ THE ADMIN ENDPOINTS ═════════════════════════════════════════════════════

@pytest.mark.real_permission_store
def test_catalog_for_an_admin():
    with client_for(FakeStore(team())) as c:
        body = c.get("/admin/permissions/catalog", headers=auth(1, "admin")).json()
    assert body["permissions"] == CATALOG
    assert body["roles"] == {"admin": "all", "staff": list(PRESETS["staff"])}


@pytest.mark.real_permission_store
@pytest.mark.parametrize("method,path", [
    ("GET", "/admin/permissions/catalog"), ("GET", "/admin/users/3/permissions"), ("PUT", "/admin/users/3/permissions"),
])
def test_the_admin_endpoints_need_users_manage(method, path):
    store = FakeStore(team())
    with client_for(store) as c:
        resp = c.request(method, path, json={"role": "admin"}, headers=auth(2, "staff"))
    assert resp.status_code == 403 and resp.json() == missing("users.manage")
    assert store.users[3]["role"] == "staff" and store.commits == 0


@pytest.mark.real_permission_store
def test_get_user_permissions():
    store = FakeStore(team(), overrides={2: {"audit_log.view": True}})
    with client_for(store) as c:
        body = c.get("/admin/users/2/permissions", headers=auth(1, "admin")).json()
    assert body == {"user_id": 2, "role": "staff", "overrides": {"audit_log.view": True},
                    "permissions": sorted(set(PRESETS["staff"]) | {"audit_log.view"})}


@pytest.mark.real_permission_store
@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_unknown_user_is_404(method):
    with client_for(FakeStore(team())) as c:
        resp = c.request(method, "/admin/users/99/permissions", json={"role": "staff"}, headers=auth(1, "admin"))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "User not found.", "code": "user_not_found"}


@pytest.mark.real_permission_store
def test_put_stores_only_the_differences_and_is_audited():
    store = FakeStore(team())
    body = {"role": "staff", "overrides": {"lp.view": True, "audit_log.view": True, "sku.view": False}}
    with client_for(store) as c:
        resp = c.put("/admin/users/2/permissions", json=body, headers=auth(1, "admin"))
    assert resp.status_code == 200
    assert resp.json()["overrides"] == {"audit_log.view": True, "sku.view": False}
    assert store.overrides[2] == {"audit_log.view": True, "sku.view": False}
    (entry,) = store.audit
    assert entry["action"] == "Change Access" and entry["user_email"] == "user1@ssmcapstone.com"
    assert entry["details"] == "user2@ssmcapstone.com: role staff → staff; overrides none → +audit_log.view, -sku.view"
    assert store.commits == 1
    assert store.revoked == []


@pytest.mark.real_permission_store
def test_a_role_change_signs_the_user_out_like_edit_user_does():
    store = FakeStore(team(), overrides={2: {"audit_log.view": True}})
    with client_for(store) as c:
        resp = c.put("/admin/users/2/permissions", json={"role": "admin"}, headers=auth(1, "admin"))
    assert resp.status_code == 200
    assert resp.json() == {"user_id": 2, "role": "admin", "overrides": {}, "permissions": sorted(ALL_KEYS)}
    assert store.users[2]["role"] == "admin" and 2 not in store.overrides
    assert store.revoked == [2]
    assert store.audit[0]["details"] == "user2@ssmcapstone.com: role staff → admin; overrides +audit_log.view → none"


@pytest.mark.real_permission_store
def test_saving_with_nothing_changed_writes_no_audit_entry():
    store = FakeStore(team(), overrides={2: {"audit_log.view": True}})
    with client_for(store) as c:
        resp = c.put("/admin/users/2/permissions", json={"role": "staff", "overrides": {"audit_log.view": True}},
                     headers=auth(1, "admin"))
    assert resp.status_code == 200 and store.audit == [] and store.overrides[2] == {"audit_log.view": True}


@pytest.mark.real_permission_store
def test_an_unknown_permission_is_422_and_nothing_is_written():
    store = FakeStore(team())
    with client_for(store) as c:
        resp = c.put("/admin/users/2/permissions", json={"role": "staff", "overrides": {"everything.all": True}},
                     headers=auth(1, "admin"))
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Unknown permission.", "code": "unknown_permission", "permission": "everything.all"}
    assert store.overrides == {} and store.commits == 0


@pytest.mark.real_permission_store
@pytest.mark.parametrize("body", [
    {"role": "superuser"}, {"role": "staff", "permissions": ["lp.view"]}, {"overrides": {}},
    {"role": "staff", "overrides": {"lp.view": "yes please"}},
])
def test_a_malformed_body_is_422(body):
    store = FakeStore(team())
    with client_for(store) as c:
        assert c.put("/admin/users/2/permissions", json=body, headers=auth(1, "admin")).status_code == 422
    assert store.commits == 0


@pytest.mark.real_permission_store
def test_one_of_two_admins_can_be_demoted():
    store = FakeStore([user(1, "admin"), user(2, "admin")])
    with client_for(store) as c:
        resp = c.put("/admin/users/2/permissions", json={"role": "staff"}, headers=auth(1, "admin"))
    assert resp.status_code == 200 and store.users[2]["role"] == "staff"


@pytest.mark.real_permission_store
def test_the_last_admin_cannot_be_demoted_or_deleted():
    """users.manage can be given to someone who isn't an admin; they still
    can't remove the only admin, by any of the three routes."""
    store = FakeStore(team(), overrides={2: {"users.manage": True}})
    manager_of_users = auth(2, "staff")
    last_admin = {"detail": "There must be at least one admin.", "code": "last_admin"}
    with client_for(store) as c:
        put = c.put("/admin/users/1/permissions", json={"role": "staff"}, headers=manager_of_users)
        patch = c.patch("/users/1", json={"role": "staff"}, headers=manager_of_users)
        delete = c.delete("/users/1", headers=manager_of_users)
    for resp in (put, patch, delete):
        assert resp.status_code == 409 and resp.json() == last_admin
    assert store.users[1]["role"] == "admin" and store.commits == 0


# ═══ POSTMAN-STYLE: TOKENS ═══════════════════════════════════════════════════
# The requests Postman would send by hand, each against the endpoints that
# matter most: who am I, a data page, and the two ways to change access.

PROTECTED = [
    ("GET", "/auth/me"), ("GET", "/dashboard"), ("GET", "/users"),
    ("GET", "/admin/permissions/catalog"), ("PUT", "/admin/users/2/permissions"), ("PATCH", "/users/2"),
]


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _claims(tok: str) -> dict:
    part = tok.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def _tampered(tok: str, **changes) -> str:
    """The same token with its claims edited and the original signature kept."""
    header, _, signature = tok.split(".")
    return f"{header}.{_b64({**_claims(tok), **changes})}.{signature}"


def _expired() -> str:
    claims = {**_claims(token(1, "admin")), "exp": int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())}
    return jwt.encode(claims, SECRET, algorithm="HS256")


BAD_TOKENS = [
    "no header", "no Bearer prefix", "garbage", "expired",
    "tampered: staff edited to admin", "signed with another key", "unsigned (alg none)",
]


def _bad_header(kind: str) -> dict:
    """Built per test: tokens need the test's JWT settings."""
    if kind == "no header":
        return {}
    if kind == "no Bearer prefix":
        return {"Authorization": token(1, "admin")}
    if kind == "garbage":
        return {"Authorization": "Bearer not-a-jwt"}
    if kind == "expired":
        return {"Authorization": f"Bearer {_expired()}"}
    if kind == "tampered: staff edited to admin":
        return {"Authorization": f"Bearer {_tampered(token(2, 'staff'), role='admin', sub='1')}"}
    if kind == "signed with another key":
        return {"Authorization": f"Bearer {jwt.encode(_claims(token(1, 'admin')), 'attacker-key', algorithm='HS256')}"}
    if kind == "unsigned (alg none)":
        return {"Authorization": f"Bearer {_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(_claims(token(1, 'admin')))}."}
    raise ValueError(kind)


@pytest.mark.real_session_check
@pytest.mark.real_permission_store
@pytest.mark.parametrize("kind", BAD_TOKENS)
@pytest.mark.parametrize("method,path", PROTECTED)
def test_postman_a_missing_or_bad_token_is_401(kind, method, path):
    store = FakeStore(team())
    with client_for(store) as c:
        resp = c.request(method, path, json={"role": "admin"}, headers=_bad_header(kind))
    assert resp.status_code == 401, resp.text
    assert store.users[2]["role"] == "staff" and store.commits == 0


def test_postman_an_expired_token_says_so():
    app.dependency_overrides[get_db] = lambda: FakeStore(team())
    with TestClient(app) as c:
        resp = c.get("/auth/me", headers=_bad_header("expired"))
    assert resp.json() == {"detail": "Invalid or expired token."}


# ═══ POSTMAN-STYLE: SELF-PROMOTION ═══════════════════════════════════════════

@pytest.mark.real_permission_store
@pytest.mark.parametrize("method,path,body", [
    ("PUT", "/admin/users/2/permissions", {"role": "admin"}),
    ("PUT", "/admin/users/2/permissions", {"role": "staff", "overrides": {"users.manage": True}}),
    ("PATCH", "/users/2", {"role": "admin"}),
    ("POST", "/auth/register", {"email": "me.again@ssmcapstone.com", "full_name": "Me Again", "role": "admin"}),
])
def test_postman_staff_cannot_promote_themselves(method, path, body):
    store = FakeStore(team())
    with client_for(store) as c:
        resp = c.request(method, path, json=body, headers=auth(2, "staff"))
    assert resp.status_code == 403 and resp.json() == missing("users.manage")
    assert store.users[2]["role"] == "staff" and store.overrides == {} and store.commits == 0


@pytest.mark.real_permission_store
@pytest.mark.parametrize("body", [
    {"role": "admin", "overrides": {}},
    {"role": "staff", "overrides": {"users.manage": True, "sku.edit": True}},
    {"role": "staff", "overrides": {"users.manage": True, "audit_log.view": True}},
])
def test_postman_someone_given_users_manage_cannot_widen_their_own_access(body):
    store = FakeStore(team(), overrides={2: {"users.manage": True}})
    with client_for(store) as c:
        resp = c.put("/admin/users/2/permissions", json=body, headers=auth(2, "staff"))
        patch = c.patch("/users/2", json={"role": "admin"}, headers=auth(2, "staff"))
    assert resp.status_code == 409
    assert resp.json() == {"detail": "You can't change your own access. Ask another admin.", "code": "self_promotion"}
    assert patch.status_code == 400  # Edit User: "You can't change your own role."
    assert store.users[2]["role"] == "staff" and store.overrides == {2: {"users.manage": True}}
    assert store.audit == [] and store.commits == 0


@pytest.mark.real_permission_store
@pytest.mark.parametrize("acting,body", [
    (1, {"role": "staff"}),                                    # the admin demoting themselves
    (2, {"role": "staff", "overrides": {}}),                   # removing their own users.manage
])
def test_nobody_can_lock_themselves_out(acting, body):
    store = FakeStore([user(1, "admin"), user(2, "staff"), user(4, "admin")], overrides={2: {"users.manage": True}})
    with client_for(store) as c:
        resp = c.put(f"/admin/users/{acting}/permissions", json=body,
                     headers=auth(acting, store.users[acting]["role"]))
    assert resp.status_code == 409
    assert resp.json() == {"detail": "You can't remove your own admin access.", "code": "self_lockout"}
    assert store.commits == 0


@pytest.mark.real_permission_store
def test_saving_your_own_access_unchanged_is_allowed():
    store = FakeStore(team())
    with client_for(store) as c:
        resp = c.put("/admin/users/1/permissions", json={"role": "admin", "overrides": {"lp.view": False}},
                     headers=auth(1, "admin"))
    assert resp.status_code == 200 and resp.json()["permissions"] == sorted(ALL_KEYS)
    assert store.audit == []


# ═══ BEFORE MIGRATION 0034 IS APPLIED ════════════════════════════════════════

@pytest.mark.real_permission_store
def test_before_0034_me_is_404_so_the_frontend_keeps_todays_access():
    with client_for(FakeStore(team(), table_exists=False)) as c:
        resp = c.get("/auth/me", headers=auth(2, "staff"))
    assert resp.status_code == 404
    assert resp.json() == {"detail": NOT_READY, "code": "permissions_not_ready"}


@pytest.mark.real_permission_store
@pytest.mark.parametrize("method,path", [
    ("GET", "/admin/permissions/catalog"), ("GET", "/admin/users/2/permissions"), ("PUT", "/admin/users/2/permissions"),
])
def test_before_0034_the_admin_endpoints_are_503(method, path):
    store = FakeStore(team(), table_exists=False)
    with client_for(store) as c:
        resp = c.request(method, path, json={"role": "staff"}, headers=auth(1, "admin"))
    assert resp.status_code == 503
    assert resp.json() == {"detail": NOT_READY, "code": "permissions_not_ready"}
    assert store.users[2]["role"] == "staff" and store.commits == 0


@pytest.mark.real_permission_store
@pytest.mark.parametrize("table_exists", [False, True])
@pytest.mark.parametrize("method,path,body", [
    ("POST", "/auth/register", {"email": "new@ssmcapstone.com", "full_name": "New", "role": "manager"}),
    ("PATCH", "/users/2", {"role": "manager"}),
    ("PUT", "/admin/users/2/permissions", {"role": "manager"}),
])
def test_there_is_no_manager_role(method, path, body, table_exists):
    """Two roles only, admin and staff: any other role is refused by request
    validation, before or after 0034, and nothing is written."""
    store = FakeStore(team(), table_exists=table_exists)
    with client_for(store) as c:
        resp = c.request(method, path, json=body, headers=auth(1, "admin"))
    assert resp.status_code == 422
    assert store.users[2]["role"] == "staff" and store.commits == 0


@pytest.mark.real_permission_store
def test_before_0034_access_is_the_role_presets_and_the_table_is_never_read():
    store = FakeStore(team(), table_exists=False, strict=False)
    with client_for(store, raise_errors=False) as c:
        assert c.get("/audit-log", headers=auth(2, "staff")).json() == missing("audit_log.view")
        assert c.get("/recommendations", headers=auth(2, "staff")).status_code != 403
        assert c.get("/audit-log", headers=auth(1, "admin")).status_code != 403
    assert not any("FROM user_permission_override" in q for q in store.queries)


@pytest.mark.real_permission_store
def test_the_readiness_check_is_cached_and_notices_the_migration():
    store = FakeStore(team(), table_exists=False)
    lookups = lambda: sum("to_regclass" in q for q in store.queries)  # noqa: E731

    assert permissions.permissions_ready(store) is False
    assert permissions.permissions_ready(store) is False
    assert lookups() == 1                         # a "no" is reused for a minute

    store.table_exists = True                     # Kelvin applies 0034
    permissions._ready_cache["checked_at"] -= 61  # a minute later
    assert permissions.permissions_ready(store) is True
    assert lookups() == 2

    store.table_exists = False
    assert permissions.permissions_ready(store) is True  # a "yes" is kept for good
    assert lookups() == 2


# ═══ PAGE SMOKE TEST ═════════════════════════════════════════════════════════
# What each page calls when it opens (frontend/src/api/* and the components
# that import them, 2026-09-30), keyed by the permission that shows the page
# (frontend/src/permissions/keys.js PAGES). For each user below, every page
# they can see must load without a 401/403, and every endpoint only a hidden
# page uses must answer 403.

EVERY_PAGE = [("GET", "/auth/me"), ("POST", "/auth/heartbeat"), ("GET", "/data-mode")]
PAGE_ENDPOINTS = {
    "dashboard.view": [("GET", "/dashboard")],
    "forecast.view": [("GET", "/abc"), ("GET", "/forecast/12345678"), ("GET", "/segment?sku=12345678"),
                      ("GET", "/decomposition?sku=12345678"), ("GET", "/sku")],   # + SkuDemandPatternPanel, useBrandLookup
    "category_trends.view": [("GET", "/category-trends")],
    "sku.view": [("GET", "/sku")],
    "abc.view": [("GET", "/abc"), ("GET", "/fsn"), ("GET", "/pareto"), ("GET", "/sku")],  # + AbcBreakdowns, useBrandLookup
    "lp.view": [("GET", "/recommendations"), ("GET", "/segment?sku=12345678"),
                ("GET", "/decomposition?sku=12345678"), ("GET", "/sku")],  # + ReorderModal's panel, useBrandLookup
    "audit_log.view": [("GET", "/audit-log"), ("GET", "/audit-log/users")],
    "upload.run": [],  # Data Management is a mock page: no endpoint yet
    "users.manage": [("GET", "/users"), ("GET", "/admin/permissions/catalog"), ("GET", "/admin/users/3/permissions")],
}
# Buttons: each needs its own permission, whatever page it sits on.
ACTIONS = {
    "sku.edit": [("POST", "/sku", {"sku_code": "X-1", "product_name": "X", "principal": "delmonte"}),
                 ("PATCH", "/sku/1", {"status": "NOT-A-STATUS"})],
    "lp.decide": [("PATCH", "/recommendations/1", {"status": "maybe"})],
    "users.manage": [("POST", "/auth/register", {"email": "n@ssmcapstone.com", "full_name": "N", "role": "staff"}),
                     ("PATCH", "/users/3", {"full_name": "Renamed"}), ("DELETE", "/users/3", None),
                     ("POST", "/users/3/send-link", None), ("PUT", "/admin/users/3/permissions", {"role": "staff"})],
}


def _route_path(method: str, url: str) -> str:
    path = url.split("?")[0]
    for route in _api_routes():
        if method in route.methods and route.path_regex.match(path):
            return route.path
    raise AssertionError(f"no route for {method} {url}")


def _smoke(c, perms: set[str], headers: dict) -> list[str]:
    problems = []
    visible = {(m, u) for key, calls in PAGE_ENDPOINTS.items() if key in perms for m, u in calls}
    for key, calls in PAGE_ENDPOINTS.items():
        for method, url in calls + EVERY_PAGE:
            status = c.request(method, url, headers=headers).status_code
            if key in perms and status in (401, 403):
                problems.append(f"{key} page: {method} {url} -> {status}")
            hidden_only = (method, url) not in visible and (method, _route_path(method, url)) not in SIGN_IN_ONLY
            if hidden_only and status != 403:
                problems.append(f"hidden {key} page: {method} {url} -> {status}, expected 403")
    for key, calls in ACTIONS.items():
        for method, url, body in calls:
            status = c.request(method, url, json=body, headers=headers).status_code
            if (status == 403) == (key in perms):
                problems.append(f"{key} button: {method} {url} -> {status}")
    return problems


def test_the_smoke_map_covers_every_page():
    pages = set(re.findall(r"permission: P\.(\w+) \}", re.search(r"export const PAGES = \[(.*?)\];", KEYS_JS, re.S).group(1)))
    assert {FRONTEND_P[name] for name in pages} == set(PAGE_ENDPOINTS)
    for key, calls in PAGE_ENDPOINTS.items():
        for method, url in calls + EVERY_PAGE:
            _route_path(method, url)  # every listed endpoint exists


@pytest.mark.parametrize("role", ["admin", "staff"])
def test_every_page_works_for_each_preset_with_any_one_box_unticked(role, monkeypatch):
    base = preset(role)
    problems = []
    with client_for(FakeStore([], strict=False), raise_errors=False) as c:
        for unticked in [None, *sorted(base)]:
            overrides = {} if unticked is None else {unticked: False}
            monkeypatch.setattr(permissions, "load_overrides", lambda db, user_id, o=overrides: o)
            label = f"{role} with {unticked or 'nothing'} unticked"
            problems += [f"{label}: {p}" for p in _smoke(c, effective(role, overrides), auth(9, role))]
    assert problems == []


@pytest.mark.parametrize("only", sorted(ALL_KEYS))
def test_each_page_works_on_its_own_permission_alone(only, monkeypatch):
    """The strongest form of any-of: a staff account with every box
    unticked but one still gets that one page (and button) whole."""
    overrides = {key: key == only for key in ALL_KEYS}
    monkeypatch.setattr(permissions, "load_overrides", lambda db, user_id: overrides)
    with client_for(FakeStore([], strict=False), raise_errors=False) as c:
        assert _smoke(c, {only}, auth(9, "staff")) == []


@pytest.mark.real_permission_store
def test_the_product_list_needs_one_of_the_pages_that_read_it():
    """GET /sku opens with any of sku.view, abc.view, lp.view, forecast.view
    (the four pages that read product names), and only with one of them:
    it used to be sign-in only, so someone with none of these pages still
    got the whole catalog with its stock and classes (2026-10-02)."""
    readers = ("sku.view", "abc.view", "lp.view", "forecast.view")
    nothing_else = {key: False for key in PRESETS["staff"] if key in readers}
    with client_for(FakeStore(team(), overrides={2: nothing_else}), raise_errors=False) as c:
        denied = c.get("/sku", headers=auth(2, "staff"))
    assert denied.status_code == 403
    assert denied.json()["code"] == "missing_permission"
    for keep in readers:
        overrides = {key: False for key in readers if key != keep and key in PRESETS["staff"]}
        with client_for(FakeStore(team(), overrides={2: overrides}), raise_errors=False) as c:
            resp = c.get("/sku", headers=auth(2, "staff"))
        assert resp.status_code != 403, keep
