"""
tests/backend/test_descriptive_endpoints.py — GET /fsn, /pareto, /decomposition,
/category-trends (the analytical mapping's D1, D3, D4 and P1).

FakeSession pattern from tests/backend/test_segment.py — never touches
Supabase. Each fake answers only the queries its endpoint issues, matched on
a distinctive SQL fragment, so a query drifting to another table fails loudly.
"""
from __future__ import annotations

import math

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

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return next(iter(self._rows[0].values())) if self._rows else None


class FakeSession:
    """routes: list of (sql fragment, rows or callable(params) -> rows)."""

    def __init__(self, routes):
        self.routes = routes

    def execute(self, stmt, params=None):
        sql = str(stmt)
        for fragment, rows in self.routes:
            if fragment in sql:
                return FakeResult(rows(params or {}) if callable(rows) else rows)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


def get(session, path):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        return c.get(path, headers={"Authorization": f"Bearer {user_token()}"})


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


MONTHS_2025 = [f"2025-{m:02d}" for m in range(1, 13)]


def test_fsn_classifies_over_observed_months():
    fast = [{"product_key": 1, "sku_id": "FAST", "period": m, "qty": 10} for m in MONTHS_2025]
    slow = [{"product_key": 2, "sku_id": "SLOW", "period": m, "qty": 3} for m in MONTHS_2025[::3]]
    dead = [{"product_key": 3, "sku_id": "DEAD", "period": m, "qty": 5} for m in MONTHS_2025[:4]]
    session = FakeSession([
        ("DISTINCT calendar_month AS period", [{"period": m} for m in reversed(MONTHS_2025)]),
        ("SUM(d.quantity_sold) AS qty", fast + slow + dead),
    ])
    body = get(session, "/fsn?principal=unilever").json()
    by_sku = {i["sku_id"]: i for i in body["items"]}
    assert by_sku["FAST"]["fsn"] == "F"
    assert by_sku["SLOW"]["fsn"] == "S"
    assert by_sku["DEAD"]["fsn"] == "N"
    assert body["summary"] == {"F": 1, "S": 1, "N": 1}
    assert body["windows"]["unilever"] == {"start": "2025-01", "end": "2025-12", "observed_months": 12}


def test_fsn_period_param_is_the_window_end():
    seen = {}

    def months(params):
        seen.update(params)
        return [{"period": "2025-06"}]

    session = FakeSession([
        ("DISTINCT calendar_month AS period", months),
        ("SUM(d.quantity_sold) AS qty", []),
    ])
    get(session, "/fsn?principal=unilever&period=2025-06")
    assert seen["end"] == "2025-06" and seen["n"] == 12


def test_brand_pareto_ranks_with_abc_cutoffs():
    session = FakeSession([
        # backend/marts.SNAPSHOT_SQL: Unilever's real sales end 2026-02.
        ("'sales' AS src", [{"src": "sales", "principal": "unilever", "period": "2026-02", "data_kind": "real",
                              "pesos": 1.0, "pieces": None, "recorded_with_tax": False, "placeholder": False}]),
        ("COALESCE(pd.brand, 'NO BRAND')", [
            {"name": "KNORR", "revenue": 700.0, "products": 10},
            {"name": "SURF", "revenue": 200.0, "products": 8},
            {"name": "DOVE", "revenue": 100.0, "products": 5},
        ]),
    ])
    body = get(session, "/pareto?grain=brand&principal=unilever").json()
    rows = body["principals"][0]["rows"]
    assert [(r["name"], r["tier"]) for r in rows] == [("KNORR", "A"), ("SURF", "B"), ("DOVE", "C")]
    assert rows[0]["revenue_share"] == pytest.approx(0.7)
    assert body["cutoffs"] == {"A": 0.8, "B": 0.95}


def test_delmonte_brand_pareto_is_a_reason_not_rows():
    body = get(FakeSession([]), "/pareto?grain=brand&principal=delmonte").json()
    del_monte = body["principals"][0]
    assert del_monte["rows"] == [] and "no brand" in del_monte["blocked_reason"]


def test_decomposition_zero_fills_and_runs_stl():
    periods = [f"{2023 + i // 12}-{i % 12 + 1:02d}" for i in range(40)]
    rows = [{"period": p, "qty": 100 + 40 * math.cos(2 * math.pi * i / 12)} for i, p in enumerate(periods) if i != 5]
    session = FakeSession([
        ("FROM Product_Dimension WHERE sku_code", [{"product_key": 7, "principal": "unilever"}]),
        ("GROUP BY calendar_month ORDER BY calendar_month", rows),
        ("SELECT MAX(calendar_month) FROM Unilever_SKU_Demand_Fact_Real", [{"max": periods[-1]}]),
    ])
    body = get(session, "/decomposition?sku=X").json()
    assert body["available"] is True
    assert body["months"] == 40  # the missing month was zero-filled, not dropped
    assert body["observed"][5] == 0.0
    assert body["method"]["name"] == "STL"


def test_decomposition_unknown_or_non_unilever_is_404():
    session = FakeSession([("FROM Product_Dimension WHERE sku_code", [])])
    assert get(session, "/decomposition?sku=CULINARY").status_code == 404


def test_category_trends_project_growth_and_refuse_short_series():
    months = [f"{2024 + i // 12}-{i % 12 + 1:02d}" for i in range(24)]
    unilever = [{"category": "COOKING AIDS", "period": m, "revenue": 1000 + 25 * i} for i, m in enumerate(months)]
    delmonte = [{"category": "CULINARY", "period": m, "revenue": 500.0} for m in ("2025-03", "2025-04", "2025-06")]
    session = FakeSession([
        ("FROM Unilever_SKU_Demand_Fact_Real d", unilever),
        ("FROM SellOut_Fact_Real s", delmonte),
    ])
    body = get(session, "/category-trends").json()
    uni, dm = body["principals"]
    cooking = uni["categories"][0]
    assert cooking["direction"] == "growing" and cooking["change_pct"] > 0
    assert cooking["projection_periods"][0] == "2026-01" and len(cooking["projection"]) == 12
    culinary = dm["categories"][0]
    assert culinary["available"] is False and culinary["projection_periods"] == []
    assert dm["observed_months"] == ["2025-03", "2025-04", "2025-06"]
