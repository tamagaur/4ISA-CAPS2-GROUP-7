"""
tests/backend/test_abc.py — GET /abc (backend/routers/abc.py).

Backlog #40, #42, #43, #44. Uses a FakeSession (same pattern as
tests/backend/test_auth.py's) so these never touch a real Supabase
instance.

UNILEVER ONLY (2026-09): GET /abc no longer accepts a ?principal= param —
every query is hardcoded to principal='unilever' in the SQL text itself.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
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

    def first(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """Matches only the query shapes backend/routers/abc.py actually issues."""

    def __init__(self, rows, latest_period):
        self.rows = rows
        self.latest_period = latest_period

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        if "MAX(classification_period)" in sql:
            return FakeResult([{"p": self.latest_period}])
        if "FROM abc_classification ac" in sql:
            period = params["period"]
            matched = [r for r in self.rows if r["_period"] == period]
            return FakeResult(matched)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


@pytest.fixture
def sample_rows():
    return [
        {"sku_id": "SKU-A", "product_name": "Product A", "principal": "unilever", "tier": "A", "revenue_share": 0.60,
         "cumulative_share": 0.60, "boundary_flag": False, "current_stock": 120, "reorder_point": None, "_period": "2024-02"},
        {"sku_id": "SKU-B", "product_name": "Product B", "principal": "unilever", "tier": "B", "revenue_share": 0.20,
         "cumulative_share": 0.80, "boundary_flag": True, "current_stock": 40, "reorder_point": None, "_period": "2024-02"},
        {"sku_id": "SKU-C", "product_name": "Product C", "principal": "unilever", "tier": "C", "revenue_share": 0.05,
         "cumulative_share": 0.99, "boundary_flag": False, "current_stock": 0, "reorder_point": None, "_period": "2024-02"},
    ]


@pytest.fixture
def client(sample_rows):
    session = FakeSession(sample_rows, latest_period="2024-02")
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def user_token():
    return auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="staff", full_name="Staff")


def test_requires_auth(sample_rows):
    session = FakeSession(sample_rows, latest_period="2024-02")
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        resp = c.get("/abc")
    app.dependency_overrides.clear()
    assert resp.status_code == 401


def test_returns_all_items_for_latest_period_by_default(client):
    resp = client.get("/abc", headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["classification_period"] == "2024-02"
    assert body["count"] == 3
    assert {i["sku_id"] for i in body["items"]} == {"SKU-A", "SKU-B", "SKU-C"}


def test_boundary_flag_passed_through(client):
    """Backlog #43."""
    resp = client.get("/abc", headers={"Authorization": f"Bearer {user_token()}"})
    items = {i["sku_id"]: i for i in resp.json()["items"]}
    assert items["SKU-B"]["boundary_flag"] is True
    assert items["SKU-A"]["boundary_flag"] is False


def test_tier_summary_rolls_up_correctly(client):
    """Backlog #44: cumulative revenue contribution per tier, computed
    server-side so the dashboard never has to sum client-side."""
    resp = client.get("/abc", headers={"Authorization": f"Bearer {user_token()}"})
    summary = {t["tier"]: t for t in resp.json()["tier_summary"]}
    assert summary["A"]["sku_count"] == 1
    assert summary["A"]["revenue_share_total"] == pytest.approx(0.60)
    assert summary["B"]["sku_count"] == 1
    assert summary["C"]["sku_count"] == 1


def test_empty_when_no_classification_rows_exist():
    session = FakeSession(rows=[], latest_period=None)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        resp = c.get("/abc", headers={"Authorization": f"Bearer {user_token()}"})
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["count"] == 0
    assert body["classification_period"] is None
