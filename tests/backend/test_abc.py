"""
tests/backend/test_abc.py — GET /abc (backend/routers/abc.py).

Backlog #40, #42, #43, #44. Uses a FakeSession (same pattern as
tests/backend/test_auth.py's) so these never touch a real Supabase
instance.

BOTH PRINCIPALS (2026-09-17): GET /abc accepts ?principal= again — the
earlier "UNILEVER ONLY" note this replaced was stale. FakeSession answers
the inventory anchor from the :principal bind (inventory_period_by_scope),
so an unscoped anchor resolves to the wrong period rather than quietly
returning the same fixture for every scope.
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

    def __init__(self, rows, latest_period, inventory_period_by_scope=None):
        self.rows = rows
        self.latest_period = latest_period
        # Keyed by the :principal bind so an UNSCOPED anchor resolves to a
        # different period than a scoped one. None is the 'all' key, matching
        # principal_clause's contract of emitting no bind at all.
        self.inventory_period_by_scope = inventory_period_by_scope or {
            None: "2026-03", "unilever": "2026-03", "delmonte": "2025-12",
        }
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, dict(params)))
        if "MAX(classification_period)" in sql:
            return FakeResult([{"p": self.latest_period}])
        if "MAX(_period) AS p FROM Inventory_Fact_Real" in sql:
            return FakeResult(
                [{"p": self.inventory_period_by_scope.get(params.get("principal"))}]
            )
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


# ---- view=last_known -------------------------------------------------------
# Most recent 'single' tier per product at or before the anchor, same rule as
# GET /sku. This fake models the SQL in Python (DISTINCT ON = newest period
# per product_key under the anchor); the fan-out protection itself lives in
# SQL and is covered by the live smoke run, not here.


class LastKnownFakeSession:
    def __init__(self, abc_rows, products):
        # abc_rows: product_key, principal, tier, classification_period,
        # revenue_share, cumulative_share, boundary_flag
        self.abc_rows = abc_rows
        # products: product_key, sku_id, product_name, principal
        self.products = products
        self.calls: list[tuple[str, dict]] = []

    def _scoped(self, rows, params):
        p = params.get("principal")
        return [r for r in rows if p is None or r["principal"] == p]

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, dict(params)))
        if "MAX(classification_period)" in sql:
            rows = self._scoped(self.abc_rows, params)
            cap = params.get("at_or_before")
            periods = [r["classification_period"] for r in rows if cap is None or r["classification_period"] <= cap]
            return FakeResult([{"p": max(periods) if periods else None}])
        if "MAX(_period) AS p FROM Inventory_Fact_Real" in sql:
            return FakeResult([{"p": "2026-03"}])
        if "SELECT COUNT(*) AS n FROM product_dimension" in sql:
            period = params["period"]
            ranked = {
                r["product_key"] for r in self.abc_rows
                if period is None or r["classification_period"] <= period
            }
            n = sum(1 for p in self._scoped(self.products, params) if p["product_key"] not in ranked)
            return FakeResult([{"n": n}])
        if "WITH latest AS" in sql:
            period = params["period"]
            latest: dict[int, dict] = {}
            for r in self._scoped(self.abc_rows, params):
                if r["classification_period"] > period:
                    continue
                cur = latest.get(r["product_key"])
                if cur is None or r["classification_period"] > cur["classification_period"]:
                    latest[r["product_key"]] = r
            by_key = {p["product_key"]: p for p in self.products}
            out = [
                {
                    "sku_id": by_key[k]["sku_id"], "product_name": by_key[k]["product_name"],
                    "principal": r["principal"], "tier": r["tier"],
                    "tier_period": r["classification_period"],
                    "revenue_share": r["revenue_share"], "cumulative_share": r["cumulative_share"],
                    "boundary_flag": r["boundary_flag"], "current_stock": None, "reorder_point": None,
                }
                for k, r in latest.items()
            ]
            return FakeResult(out)
        raise AssertionError(f"Unexpected query in LastKnownFakeSession: {sql}")

    def close(self):
        pass


def _abc(pk, tier, period, share, principal="unilever", boundary=False):
    return {"product_key": pk, "principal": principal, "tier": tier, "classification_period": period,
            "revenue_share": share, "cumulative_share": share, "boundary_flag": boundary}


@pytest.fixture
def last_known_session():
    products = [
        {"product_key": k, "sku_id": f"SKU-{k}", "product_name": f"P{k}", "principal": "unilever"}
        for k in (1, 2, 3, 4, 5)
    ] + [{"product_key": 9, "sku_id": "DM-9", "product_name": "DM", "principal": "delmonte"}]
    abc_rows = [
        # 2026-02 run: products 1 and 2 only (0.7 + 0.3 = 100%).
        _abc(1, "A", "2026-02", 0.7), _abc(2, "B", "2026-02", 0.3, boundary=True),
        # Product 1 also ranked earlier — must NOT appear twice.
        _abc(1, "B", "2025-11", 0.2),
        # Product 3 last ranked 2025-11 -> carried forward.
        _abc(3, "A", "2025-11", 0.5),
        # Product 4 ranked only AFTER the anchor used in one test.
        _abc(4, "C", "2026-03", 1.0),
        # Product 5 never ranked.
    ]
    return LastKnownFakeSession(abc_rows, products)


def _get(session, qs):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        resp = c.get(f"/abc?{qs}", headers={"Authorization": f"Bearer {user_token()}"})
    app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_last_known_one_row_per_product_with_tier_period(last_known_session):
    body = _get(last_known_session, "view=last_known&classification_period=2026-02&principal=unilever")
    items = {i["sku_id"]: i for i in body["items"]}
    assert body["classification_period"] == "2026-02"
    # 1 and 2 current, 3 carried forward; 4 is after the anchor, 5 never ranked.
    assert set(items) == {"SKU-1", "SKU-2", "SKU-3"}
    assert items["SKU-1"]["tier"] == "A" and items["SKU-1"]["tier_period"] == "2026-02"
    assert items["SKU-3"]["tier_period"] == "2025-11"


def test_last_known_revenue_total_excludes_carried_forward(last_known_session):
    """Carried-forward shares are fractions of OTHER months' revenue; summing
    them in would put tier A at 120% of February."""
    body = _get(last_known_session, "view=last_known&classification_period=2026-02&principal=unilever")
    summary = {t["tier"]: t for t in body["tier_summary"]}
    assert summary["A"]["sku_count"] == 2
    assert summary["A"]["carried_forward_count"] == 1
    assert summary["A"]["revenue_share_total"] == pytest.approx(0.7)
    assert sum(t["revenue_share_total"] for t in body["tier_summary"]) == pytest.approx(1.0)


def test_last_known_counts_never_ranked_products(last_known_session):
    body = _get(last_known_session, "view=last_known&classification_period=2026-02&principal=unilever")
    # Product 4 (ranked only in 2026-03) and 5 (never) have no tier as of 2026-02.
    assert body["unclassified_count"] == 2


def test_last_known_anchor_falls_back_to_nearest_earlier_run(last_known_session):
    """The page seeds from the dashboard's end month, which can be past the
    newest run; that must land on the nearest run, not an empty page."""
    body = _get(last_known_session, "view=last_known&classification_period=2026-01&principal=unilever")
    assert body["classification_period"] == "2025-11"
    assert {i["sku_id"] for i in body["items"]} == {"SKU-1", "SKU-3"}
    assert {i["tier_period"] for i in body["items"]} == {"2025-11"}


def test_last_known_delmonte_is_empty_but_counted(last_known_session):
    body = _get(last_known_session, "view=last_known&principal=delmonte")
    assert body["items"] == []
    assert body["classification_period"] is None
    assert body["unclassified_count"] == 1


def test_default_view_unchanged_has_no_unclassified_count(client):
    resp = client.get("/abc", headers={"Authorization": f"Bearer {user_token()}"})
    body = resp.json()
    assert body["unclassified_count"] is None
    assert {i["tier_period"] for i in body["items"]} == {"2024-02"}
