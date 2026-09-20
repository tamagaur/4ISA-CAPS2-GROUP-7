"""
tests/backend/test_recommendations.py — GET /recommendations
(backend/routers/recommendations.py).

New 2026-09-20 alongside the principal-scoping fix; this router had no
tests. Same principal-keyed fake as tests/backend/test_sku.py: the anchor
answer is derived from the :principal bind, and the fixture makes the two
principals disagree about their max inventory period, so an unscoped anchor
produces NULL stock and fails outright rather than merely going unasserted.

Live shape for reference (2026-09-20): lp_recommendation holds 430 Unilever
rows and zero Del Monte rows, so the Del Monte list is legitimately empty.
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
    def __init__(self, rows, stock_by_period, inventory_period_by_scope, abc_period_by_scope):
        self.rows = rows
        self.stock_by_period = stock_by_period
        self.inventory_period_by_scope = inventory_period_by_scope
        self.abc_period_by_scope = abc_period_by_scope
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, dict(params)))
        scope = params.get("principal")
        if "MAX(_period) AS p FROM Inventory_Fact_Real" in sql:
            return FakeResult([{"p": self.inventory_period_by_scope.get(scope)}])
        if "MAX(classification_period) AS p FROM ABC_Classification" in sql:
            return FakeResult([{"p": self.abc_period_by_scope.get(scope)}])
        if "FROM lp_recommendation lr" in sql:
            matched = [r for r in self.rows if scope is None or r["principal"] == scope]
            out = []
            for r in matched:
                stock = self.stock_by_period.get((r["product_key"], params.get("inv_period")))
                share = r["revenue_share"] if r["_abc_period"] == params.get("abc_period") else None
                out.append({
                    **r, "current_stock": stock, "stock_value_pesos": None,
                    "revenue_share": share, "avg_monthly_sales_pesos": None,
                })
            return FakeResult(out)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


@pytest.fixture
def sample_rows():
    return [
        {"recommendation_key": 1, "product_key": 1, "sku_id": "U-1", "product_name": "Uni One",
         "principal": "unilever", "q_i": 50.0, "rop_i": 30.0, "ss_i": 10.0, "status": "pending",
         "planning_cycle_date": "2026-03-01", "decided_at": None, "decided_by": None,
         "generated_at": None, "tier": "A", "revenue_share": 0.6, "_abc_period": "2026-02"},
    ]


@pytest.fixture
def session(sample_rows):
    return FakeSession(
        sample_rows,
        stock_by_period={(1, "2026-03"): 120.0},
        inventory_period_by_scope={None: "2026-03", "unilever": "2026-03", "delmonte": "2025-12"},
        abc_period_by_scope={None: "2026-02", "unilever": "2026-02", "delmonte": None},
    )


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def user_token():
    return auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="staff", full_name="Staff")


def test_requires_auth(session):
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        resp = c.get("/recommendations")
    app.dependency_overrides.clear()
    assert resp.status_code == 401


def test_unilever_stock_resolves(client):
    resp = client.get("/recommendations?principal=unilever")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["current_stock"] == 120.0
    assert items[0]["urgency"] != "NO DATA"


def test_delmonte_returns_empty_not_borrowed_rows(client):
    """Zero Del Monte LP rows live. The list must be honestly empty, never
    Unilever rows leaking through an unscoped anchor."""
    resp = client.get("/recommendations?principal=delmonte")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_anchors_carry_the_principal_bind(client, session):
    client.get("/recommendations?principal=unilever")
    flat = [" ".join(s.split()).lower() for s, _ in session.calls]
    assert not any("max(_period) from inventory_fact_real)" in s for s in flat)
    anchors = [(s, p) for s, p in session.calls if "max(" in s.lower() and " as p " in s.lower()]
    assert anchors, "no anchor query was issued at all"
    assert all(p.get("principal") == "unilever" for _, p in anchors)


def test_abc_join_is_pinned_to_one_period(client, session):
    """The DISTINCT ON walk it replaced mixed classification vintages."""
    client.get("/recommendations?principal=unilever")
    row_query = next(s for s, _ in session.calls if "FROM lp_recommendation lr" in s)
    assert "classification_period = :abc_period" in row_query
    assert "method = 'single'" in row_query
