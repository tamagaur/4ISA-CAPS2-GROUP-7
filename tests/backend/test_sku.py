"""
tests/backend/test_sku.py — GET /sku (backend/routers/sku.py).

New 2026-09-20 alongside the principal-scoping fix: sku.py had no tests at
all, and the anchor bug it carried was structurally invisible to the older
fakes, which matched SQL substrings and threw `params` away.

The decisive pattern here is `inventory_period_by_scope`: the fixture is
built so the two principals disagree about their max period (Unilever
2026-03, Del Monte 2025-12 — the real shape, measured 2026-09-20). Since
2026-09-29 stock resolves per principal INSIDE the row query
(backend/stock_units.STOCK_AT_LATEST_SQL); the fake honours that only when
the query really groups the latest snapshot by principal, and otherwise
falls back to one global :inv_period — the old shape, which loses Del
Monte's stock under 'all'. Likewise reorder_point comes from the LP's
current cycle only when the query filters on :current_cycle; otherwise the
fake answers with the newest pending row of ANY cycle, the old behaviour.
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
    when the query resolved that principal's OWN max period. Reorder points
    are keyed by (product_key, planning cycle).
    """

    def __init__(self, rows, stock_by_period, inventory_period_by_scope, abc_period_by_scope,
                 rop_by_cycle=None, current_cycle=None):
        self.rows = rows
        self.stock_by_period = stock_by_period
        self.inventory_period_by_scope = inventory_period_by_scope
        self.abc_period_by_scope = abc_period_by_scope
        self.rop_by_cycle = rop_by_cycle or {}
        self.current_cycle = current_cycle
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
            return FakeResult([
                {"principal": who, "p": self.abc_period_by_scope.get(who)}
                for who in (("unilever", "delmonte") if scope is None else (scope,))
            ])
        if "MAX(lr.planning_cycle_date) AS d" in sql:
            return FakeResult([{"d": self.current_cycle}])
        if "FROM product_dimension pd" in sql:
            matched = [
                r for r in self.rows
                if scope is None or r["principal"] == scope
            ]
            per_principal = "MAX(_period) AS latest_period" in sql and "GROUP BY principal" in sql
            current_only = "planning_cycle_date = :current_cycle" in sql
            out = []
            for r in matched:
                key = r["product_key"]
                period = (self.inventory_period_by_scope.get(r["principal"]) if per_principal
                          else params.get("inv_period"))
                stock = self.stock_by_period.get((key, period))
                if current_only:
                    rop = self.rop_by_cycle.get((key, params.get("current_cycle")))
                else:
                    cycles = sorted(c for k, c in self.rop_by_cycle if k == key)
                    rop = self.rop_by_cycle[(key, cycles[-1])] if cycles else None
                tier = r["tier"] if r["_abc_period"] == params.get("abc_p_" + r["principal"]) else None
                out.append({**r, "current_stock": stock,
                            "current_stock_cases": None if stock is None else stock / 288,
                            "reorder_point": rop, "tier": tier})
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
        {"product_key": 3, "sku_id": "U-2", "product_name": "Uni Two", "principal": "unilever",
         "pack_size": None, "brand": None, "unit_price": None, "lead_time_days": None,
         "status": "ACTIVE", "notes": None, "tier": "B", "_abc_period": "2026-02"},
    ]


def make_session(rows):
    return FakeSession(
        rows,
        # Each product only has stock at its OWN principal's max period.
        stock_by_period={(1, "2026-03"): 120.0, (2, "2025-12"): 260.0},
        inventory_period_by_scope={None: "2026-03", "unilever": "2026-03", "delmonte": "2025-12"},
        # Del Monte has zero abc_classification rows live — None is correct.
        abc_period_by_scope={None: "2026-02", "unilever": "2026-02", "delmonte": None},
        # Product 1 is in the current cycle; product 3 only in a superseded one.
        rop_by_cycle={(1, "2026-03-01"): 9818340.0, (3, "2023-05-01"): 1783.0},
        current_cycle="2026-03-01",
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


def test_method_still_pinned(client, session):
    """Migration 0017 guard — without it the tier join fans out to one row
    per basis per product_key. Pinned to each principal's Tier A basis since
    migration 0044 (analytics.params.abc_method_sql)."""
    from analytics.params import abc_method_sql
    client.get("/sku?principal=unilever")
    row_query = next(s for s, _ in session.calls if "FROM product_dimension pd" in s)
    assert abc_method_sql() in row_query


def test_all_scope_keeps_each_principals_own_stock(client):
    """Under 'all' one global snapshot month (Unilever's 2026-03) left every
    Del Monte product without stock (260 products -> 0, measured 2026-09-29)."""
    items = {i["sku_id"]: i for i in client.get("/sku").json()["items"]}
    assert items["D-1"]["current_stock"] == 260.0
    assert items["U-1"]["current_stock"] == 120.0


def test_stock_is_pieces_with_cases_alongside(client):
    item = client.get("/sku?principal=unilever").json()["items"][0]
    assert item["current_stock"] == 120.0
    assert item["current_stock_cases"] == pytest.approx(120.0 / 288)


def test_reorder_point_comes_from_the_current_cycle_only(client):
    """A superseded cycle's pending row must not supply a reorder point —
    179 did before 2026-09-29, from runs as old as 2023-05."""
    items = {i["sku_id"]: i for i in client.get("/sku?principal=unilever").json()["items"]}
    assert items["U-1"]["reorder_point"] == 9818340.0
    assert items["U-2"]["reorder_point"] is None


@pytest.fixture
def admin_client(session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=2, email="admin@ssmcapstone.com", role="admin", full_name="Admin")
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.parametrize("code", ["1234567", "123456789", "1234567A", "", " 12345678"])
def test_create_rejects_a_code_that_is_not_8_digits(admin_client, session, code):
    """Migration 0030's CHECK allows exactly 8 digits for a Unilever code; the
    route says so with a 400 instead of letting the constraint raise a 500."""
    resp = admin_client.post("/sku", json={"sku_code": code, "principal": "unilever", "product_name": "X"})
    assert resp.status_code == 400
    assert "8 digits" in resp.json()["detail"]
    assert not any("INSERT" in s for s, _ in session.calls)


def test_reorder_point_is_left_out_without_lp_view(client, monkeypatch):
    """The product list is sign-in only (shared by several pages), but the
    LP's reorder point on it follows lp.view (Yuan's permissions proposal)."""
    from backend import permissions

    monkeypatch.setattr(permissions, "load_overrides", lambda db, user_id: {"lp.view": False})
    items = {i["sku_id"]: i for i in client.get("/sku?principal=unilever").json()["items"]}
    assert items["U-1"]["reorder_point"] is None
    assert items["U-1"]["current_stock"] == 120.0  # stock is not an LP figure


def test_abc_period_params_keep_each_principal_on_its_own_run():
    """Under 'all', Del Monte keeps its own 2025-12 run instead of Unilever's
    2026-02 (a single MAX across both left Del Monte with no tier)."""
    from backend.principals import abc_period_params, abc_period_pred, abc_periods_from_rows

    periods = abc_periods_from_rows([{"principal": "unilever", "p": "2026-02"}, {"principal": "delmonte", "p": "2025-12"}])
    assert abc_period_params(periods) == {"abc_p_unilever": "2026-02", "abc_p_delmonte": "2025-12"}
    assert abc_period_params({"unilever": "2026-02"})["abc_p_delmonte"] is None
    assert "CASE ac.principal" in abc_period_pred("=", "ac")


def test_tier_a_periods_is_a_per_principal_map_by_display_name():
    from backend.principals import tier_a_periods

    assert tier_a_periods({"unilever": "2026-02", "delmonte": "2025-12"}) == {"Unilever": "2026-02", "Del Monte": "2025-12"}
    assert tier_a_periods({"delmonte": "2025-12"}) == {"Del Monte": "2025-12"}
    assert tier_a_periods({}) == {}


def test_sku_list_carries_tier_a_periods_without_touching_item_tiers(client):
    body = client.get("/sku?principal=unilever").json()
    assert isinstance(body["tier_a_periods"], dict)
