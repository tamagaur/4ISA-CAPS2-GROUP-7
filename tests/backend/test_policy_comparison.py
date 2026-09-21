"""
tests/backend/test_policy_comparison.py — GET /policy-comparison (backend/routers/policy_comparison.py).

FakeSession pattern from tests/backend/test_segment.py — never touches
Supabase. Covers the per-SKU rule-vs-LP arithmetic, the roll-up (which must
equal GET /dashboard's policy_comparison), ordering, the honest nulls for
the peso and stockout fields, and the blocked answer when nothing compares.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.routers.dashboard import AVG_WEEKS_PER_MONTH


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


def user_token():
    return auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="staff", full_name="Staff")


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.last_params = None

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.last_params = params or {}
        if "FROM LP_Recommendation lr" in sql and "fr.forecast_date = lr.planning_cycle_date" in sql:
            return FakeResult(self.rows)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


CYCLE = datetime.date(2026, 3, 1)
ROWS = [
    {"planning_cycle_date": CYCLE, "ss_i": 40.0, "forecast_value": 100.0, "sku_id": "A1", "product_name": "SMALL GAP", "principal": "unilever"},
    {"planning_cycle_date": CYCLE, "ss_i": 10.0, "forecast_value": 500.0, "sku_id": "B2", "product_name": "BIG GAP", "principal": "unilever"},
    {"planning_cycle_date": CYCLE, "ss_i": None, "forecast_value": 80.0, "sku_id": "C3", "product_name": "NO SS", "principal": "unilever"},
]


def make_client(session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_requires_auth():
    app.dependency_overrides[get_db] = lambda: FakeSession(ROWS)
    with TestClient(app) as c:
        assert c.get("/policy-comparison").status_code == 401


def test_per_sku_rule_vs_lp_and_rollup():
    with make_client(FakeSession(ROWS)) as c:
        body = c.get("/policy-comparison?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["cycle_date"] == "2026-03-01"
    assert body["rule_weeks"] == 3
    # The row with no ss_i is dropped from BOTH sides, never one.
    assert [i["sku_id"] for i in body["items"]] == ["B2", "A1"]  # biggest gap first
    big = body["items"][0]
    assert big["rule_safety_stock_units"] == pytest.approx(3 * 500.0 / AVG_WEEKS_PER_MONTH, rel=1e-4)
    assert big["difference_units"] == pytest.approx(3 * 500.0 / AVG_WEEKS_PER_MONTH - 10.0, rel=1e-4)
    rule_total = 3 * 600.0 / AVG_WEEKS_PER_MONTH
    pf = body["portfolio"]
    assert pf["sku_count"] == 2
    assert pf["lp_safety_stock_units"] == pytest.approx(50.0)
    assert pf["rule_safety_stock_units"] == pytest.approx(rule_total, rel=1e-4)
    assert pf["lp_vs_rule_pct"] == pytest.approx(round((rule_total - 50.0) / rule_total * 100, 1))
    assert pf["skus_lp_holds_less"] == 2


def test_money_and_stockout_fields_are_null_with_reason():
    with make_client(FakeSession(ROWS)) as c:
        body = c.get("/policy-comparison", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["working_capital"] is None
    assert body["capital_freed"] is None
    assert body["est_stockout_rate"] is None
    assert "pesos" in body["valuation_blocked_reason"]


def test_principal_scope_is_bound_not_interpolated():
    session = FakeSession(ROWS)
    with make_client(session) as c:
        c.get("/policy-comparison?principal=delmonte", headers={"Authorization": f"Bearer {user_token()}"})
    assert session.last_params == {"principal": "delmonte"}


def test_blocked_when_nothing_compares():
    with make_client(FakeSession([])) as c:
        body = c.get("/policy-comparison", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["items"] == []
    assert body["portfolio"]["lp_vs_rule_pct"] is None
    assert body["blocked_reason"]
