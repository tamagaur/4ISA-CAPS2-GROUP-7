"""
tests/backend/test_sku.py — GET /sku (backend/routers/sku.py).

New 2026-09-20 alongside the principal-scoping fix: sku.py had no tests at
all, and the anchor bug it carried was structurally invisible to the older
fakes, which matched SQL substrings and threw `params` away.

The decisive pattern here is `inventory_period_by_scope`: the fake answers
the anchor query FROM THE :principal BIND, and the fixture is built so the
two principals disagree about their max period (Unilever 2026-03, Del Monte
2025-12 — the real shape, measured 2026-09-20). An unscoped anchor therefore
resolves to the wrong period and returns NULL stock, which no assertion
below can pass. A missing-assertion test would not have caught this.
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
    """Matches only the query shapes backend/routers/sku.py issues.

    Stock rows are keyed by (product_key, period), so a row is only found
    when the anchor resolved to that principal's OWN max period.
    """

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
        # None is the 'all' key — principal_clause emits no bind at all then.
        scope = params.get("principal")
        if "MAX(_period) AS p FROM Inventory_Fact_Real" in sql:
            return FakeResult([{"p": self.inventory_period_by_scope.get(scope)}])
        if "MAX(classification_period) AS p FROM ABC_Classification" in sql:
            return FakeResult([{"p": self.abc_period_by_scope.get(scope)}])
        if "FROM product_dimension pd" in sql:
            matched = [
                r for r in self.rows
                if scope is None or r["principal"] == scope
            ]
            out = []
            for r in matched:
                stock = self.stock_by_period.get((r["product_key"], params.get("inv_period")))
                tier = r["tier"] if r["_abc_period"] == params.get("abc_period") else None
                out.append({**r, "current_stock": stock, "reorder_point": None, "tier": tier})
            return FakeResult(out)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


@pytest.fixture
def sample_rows():
    return [
        {"product_key": 1, "sku_id": "U-1", "product_name": "Uni One", "principal": "unilever",
         "pack_size": None, "brand": None, "unit_price": None, "lead_time_days": None,
         "status": "ACTIVE", "notes": None, "tier": "A", "_abc_period": "2026-02"},
        {"product_key": 2, "sku_id": "D-1", "product_name": "DM One", "principal": "delmonte",
         "pack_size": None, "brand": None, "unit_price": None, "lead_time_days": None,
         "status": "ACTIVE", "notes": None, "tier": None, "_abc_period": None},
    ]


def make_session(rows):
    return FakeSession(
        rows,
        # Each product only has stock at its OWN principal's max period.
        stock_by_period={(1, "2026-03"): 120.0, (2, "2025-12"): 260.0},
        inventory_period_by_scope={None: "2026-03", "unilever": "2026-03", "delmonte": "2025-12"},
        # Del Monte has zero abc_classification rows live — None is correct.
        abc_period_by_scope={None: "2026-02", "unilever": "2026-02", "delmonte": None},
    )


@pytest.fixture
def session(sample_rows):
    return make_session(sample_rows)


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
        resp = c.get("/sku")
    app.dependency_overrides.clear()
    assert resp.status_code == 401


def test_delmonte_stock_resolves_under_its_own_period(client):
    """The decisive test. Del Monte's max is 2025-12; the global max is
    2026-03. An unscoped anchor lands on 2026-03, where Del Monte has no
    row, and current_stock comes back None."""
    resp = client.get("/sku?principal=delmonte")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["current_stock"] == 260.0


def test_unilever_stock_unchanged(client):
    resp = client.get("/sku?principal=unilever")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["current_stock"] == 120.0


def test_delmonte_tier_stays_null(client):
    """Del Monte has no abc_classification rows at all. Scoping the anchor
    must NOT borrow Unilever's period to manufacture a tier."""
    items = client.get("/sku?principal=delmonte").json()["items"]
    assert items[0]["tier"] is None


def test_anchors_carry_the_principal_bind(client, session):
    """Structural guard: no inline anchor may survive, and every anchor
    query must carry the scope."""
    client.get("/sku?principal=delmonte")
    flat = [" ".join(s.split()).lower() for s, _ in session.calls]
    assert not any("max(_period) from inventory_fact_real)" in s for s in flat)
    assert not any("max(classification_period) from abc_classification" in s for s in flat)
    anchors = [(s, p) for s, p in session.calls if "max(" in s.lower() and " as p " in s.lower()]
    assert anchors, "no anchor query was issued at all"
    assert all(p.get("principal") == "delmonte" for _, p in anchors)


def test_method_single_still_pinned(client, session):
    """Migration 0017 guard — without it the tier join fans out to two rows
    per product_key. Out of scope for this change; must not regress."""
    client.get("/sku?principal=unilever")
    row_query = next(s for s, _ in session.calls if "FROM product_dimension pd" in s)
    assert "method = 'single'" in row_query
