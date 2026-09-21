"""
tests/backend/test_bo_monitoring.py — GET /bo-monitoring (backend/routers/bo_monitoring.py).

FakeSession pattern from tests/backend/test_segment.py — never touches
Supabase. Pins the honesty rules the page relies on: months with no typed
returns are gaps (not zeros), the value-based rate only divides BO value by
purchases from the SAME months, no field is filled with a placeholder, and
undated returns give no weekday breakdown.
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
    """Returns (typed) per principal/period, purchases per principal/period,
    BO incidents, regions and dated weekday counts — the shapes the router reads."""

    def __init__(self, returns=None, purchases=None, incidents=None, regions=None, weekdays=None):
        self.returns = returns or []
        self.purchases = purchases or []
        self.incidents = incidents or []
        self.regions = regions or []
        self.weekdays = weekdays or []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "return_slip_num as id" in sql:
            return FakeResult(self.incidents)
        if "AS bo_count" in sql:
            return FakeResult(self.returns)
        if "FROM purchase_fact_real" in sql:
            return FakeResult(self.purchases)
        if "GROUP BY region" in sql:
            return FakeResult(self.regions)
        if "EXTRACT(ISODOW" in sql:
            return FakeResult(self.weekdays)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


RETURNS = [
    {"principal": "delmonte", "_period": "2025-03", "bo_count": 10, "bo_value": 1000.0},
    # 2025-04: no typed returns at all -> a gap, not zero
    {"principal": "delmonte", "_period": "2025-05", "bo_count": 5, "bo_value": 4000.0},  # no purchases that month
    {"principal": "delmonte", "_period": "2025-06", "bo_count": 0, "bo_value": 0.0},     # typed returns, no BO: a real zero
]
PURCHASES = [
    {"principal": "delmonte", "_period": "2025-03", "purchase_value": 100000.0},
    {"principal": "delmonte", "_period": "2025-06", "purchase_value": 50000.0},
    {"principal": "delmonte", "_period": "2024-01", "purchase_value": 999999.0},  # outside the BO months
]
INCIDENTS = [{"id": "39206", "principal": "delmonte", "region": "ilocos", "period": "2025-03", "date": None, "value": 480.0}]


def make_client(session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def get(session, path="/bo-monitoring"):
    with make_client(session) as c:
        return c.get(path, headers={"Authorization": f"Bearer {user_token()}"}).json()


def test_missing_months_are_gaps_not_zeros():
    body = get(FakeSession(RETURNS, PURCHASES, INCIDENTS))
    by_period = {t["period"]: t for t in body["trend"]}
    assert list(by_period) == ["2025-03", "2025-04", "2025-05", "2025-06"]
    assert by_period["2025-04"] == {"period": "2025-04", "has_data": False, "incident_count": None,
                                    "value_lost": None, "purchase_value": None, "bo_rate": None}
    assert by_period["2025-06"]["has_data"] is True and by_period["2025-06"]["incident_count"] == 0
    assert body["kpis"]["months_missing"] == ["2025-04"]
    assert body["kpis"]["months_with_data"] == 3


def test_rate_only_uses_months_with_both_returns_and_purchases():
    body = get(FakeSession(RETURNS, PURCHASES, INCIDENTS))
    # (1000 + 0) / (100000 + 50000): 2025-05's BO has no purchases, 2024-01's purchases have no BO.
    assert body["kpis"]["ratePct"] == pytest.approx(round(1000 / 150000 * 100, 2))
    assert body["kpis"]["rate_periods"] == ["2025-03", "2025-06"]
    by_period = {t["period"]: t for t in body["trend"]}
    assert by_period["2025-03"]["bo_rate"] == pytest.approx(1.0)
    assert by_period["2025-05"]["bo_rate"] is None
    assert body["kpis"]["incidents"] == 15
    assert body["kpis"]["valueLost"] == pytest.approx(5000.0)


def test_no_placeholder_fields():
    body = get(FakeSession(RETURNS, PURCHASES, INCIDENTS))
    assert body["kpis"]["unitsLost"] is None
    incident = body["incidents"][0]
    assert incident["principal"] == "delmonte" and incident["region"] == "ilocos"
    assert incident["period"] == "2025-03"
    assert incident["brand"] is None and incident["sku"] is None and incident["qty"] is None
    assert "brand_breakdown" not in body


def test_principal_breakdown_uses_the_same_rate_rule():
    body = get(FakeSession(RETURNS, PURCHASES, INCIDENTS))
    assert body["principal_breakdown"] == [{
        "principal": "delmonte", "incidents": 15, "value_lost": 5000.0, "months_with_data": 3,
        "bo_rate": round(1000 / 150000 * 100, 2), "rate_periods": ["2025-03", "2025-06"],
    }]


def test_undated_returns_give_no_weekday_breakdown():
    body = get(FakeSession(RETURNS, PURCHASES, INCIDENTS))
    assert body["weekday_breakdown"] == []
    assert body["kpis"]["dated_incidents"] == 0
    dated = get(FakeSession(RETURNS, PURCHASES, INCIDENTS, weekdays=[{"dow": 1, "count": 3}]))
    assert dated["kpis"]["dated_incidents"] == 3
    assert dated["weekday_breakdown"][0] == {"day": "Mon", "count": 3}


def test_empty_scope_is_empty_not_zero():
    body = get(FakeSession(), "/bo-monitoring?principal=unilever")
    assert body["trend"] == []
    assert body["kpis"]["ratePct"] is None
    assert body["principal_breakdown"] == []
