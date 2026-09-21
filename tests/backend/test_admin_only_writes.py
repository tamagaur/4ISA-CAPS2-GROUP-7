"""
tests/backend/test_admin_only_writes.py — deps.require_admin on the endpoints
that change shared data: POST /sku, PATCH /sku/{key}, PATCH /recommendations/{key}.

Staff get 403 before any query runs, so the FakeSession here fails the test
if one is issued. Admins pass the role check; each admin case sends a body
the endpoint rejects with 400 on its own validation, which proves the
request got past require_admin without needing a database.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_db
from backend.main import app


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


# (method, path, body the endpoint rejects with 400 once past the role check)
WRITES = [
    ("POST", "/sku", {"sku_code": "X-1", "product_name": "X", "principal": "delmonte"}),
    ("PATCH", "/sku/1", {"status": "NOT-A-STATUS"}),
    ("PATCH", "/recommendations/1", {"status": "maybe"}),
]


@pytest.mark.parametrize("method,path,body", WRITES)
def test_staff_cannot_write(client, method, path, body):
    resp = client.request(method, path, json=body, headers={"Authorization": f"Bearer {_token('staff')}"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Only an admin account can do this."


@pytest.mark.parametrize("method,path,body", WRITES)
def test_admin_passes_the_role_check(client, method, path, body):
    resp = client.request(method, path, json=body, headers={"Authorization": f"Bearer {_token('admin')}"})
    assert resp.status_code == 400, resp.text


@pytest.mark.parametrize("method,path,body", WRITES)
def test_writes_still_require_a_token(client, method, path, body):
    assert client.request(method, path, json=body).status_code == 401


def test_staff_can_still_read(client):
    """require_admin is only on writes — GET /sku keeps get_current_user.
    Checked on the route table rather than by calling it, which would need
    the SKU query faked."""
    from backend.deps import require_admin

    for route in app.routes:
        if getattr(route, "path", None) == "/sku" and "GET" in route.methods:
            deps = [d.call for d in route.dependant.dependencies]
            assert require_admin not in deps
            return
    pytest.fail("GET /sku route not found")
