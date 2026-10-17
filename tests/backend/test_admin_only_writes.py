"""
tests/backend/test_admin_only_writes.py — the endpoints that change shared
data need a write permission (backend/permissions.py; deps.require_admin until
2026-09-30): POST /sku and PATCH /sku/{key} need sku.edit, PATCH
/recommendations/{key} needs lp.decide.

Staff have neither, so they get the contract's 403 before any query runs: the
NoQuerySession here fails the test if one is issued. Admins have
both; each of their cases sends a body the endpoint rejects with 400 on its
own validation, which proves the request got past the permission check
without needing a database.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.permissions import MISSING_PERMISSION


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


class NoQuerySession:
    def execute(self, stmt, params=None):
        raise AssertionError(f"No query should run for this request: {stmt}")

    def rollback(self):
        pass

    def close(self):
        pass


def _token(role):
    return auth_utils.create_access_token(
        user_id=1, email=f"{role}@ssmcapstone.com", role=role, full_name=role.title()
    )


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: NoQuerySession()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# (method, path, permission it needs, body the endpoint rejects with 400 once past the check)
WRITES = [
    ("POST", "/sku", "sku.edit", {"sku_code": "X-1", "product_name": "X", "principal": "delmonte"}),
    ("PATCH", "/sku/1", "sku.edit", {"status": "NOT-A-STATUS"}),
    ("PATCH", "/recommendations/1", "lp.decide", {"status": "maybe"}),
]


@pytest.mark.parametrize("method,path,permission,body", WRITES)
def test_staff_cannot_write(client, method, path, permission, body):
    resp = client.request(method, path, json=body, headers={"Authorization": f"Bearer {_token('staff')}"})
    assert resp.status_code == 403
    assert resp.json() == {"detail": MISSING_PERMISSION, "code": "missing_permission", "permission": permission}


@pytest.mark.parametrize("method,path,permission,body", WRITES)
def test_admin_passes_the_permission_check(client, method, path, permission, body):
    resp = client.request(method, path, json=body, headers={"Authorization": f"Bearer {_token('admin')}"})
    assert resp.status_code == 400, resp.text


@pytest.mark.parametrize("method,path,permission,body", WRITES)
def test_writes_still_require_a_token(client, method, path, permission, body):
    assert client.request(method, path, json=body).status_code == 401


def test_staff_can_still_read(client):
    """GET /sku opens with any of the four pages that read product names
    (SKU Management, ABC, Reorder, SKU Forecast), all in the staff preset,
    so staff keep reading it (2026-10-02; it was sign-in only before).
    Checked on the route table rather than by calling it, which would need
    the SKU query faked. Walks the SKU router itself: fastapi 0.141 keeps an
    included router as one nested entry in app.routes instead of copying its
    routes up, and main.py adds no dependencies when it includes a router."""
    from backend.routers import sku

    for route in sku.router.routes:
        if getattr(route, "path", None) == "/sku" and "GET" in route.methods:
            calls = [d.call for d in route.dependant.dependencies]
            keys = next(set(call.permission_keys) for call in calls if hasattr(call, "permission_keys"))
            assert keys == {"sku.view", "abc.view", "lp.view", "forecast.view"}
            return
    pytest.fail("GET /sku route not found")
