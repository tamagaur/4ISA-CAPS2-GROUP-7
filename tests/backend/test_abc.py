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
        # lp_cycle.current_cycle(): no pending LP rows in these fixtures.
        if "MAX(lr.planning_cycle_date)" in sql:
            return FakeResult([{"d": None}])
        if "MAX(classification_period)" in sql:
            return FakeResult([{"principal": params.get("principal") or "unilever", "p": self.latest_period}])
        if "MAX(_period) AS p FROM Inventory_Fact_Real" in sql:
            return FakeResult(
                [{"p": self.inventory_period_by_scope.get(params.get("principal"))}]
            )
        if "FROM abc_classification ac" in sql:
            # Each row is current against ITS principal's resolved run (abc_period_pred).
            per = {"unilever": params.get("abc_p_unilever"), "delmonte": params.get("abc_p_delmonte")}
            matched = [r for r in self.rows if r["_period"] == per.get(r["principal"])]
            return FakeResult(matched)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


@pytest.fixture
def sample_rows():
    return [
        {"product_key": 1, "sku_id": "SKU-A", "product_name": "Product A", "principal": "unilever", "tier": "A", "revenue_share": 0.60,
         "cumulative_share": 0.60, "boundary_flag": False, "current_stock": 120, "has_stock_row": True, "reorder_point": None, "safety_stock": None, "_period": "2024-02"},
        {"product_key": 2, "sku_id": "SKU-B", "product_name": "Product B", "principal": "unilever", "tier": "B", "revenue_share": 0.20,
         "cumulative_share": 0.80, "boundary_flag": True, "current_stock": 40, "has_stock_row": True, "reorder_point": None, "safety_stock": None, "_period": "2024-02"},
        {"product_key": 3, "sku_id": "SKU-C", "product_name": "Product C", "principal": "unilever", "tier": "C", "revenue_share": 0.05,
         "cumulative_share": 0.99, "boundary_flag": False, "current_stock": 0, "has_stock_row": True, "reorder_point": None, "safety_stock": None, "_period": "2024-02"},
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


def test_items_carry_product_key_and_sku_id_falls_back_to_category_path(sample_rows):
    """Del Monte ABC rows are category grain with no sku_code. A '' fallback
    gave all 85 of them the same sku_id, which the ABC page used as its row
    key. The fallback itself is SQL, so it is checked on the issued query;
    product_key (the frontend's row key) is checked on the response."""
    session = FakeSession(sample_rows, latest_period="2024-02")
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        body = c.get("/abc", headers={"Authorization": f"Bearer {user_token()}"}).json()
    app.dependency_overrides.clear()
    assert {i["product_key"] for i in body["items"]} == {1, 2, 3}
    row_sql = [sql for sql, _ in session.calls if "FROM abc_classification ac" in sql]
    assert row_sql and all("COALESCE(pd.sku_code, pd.category_path, '')" in sql for sql in row_sql)


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
        # lp_cycle.current_cycle(): no pending LP rows in these fixtures.
        if "MAX(lr.planning_cycle_date)" in sql:
            return FakeResult([{"d": None}])
        if "MAX(classification_period)" in sql:
            rows = self._scoped(self.abc_rows, params)
            cap = params.get("at_or_before")
            by_principal: dict[str, str] = {}
            for r in rows:
                if (cap is None or r["classification_period"] <= cap) and r["classification_period"] > by_principal.get(r["principal"], ""):
                    by_principal[r["principal"]] = r["classification_period"]
            return FakeResult([{"principal": k, "p": v} for k, v in by_principal.items()])
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
            per = {"unilever": params.get("abc_p_unilever"), "delmonte": params.get("abc_p_delmonte")}
            latest: dict[int, dict] = {}
            for r in self._scoped(self.abc_rows, params):
                if per.get(r["principal"]) is None or r["classification_period"] > per[r["principal"]]:
                    continue
                cur = latest.get(r["product_key"])
                if cur is None or r["classification_period"] > cur["classification_period"]:
                    latest[r["product_key"]] = r
            by_key = {p["product_key"]: p for p in self.products}
            out = [
                {
                    "product_key": k,
                    "sku_id": by_key[k]["sku_id"], "product_name": by_key[k]["product_name"],
                    "principal": r["principal"], "tier": r["tier"],
                    "tier_period": r["classification_period"],
                    "revenue_share": r["revenue_share"], "cumulative_share": r["cumulative_share"],
                    "boundary_flag": r["boundary_flag"], "current_stock": None, "has_stock_row": False, "reorder_point": None, "safety_stock": None,
                    # SQL decides this from sellout_fact_real (backend/routers/abc._DM_RETIRED_PRED); the
                    # fake takes it from the fixture row.
                    "retired_series": r.get("retired", False),
                }
                for k, r in latest.items()
            ]
            return FakeResult(out)
        raise AssertionError(f"Unexpected query in LastKnownFakeSession: {sql}")

    def close(self):
        pass


def _abc(pk, tier, period, share, principal="unilever", boundary=False, retired=False):
    return {"product_key": pk, "principal": principal, "tier": tier, "classification_period": period,
            "revenue_share": share, "cumulative_share": share, "boundary_flag": boundary, "retired": retired}


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
    assert [items[s]["product_key"] for s in ("SKU-1", "SKU-2", "SKU-3")] == [1, 2, 3]
    lk_sql = [sql for sql, _ in last_known_session.calls if "WITH latest AS" in sql]
    assert lk_sql and "COALESCE(pd.sku_code, pd.category_path, '')" in lk_sql[0]


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


class PeriodResolvingFakeSession(FakeSession):
    """FakeSession whose MAX(classification_period) honours the principal scope
    and the at_or_before bind, like the real query does."""

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        # lp_cycle.current_cycle(): no pending LP rows in these fixtures.
        if "MAX(lr.planning_cycle_date)" in sql:
            return FakeResult([{"d": None}])
        if "MAX(classification_period)" in sql:
            self.calls.append((sql, dict(params)))
            scope, cap = params.get("principal"), params.get("at_or_before")
            by_principal: dict[str, str] = {}
            for r in self.rows:
                if (scope is None or r["principal"] == scope) and (cap is None or r["_period"] <= cap)                         and r["_period"] > by_principal.get(r["principal"], ""):
                    by_principal[r["principal"]] = r["_period"]
            return FakeResult([{"principal": k, "p": v} for k, v in by_principal.items()])
        return super().execute(stmt, params)


def test_period_view_resolves_requested_month_to_latest_classified_period_per_principal():
    """The page always sends a month. Del Monte's latest ABC run is 2025-12
    while Unilever's is 2026-02, so an exact match on 2026-02 returned an empty
    Del Monte tab. The requested month resolves to the latest classified period
    at or before it for that principal - 2025-12 - and its rows come back."""
    def row(pk, principal, period, tier="A"):
        return {"product_key": pk, "sku_id": f"/CAT/{pk}", "product_name": f"Category {pk}", "principal": principal, "tier": tier,
                "revenue_share": 0.5, "cumulative_share": 0.5, "boundary_flag": False, "current_stock": None,
                "has_stock_row": False, "reorder_point": None, "safety_stock": None, "_period": period}
    rows = [row(1, "unilever", "2026-02"), row(10, "delmonte", "2025-12"), row(11, "delmonte", "2025-12", "B"), row(12, "delmonte", "2025-11")]
    session = PeriodResolvingFakeSession(rows, latest_period=None)

    body = _get(session, "classification_period=2026-02&principal=delmonte")

    assert body["classification_period"] == "2025-12"
    assert body["count"] == 2 and {i["product_key"] for i in body["items"]} == {10, 11}
    max_calls = [params for sql, params in session.calls if "MAX(classification_period)" in sql]
    assert max_calls and all(p.get("at_or_before") == "2026-02" and p.get("principal") == "delmonte" for p in max_calls)

    # the same request for Unilever still lands on its own latest run, and a month before any run is empty
    assert _get(session, "classification_period=2026-02&principal=unilever")["classification_period"] == "2026-02"
    empty = _get(session, "classification_period=2025-10&principal=delmonte")
    assert empty["count"] == 0 and empty["classification_period"] is None


def test_response_carries_rules_shares_and_pareto_check(client):
    """The page states the run's rules and measured shares from the API, not
    from its own copy (2026-09-25)."""
    from analytics.classification.abc import abc_rules
    body = client.get("/abc", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["rules"] == abc_rules()
    summary = {t["tier"]: t for t in body["tier_summary"]}
    assert summary["A"]["sku_share"] == pytest.approx(1 / 3)
    assert sum(t["sku_share"] for t in body["tier_summary"]) == pytest.approx(1.0, abs=1e-5)
    assert body["pareto_check"]["ranked_count"] == 3
    assert body["pareto_check"]["top_count"] == 1


def test_last_known_shares_count_only_this_run(last_known_session):
    body = _get(last_known_session, "view=last_known&classification_period=2026-02&principal=unilever")
    summary = {t["tier"]: t for t in body["tier_summary"]}
    ranked = sum(t["sku_count"] - t["carried_forward_count"] for t in body["tier_summary"])
    assert summary["A"]["sku_share"] == pytest.approx((summary["A"]["sku_count"] - summary["A"]["carried_forward_count"]) / ranked)
    assert body["pareto_check"]["ranked_count"] == ranked


# ---- stock status and the Pareto check (2026-09-29) -------------------------

def test_stock_status_is_the_shared_rule_in_pieces():
    """Item 9: backend/stock_status.py, stock vs ss_i and the target stock
    rop_i, all pieces. A SKU the LP does not plan has no target instead of
    a flat 100."""
    from backend.routers.abc import _stock_status

    assert _stock_status(None, 50.0, 100.0, False) == "NO DATA"
    assert _stock_status(0.0, 50.0, 100.0, True) == "CRITICAL"
    assert _stock_status(22.0, None, None, True) == "NO ROP"
    assert _stock_status(121964.0, 36193.0, 9818340.0, True) == "LOW"
    assert _stock_status(121964.0, 1000.0, 36193.0, True) == "IN STOCK"
    # A stock row with no pieces (no pack size) and no plan: no ROP, not "no data".
    assert _stock_status(None, None, None, True) == "NO ROP"
    assert _stock_status(None, None, None, False) == "NO DATA"


def test_pareto_check_reads_the_running_total_not_a_sum_of_rounded_shares():
    """Unilever's 2025-12 run: 120 shares, each stored to 4 dp, summed to
    0.8501 ("fails") while the true top-20% share was 0.8498. The stored
    cumulative share at the cut is rounded only once."""
    from analytics.classification.abc import pareto_check

    top, rest = 0.00707, (1 - 120 * 0.00707) / 480
    shares = [round(top, 4)] * 120 + [round(rest, 4)] * 480
    cumulative = ([round((i + 1) * top, 4) for i in range(120)]
                  + [round(120 * top + (j + 1) * rest, 4) for j in range(480)])

    assert pareto_check(shares)["passes"] is False  # 120 x 0.0071 = 0.852, the drift
    check = pareto_check(shares, cumulative)
    assert check["top_count"] == 120
    assert check["revenue_share"] == pytest.approx(0.8484)
    assert check["passes"] is True


# ---- stock status follows lp.view (Yuan's permissions proposal, 2026-09-30) ----

def _rows_with_reorder_points():
    base = {"principal": "unilever", "revenue_share": 0.25, "cumulative_share": 0.5,
            "boundary_flag": False, "_period": "2024-02", "has_stock_row": True}
    return [
        {**base, "product_key": 1, "sku_id": "ABOVE", "product_name": "P1", "tier": "A", "current_stock": 120, "reorder_point": 100, "safety_stock": 50},
        {**base, "product_key": 2, "sku_id": "BELOW", "product_name": "P2", "tier": "A", "current_stock": 40, "reorder_point": 100, "safety_stock": 20},
        {**base, "product_key": 3, "sku_id": "NOROP", "product_name": "P3", "tier": "B", "current_stock": 40, "reorder_point": None, "safety_stock": None},
        {**base, "product_key": 4, "sku_id": "EMPTY", "product_name": "P4", "tier": "C", "current_stock": 0, "reorder_point": 100, "safety_stock": 50},
    ]


def _statuses():
    session = FakeSession(_rows_with_reorder_points(), latest_period="2024-02")
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        body = c.get("/abc").json()
    app.dependency_overrides.clear()
    return {i["sku_id"]: i["stock_status"] for i in body["items"]}


def test_stock_status_is_judged_against_the_reorder_point_with_lp_view():
    assert _statuses() == {"ABOVE": "IN STOCK", "BELOW": "LOW", "NOROP": "NO ROP", "EMPTY": "CRITICAL"}


def test_without_lp_view_stock_on_hand_reads_on_hand(monkeypatch):
    """Above/below the reorder point would reveal the LP's figure; being out
    of stock doesn't, so CRITICAL (and NO DATA) stay."""
    from backend import permissions

    monkeypatch.setattr(permissions, "load_overrides", lambda db, user_id: {"lp.view": False})
    assert _statuses() == {"ABOVE": "ON HAND", "BELOW": "ON HAND", "NOROP": "ON HAND", "EMPTY": "CRITICAL"}


def test_status_for_keeps_no_data_and_critical():
    from backend.routers.abc import _status_for

    assert _status_for(None, 50.0, 100.0, False, lp_visible=False) == "NO DATA"
    assert _status_for(0.0, 50.0, 100.0, True, lp_visible=False) == "CRITICAL"
    assert _status_for(500.0, 50.0, 100.0, True, lp_visible=False) == "ON HAND"
    assert _status_for(500.0, 50.0, 100.0, True, lp_visible=True) == "IN STOCK"
    # Below ss_i is CRITICAL with lp.view, but ss_i is the LP's figure: on hand without it.
    assert _status_for(30.0, 50.0, 100.0, True, lp_visible=True) == "CRITICAL"
    assert _status_for(30.0, 50.0, 100.0, True, lp_visible=False) == "ON HAND"
    # Whether the LP plans the product is LP information too.
    assert _status_for(None, None, None, True, lp_visible=False) == "NO DATA"


# ---- 80/20 check minimum, no-target reasons, class shares (2026-10-01) ------

def _ranked(n, principal="unilever", period="2024-02"):
    """n current-run rows with a steep, consistent running total."""
    weights = [0.5 ** i for i in range(n)]
    total = sum(weights)
    rows, cumulative = [], 0.0
    for i, w in enumerate(weights):
        cumulative += w / total
        tier = "A" if cumulative <= 0.80 else ("B" if cumulative <= 0.95 else "C")
        rows.append({"product_key": i + 1, "sku_id": f"R-{i + 1}", "product_name": f"R{i + 1}", "principal": principal,
                     "tier": tier, "revenue_share": round(w / total, 4), "cumulative_share": round(cumulative, 4),
                     "boundary_flag": False, "current_stock": None, "has_stock_row": False, "reorder_point": None,
                     "safety_stock": None, "_period": period})
    return rows


def test_pareto_check_is_not_applicable_below_the_minimum():
    """Del Monte's 2025-12 run ranks 4 categories: the top fifth is ONE
    category, and the page called that a failed 80/20 split (71.1%)."""
    from backend.routers.abc import PARETO_MIN_ITEMS

    session = FakeSession(_ranked(4, principal="delmonte"), latest_period="2024-02")
    check = _get(session, "principal=delmonte")["pareto_check"]
    assert check["status"] == "not_applicable"
    assert check["passes"] is None
    assert check["ranked_count"] == 4 and check["min_items"] == PARETO_MIN_ITEMS
    assert check["reason"].startswith("Too few categories for an 80/20 check (4 ranked")


def test_pareto_check_is_unchanged_at_and_above_the_minimum():
    """From PARETO_MIN_ITEMS up, the check is pareto_check's own verdict."""
    from analytics.classification.abc import pareto_check
    from backend.routers.abc import PARETO_MIN_ITEMS

    for n in (PARETO_MIN_ITEMS, 40):
        rows = _ranked(n)
        check = _get(FakeSession(rows, latest_period="2024-02"), "principal=unilever")["pareto_check"]
        expected = pareto_check([r["revenue_share"] for r in rows], [r["cumulative_share"] for r in rows])
        assert {k: check[k] for k in expected} == expected
        assert check["status"] == ("pass" if expected["passes"] else "fail")
        assert check["reason"] is None


def test_class_shares_come_from_the_running_total_not_rounded_row_shares():
    """Unilever 2026-02: Class B's 194 shares, each rounded to 4 dp, summed to
    0.1493 (14.9%) while B is 14.99% of the month. Built the way the run
    stores it — row shares and the running total each rounded once — the
    sum drifts by more than half a point and the boundaries don't."""
    from backend.routers.abc import _summarize
    from backend.schemas.abc import ABCItem

    true = {"A": (132, 0.79992), "B": (194, 0.14990), "C": (384, 0.05018)}
    items, cumulative = [], 0.0
    for tier, (n, share) in true.items():
        for _ in range(n):
            cumulative += share / n
            items.append(ABCItem(sku_id="x", principal="unilever", tier=tier, tier_period="2026-02",
                                 revenue_share=round(share / n, 4), cumulative_share=round(cumulative, 4),
                                 stock_status="NO DATA"))
    summary = {t.tier: t.revenue_share_total for t in _summarize(items, {"unilever": "2026-02"})[0]}
    for tier, (n, share) in true.items():
        assert summary[tier] == pytest.approx(share, abs=1e-4)
        assert abs(n * round(share / n, 4) - share) > 0.005  # what the old sum read
    assert sum(summary.values()) == pytest.approx(1.0, abs=1e-6)


def test_class_shares_are_summed_when_a_class_is_not_one_block_of_the_ranking():
    """The 12-month Tier A basis sets the class on 12 months while the running
    total ranks one month, so a Class A row can rank below Class B rows.
    Differencing the boundaries then credits A with everything above its
    deepest row (Unilever 2026-02 read A 94.7% / B 0.3%); the rows' own
    shares are summed instead."""
    from backend.routers.abc import _summarize, _tier_shares
    from backend.schemas.abc import ABCItem

    def row(tier, share, cumulative):
        return ABCItem(sku_id="x", principal="unilever", tier=tier, tier_period="2026-02",
                       revenue_share=share, cumulative_share=cumulative, stock_status="NO DATA")

    # Ranked by the month's sales: A, B, then an A product that sold little this month, then C.
    items = [row("A", 0.50, 0.50), row("B", 0.30, 0.80), row("A", 0.15, 0.95), row("C", 0.05, 1.00)]
    assert _tier_shares(items) is None
    summary = {t.tier: t.revenue_share_total for t in _summarize(items, {"unilever": "2026-02"})[0]}
    assert summary == {"A": pytest.approx(0.65), "B": pytest.approx(0.30), "C": pytest.approx(0.05)}


def test_lp_mase_gate_matches_the_forecast_gate():
    from analytics.forecasting.baseline import MASE_GATE
    from backend.routers.abc import LP_MASE_GATE

    assert LP_MASE_GATE == MASE_GATE


def _reason(row, tier="A", tier_period="2026-02", has_cycle=True):
    from backend.routers.abc import _no_target_reason

    base = {"principal": "unilever", "pool_period": "2026-02", "pool_tier": tier}
    return _no_target_reason({**base, **row}, tier, tier_period, has_cycle=has_cycle)


def test_no_target_reason_for_each_way_out_of_the_lp_pool():
    """The LP plans Class A of the latest run whose forecast is 'ok' with
    MASE < 1 (scripts/run_lp.py). Each way out of that pool has its reason."""
    assert _reason({}, tier="B") == ("Not planned: the reorder plan covers Class A only", "not_class_a")
    assert _reason({}, tier="C") == ("Not planned: the reorder plan covers Class A only", "not_class_a")
    assert _reason({"fc_status": "ok", "fc_mase": 1.24}) == (
        "Not planned: forecast accuracy check not passed (MASE 1.24)", "accuracy")
    assert _reason({"fc_status": "ok", "fc_mase": 1.004})[0].endswith("(MASE 1.004)")
    assert _reason({"fc_status": "insufficient_data", "fc_mase": None}) == (
        "Not planned: too little sales history to forecast", "short_history")
    assert _reason({"fc_status": "dead_sku"})[1] == "no_recent_sales"
    assert _reason({"fc_status": "fit_failed"})[1] == "forecast_failed"
    assert _reason({"fc_status": "unreliable"})[1] == "accuracy"
    assert _reason({"fc_status": "ok", "fc_mase": None})[1] == "not_measured"
    assert _reason({"fc_status": None}) == ("Not planned: no forecast exists for it", "no_forecast")
    assert _reason({"fc_status": "ok", "fc_mase": 0.8})[1] == "not_in_plan"
    assert _reason({"fc_status": "ok", "fc_mase": 0.8}, has_cycle=False)[1] == "no_plan"


def test_no_target_reason_follows_the_latest_ranking_not_the_row_tier():
    """A Class A row carried forward (no sales in the plan's month), or shown
    for an earlier month where it was A, is outside the plan all the same."""
    carried = _reason({"pool_tier": None}, tier_period="2025-11")
    assert carried == ("Not planned: the reorder plan covers Class A of the Feb 2026 ranking, "
                       "and this SKU had no sales that month", "not_ranked")
    earlier = _reason({"pool_tier": "B"}, tier_period="2025-11")
    assert earlier == ("Not planned: the reorder plan covers Class A only, and this SKU is Class B "
                       "in the Feb 2026 ranking", "not_class_a")
    assert "this category" in _reason({"principal": "delmonte", "pool_tier": None}, tier_period="2024-12")[0]


class CycleFakeSession(FakeSession):
    """FakeSession with a current LP cycle, so a planned row has a target."""

    def execute(self, stmt, params=None):
        if "MAX(lr.planning_cycle_date)" in str(stmt):
            return FakeResult([{"d": "2026-03-01"}])
        return super().execute(stmt, params)


def _reason_rows():
    base = {"principal": "unilever", "revenue_share": 0.2, "cumulative_share": 0.5, "boundary_flag": False,
            "current_stock": 50, "has_stock_row": True, "_period": "2024-02", "pool_period": "2024-02"}
    return [
        {**base, "product_key": 1, "sku_id": "PLANNED", "product_name": "P1", "tier": "A", "pool_tier": "A",
         "reorder_point": 100, "safety_stock": 20, "fc_status": "ok", "fc_mase": 0.7},
        {**base, "product_key": 2, "sku_id": "MASE", "product_name": "P2", "tier": "A", "pool_tier": "A",
         "reorder_point": None, "safety_stock": None, "fc_status": "ok", "fc_mase": 1.24},
        {**base, "product_key": 3, "sku_id": "SHORT", "product_name": "P3", "tier": "A", "pool_tier": "A",
         "reorder_point": None, "safety_stock": None, "fc_status": "insufficient_data", "fc_mase": None},
        {**base, "product_key": 4, "sku_id": "CLASSB", "product_name": "P4", "tier": "B", "pool_tier": "B",
         "reorder_point": None, "safety_stock": None, "fc_status": None, "fc_mase": None},
    ]


def test_items_carry_the_no_target_reason_and_the_query_joins_the_pool(monkeypatch):
    session = CycleFakeSession(_reason_rows(), latest_period="2024-02")
    items = {i["sku_id"]: i for i in _get(session, "principal=unilever")["items"]}
    assert items["PLANNED"]["stock_status"] == "LOW"
    assert items["PLANNED"]["no_target_reason"] is None and items["PLANNED"]["no_target_code"] is None
    assert items["MASE"]["stock_status"] == "NO ROP"
    assert items["MASE"]["no_target_reason"] == "Not planned: forecast accuracy check not passed (MASE 1.24)"
    assert items["SHORT"]["no_target_code"] == "short_history"
    assert items["CLASSB"]["no_target_reason"] == "Not planned: the reorder plan covers Class A only"
    row_sql = [sql for sql, _ in session.calls if "FROM abc_classification ac" in sql]
    assert row_sql and "pool_run" in row_sql[0] and "DISTINCT ON (f.product_key)" in row_sql[0]

    # Whether the LP plans a product is LP information: hidden without lp.view.
    from backend import permissions

    monkeypatch.setattr(permissions, "load_overrides", lambda db, user_id: {"lp.view": False})
    hidden = _get(CycleFakeSession(_reason_rows(), latest_period="2024-02"), "principal=unilever")["items"]
    assert all(i["no_target_reason"] is None and i["no_target_code"] is None for i in hidden)


# ---- every stock figure says when it was counted (2026-10-03) ----

COUNT_DATES = {"unilever": "2026-04-06", "delmonte": "2025-12-01"}


class CountDateFakeSession(CycleFakeSession):
    """Adds each row's principal's stock count date, but only when the row
    query really joins MAX(snapshot_date) of the latest snapshot by
    principal — a query that dropped the join gets no date, as live."""

    def execute(self, stmt, params=None):
        result = super().execute(stmt, params)
        sql = str(stmt)
        if "FROM abc_classification ac" in sql and "MAX(inv.snapshot_date) AS count_date" in sql \
                and "stock_count.principal = ac.principal" in sql:
            return FakeResult([{**r, "stock_count_date": COUNT_DATES[r["principal"]]} for r in result.all()])
        return result


def test_response_states_the_stock_count_date_and_plan_cycle(monkeypatch):
    """The Technical Adviser's rule: a stock figure says when it was counted
    (Unilever's "Mar 2026" file was counted 6 Apr 2026) and a target stock
    which plan it comes from."""
    body = _get(CountDateFakeSession(_reason_rows(), latest_period="2024-02"), "principal=unilever")
    assert body["stock_count_dates"] == {"unilever": "2026-04-06"}
    assert body["planning_cycle_date"] == "2026-03-01"

    # The plan cycle is LP information; the count date is not.
    from backend import permissions

    monkeypatch.setattr(permissions, "load_overrides", lambda db, user_id: {"lp.view": False})
    hidden = _get(CountDateFakeSession(_reason_rows(), latest_period="2024-02"), "principal=unilever")
    assert hidden["planning_cycle_date"] is None
    assert hidden["stock_count_dates"] == {"unilever": "2026-04-06"}


def test_scope_all_reports_each_principals_own_run_and_marks_both_current():
    """Unilever's latest run is 2026-02, Del Monte's 2025-12. Under 'all' the
    page needs both: tier_a_periods carries each, and neither principal's rows
    read as carried-forward against the other's period."""
    def row(pk, principal, period):
        return {"product_key": pk, "sku_id": f"S{pk}", "product_name": f"P{pk}", "principal": principal, "tier": "A",
                "revenue_share": 0.5, "cumulative_share": 0.5, "boundary_flag": False, "current_stock": None,
                "has_stock_row": False, "reorder_point": None, "safety_stock": None, "_period": period}
    rows = [row(1, "unilever", "2026-02"), row(10, "delmonte", "2025-12"), row(11, "delmonte", "2025-11")]
    body = _get(PeriodResolvingFakeSession(rows, latest_period=None), "classification_period=2026-02")

    assert body["tier_a_periods"] == {"Unilever": "2026-02", "Del Monte": "2025-12"}
    assert body["classification_period"] == "2026-02"  # the scalar is unchanged
    assert {i["product_key"]: i["tier_period"] for i in body["items"]} == {1: "2026-02", 10: "2025-12"}


def test_last_known_leaves_out_a_retired_series_and_says_how_many():
    """BE-3 (2026-10-20): a Del Monte category that stopped existing is not carried past its last real month, so
    it is neither listed nor shown as Non-moving; it is counted in retired_series_count."""
    products = [{"product_key": k, "sku_id": f"DM-{k}", "product_name": f"C{k}", "principal": "delmonte"}
                for k in (10, 11, 12)]
    abc_rows = [
        _abc(10, "A", "2025-12", 0.6, principal="delmonte"),
        _abc(11, "B", "2024-02", 0.3, principal="delmonte", retired=True),
        _abc(12, "C", "2024-02", 0.1, principal="delmonte", retired=True),
    ]
    body = _get(LastKnownFakeSession(abc_rows, products), "view=last_known&principal=delmonte")
    assert [i["product_key"] for i in body["items"]] == [10]
    assert body["count"] == 1 and body["retired_series_count"] == 2
