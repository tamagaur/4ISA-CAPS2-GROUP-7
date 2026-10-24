"""POST/PATCH /sku must not answer 200/201 for a write it ignored (QA 2026-10-24, finding 1).

unit_price, lead_time_days and status are refused with a 422 that names them;
notes is saved. Nothing is written for a refused request.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.routers import sku as sku_router

from tests.backend.test_sku import FakeResult, make_session, sample_rows, jwt_env  # noqa: F401


class WritableSession:
    """test_sku's FakeSession plus the few write-path statements /sku issues."""

    def __init__(self, inner):
        self.inner = inner
        self.writes: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if sql.lstrip().startswith(("INSERT", "UPDATE")):
            self.writes.append((sql, dict(params or {})))
            return FakeResult([{"product_key": 1, "sku_id": "U-1"}])
        if sql.lstrip().startswith("SELECT product_name, pack_size, brand, notes"):
            return FakeResult([{"product_name": "Uni One", "pack_size": None, "brand": None, "notes": None, "grain": "sku"}])
        if sql.lstrip().startswith("SELECT 1 FROM product_dimension"):
            return FakeResult([])
        return self.inner.execute(stmt, params)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def session(sample_rows):  # noqa: F811
    return WritableSession(make_session(sample_rows))


@pytest.fixture
def admin_client(session, monkeypatch):
    monkeypatch.setattr(sku_router.audit, "record", lambda *a, **k: None)
    monkeypatch.setattr(sku_router.planning_mart, "refresh", lambda *a, **k: None)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=2, email="admin@ssmcapstone.com", role="admin", full_name="Admin")
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


REFUSED = [("unit_price", -5), ("unit_price", 12.5), ("lead_time_days", -3), ("lead_time_days", 5),
           ("status", "DISABLED")]
NEW = {"sku_code": "99999998", "principal": "unilever", "product_name": "q"}


@pytest.mark.parametrize("field,value", REFUSED)
def test_patch_refuses_a_field_it_does_not_save(admin_client, session, field, value):
    resp = admin_client.patch("/sku/1", json={field: value})
    assert resp.status_code == 422
    assert field in resp.json()["detail"]
    assert session.writes == []


@pytest.mark.parametrize("field,value", [("unit_price", -5), ("unit_price", 12.5), ("lead_time_days", 5)])
def test_post_refuses_a_field_it_does_not_save(admin_client, session, field, value):
    resp = admin_client.post("/sku", json={**NEW, field: value})
    assert resp.status_code == 422
    assert field in resp.json()["detail"]
    assert session.writes == []


def test_patch_names_every_refused_field_at_once(admin_client):
    resp = admin_client.patch("/sku/1", json={"unit_price": 1, "lead_time_days": 2, "status": "DISABLED"})
    assert resp.status_code == 422
    for field in ("unit_price", "lead_time_days", "status"):
        assert field in resp.json()["detail"]


def test_patch_still_400s_on_a_status_outside_the_two_values(admin_client):
    assert admin_client.patch("/sku/1", json={"status": "GONE"}).status_code == 400


def test_a_null_for_a_refused_field_is_not_a_write(admin_client, session):
    """A client that echoes the whole record with nulls is not trying to set them."""
    resp = admin_client.patch("/sku/1", json={"unit_price": None, "lead_time_days": None, "status": None})
    assert resp.status_code == 200
    assert session.writes == []


def test_patch_saves_notes(admin_client, session):
    resp = admin_client.patch("/sku/1", json={"notes": "supplier changed the case size"})
    assert resp.status_code == 200
    (sql, params), = session.writes
    assert "notes = :notes" in sql and params["notes"] == "supplier changed the case size"


def test_post_saves_notes(admin_client, session):
    resp = admin_client.post("/sku", json={**NEW, "notes": "new line"})
    assert resp.status_code == 201
    (sql, params), = session.writes
    assert ":notes" in sql and params["notes"] == "new line"
