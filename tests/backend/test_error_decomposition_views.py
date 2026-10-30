"""
tests/backend/test_error_decomposition_views.py - the three narrower reads of the decomposition tables
(GET /dashboard/error-decomposition/product/{sku}, /aggregate, /concentration, 2026-10-23).

No database: a fake session answers by SQL text. The live test (skipped without SUPABASE_DB_URL, read only)
checks the endpoints' sums against the stored tables.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app

BASE = "/dashboard/error-decomposition"
RANGE = "start_period=2025-01&period=2026-02"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")
    yield
    app.dependency_overrides.clear()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows


class _Session:
    def __init__(self, **by_kind):
        self.k, self.calls, self.info = by_kind, [], {}

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params))
        if "to_regclass('mart.error_decomposition')" in sql:
            return _Result(self.k.get("available", True))
        if "'sales' AS src" in sql:
            return _Result([{"src": "sales", "principal": "unilever", "period": "2026-02", "data_kind": "real",
                             "source_tag": None, "flow": None, "pesos": 1.0, "pieces": None, "recorded_with_tax": False,
                             "placeholder": False, "first_date": None, "last_date": None, "negative_rows": None, "products": None}])
        if "FROM product_dimension pd" in sql and "pd.sku_code = :sku" in sql:
            return _Result(self.k.get("product", []))
        if "r.beyond_pieces > 0 AND r.beyond_pesos IS NULL" in sql:
            return _Result(self.k.get("unpriced", [{"n": 0}]))
        if "GROUP BY r.product_key" in sql:
            return _Result(self.k.get("ranked", []))
        if "GROUP BY principal, tier" in sql:
            return _Result(self.k.get("aggregate", []))
        if "WHERE principal = 'unilever' AND product_key = :pk" in sql:
            return _Result(self.k.get("months", []))
        raise AssertionError(sql)

    def close(self):
        pass


def _call(session, path, role="staff"):
    app.dependency_overrides[get_db] = lambda: session
    token = auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role=role, full_name="Staff")
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(token)
    with TestClient(app) as c:
        return c.get(path, headers={"Authorization": f"Bearer {token}"})


def _get(session, path):
    resp = _call(session, path)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _month(m, tier="A", beyond=5.0, exceeds=True):
    return {"month": m, "tier": tier, "forecast_source": "as_served_calendar", "forecast_pieces": 100.0,
            "actual_pieces": 120.0, "price_per_piece": 10.0, "safety_stock_pieces": 15.0, "ss_method": "rebuilt",
            "over_pieces": 0.0, "absorbed_pieces": 15.0, "beyond_pieces": beyond, "exceeds_safety_stock": exceeds,
            "over_pesos": 0.0, "absorbed_pesos": 150.0, "beyond_pesos": beyond * 10}


def _sums(**over):
    base = {"product_months": 10, "product_months_with_ss": 10, "ss_stored_rows": 0, "ss_rebuilt_rows": 10,
            "exceed_product_months": 2, "priced_product_months": 10, "actual_pieces": 1000.0, "over_pieces": 60.0,
            "absorbed_pieces": 25.0, "beyond_pieces": 15.0, "under_no_ss_pieces": 0.0, "actual_pesos": 5000.0,
            "over_pesos": 300.0, "absorbed_pesos": 100.0, "beyond_pesos": 100.0, "under_no_ss_pesos": 0.0}
    return {**base, **over}


def _ranked(key, pesos):
    return {"product_key": key, "sku_code": f"S{key}", "product_name": f"P{key}", "category_path": "C",
            "tier_first": "A", "tier_last": "A", "beyond_pesos": pesos, "beyond_pieces": pesos / 10,
            "exposure_months": 2, "product_months": 5}


# ---- a. one product ----------------------------------------------------------------

def test_product_months_and_totals():
    s = _Session(product=[{"product_key": 7, "sku_code": "S7", "product_name": "P7", "category_path": "C"}],
                 months=[_month("2025-05", beyond=5.0), _month("2025-06", tier="B", beyond=0.0, exceeds=False)])
    body = _get(s, f"{BASE}/product/S7?{RANGE}")
    assert body["available"] and body["sku_code"] == "S7" and body["period_start"] == "2025-01"
    assert [m["month"] for m in body["months"]] == ["2025-05", "2025-06"]
    assert [m["counterfactual"] for m in body["months"]] == [False, True]
    assert body["totals"] == {"months_scored": 2, "exposure_months": 1, "over_pieces": 0.0, "absorbed_pieces": 30.0,
                              "beyond_pieces": 5.0, "over_pesos": 0.0, "absorbed_pesos": 300.0, "beyond_pesos": 50.0}
    assert "scoring_rule" in body


def test_product_unknown_sku_is_404_and_known_sku_without_months_is_unavailable_not_an_error():
    assert _call(_Session(product=[]), f"{BASE}/product/NOPE?{RANGE}").status_code == 404
    body = _get(_Session(product=[{"product_key": 7, "sku_code": "S7", "product_name": "P7", "category_path": "C"}], months=[]),
                f"{BASE}/product/S7?{RANGE}")
    assert body["available"] is False and body["months"] == [] and "No scored months" in body["blocked_reason"]


# ---- b. aggregate ------------------------------------------------------------------

def test_aggregate_splits_by_principal_and_tier_with_all_last_and_b_c_counterfactual():
    rows = [{"principal": "unilever", "tier": t, **_sums()} for t in ("A", "all", "B", "C")]
    body = _get(_Session(aggregate=rows), f"{BASE}/aggregate?{RANGE}")
    (p,) = body["principals"]
    assert p["principal"] == "unilever" and [t["tier"] for t in p["tiers"]] == ["A", "B", "C", "all"]
    assert [t["counterfactual"] for t in p["tiers"]] == [False, True, True, False]
    assert p["tiers"][0]["beyond_share_of_error_pesos"] == pytest.approx(0.2)
    assert body["served_tier"] == "A" and "counterfactual_note" in body


def test_aggregate_with_nothing_scored_says_so():
    body = _get(_Session(aggregate=[]), f"{BASE}/aggregate?{RANGE}")
    assert body["available"] is False and body["principals"] == [] and body["blocked_reason"]


# ---- c. concentration --------------------------------------------------------------

def test_concentration_ranks_by_pesos_with_a_running_share_of_all_products_not_only_those_listed():
    ranked = [_ranked(1, 500.0), _ranked(2, 300.0), _ranked(3, 100.0), _ranked(4, 100.0)]
    body = _get(_Session(ranked=ranked), f"{BASE}/concentration?{RANGE}&limit=2")
    assert body["total_beyond_pesos"] == 1000.0 and body["products_with_exposure"] == 4 and body["listed"] == 2
    assert [p["product_key"] for p in body["products"]] == [1, 2]
    assert [p["rank"] for p in body["products"]] == [1, 2]
    assert [p["cumulative_share_of_beyond_pesos"] for p in body["products"]] == [0.5, 0.8]
    assert body["products"][0]["share_of_beyond_pesos"] == 0.5
    assert (body["products_for_50_percent"], body["products_for_80_percent"]) == (1, 2)


def test_concentration_reports_products_that_have_exposure_in_pieces_but_no_price():
    body = _get(_Session(ranked=[_ranked(1, 10.0)], unpriced=[{"n": 3}]), f"{BASE}/concentration?{RANGE}")
    assert body["products_beyond_without_price"] == 3 and "no price" in body["basis"]


def test_concentration_asks_for_the_tier_and_orders_in_the_database_by_pesos():
    s = _Session(ranked=[_ranked(1, 10.0)])
    _get(s, f"{BASE}/concentration?{RANGE}&tier=B")
    sql, params = next(c for c in s.calls if "GROUP BY r.product_key" in c[0])
    assert params["tier"] == "B" and "ORDER BY COALESCE(SUM(r.beyond_pesos), 0) DESC" in sql


def test_concentration_with_no_exposure_is_unavailable_and_limit_is_bounded():
    body = _get(_Session(ranked=[]), f"{BASE}/concentration?{RANGE}")
    assert body["available"] is False and body["products"] == [] and body["products_for_50_percent"] is None
    assert _call(_Session(ranked=[]), f"{BASE}/concentration?{RANGE}&limit=0").status_code == 422
    assert _call(_Session(ranked=[]), f"{BASE}/concentration?{RANGE}&tier=Z").status_code == 422


# ---- shared ------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/product/S7", "/aggregate", "/concentration"])
def test_del_monte_is_blocked_and_a_missing_mart_is_reported(path):
    body = _get(_Session(), f"{BASE}{path}?principal=delmonte")
    assert body["available"] is False and "category grain" in body["blocked_reason"]
    body = _get(_Session(available=False), f"{BASE}{path}?{RANGE}")
    assert body["available"] is False and "0063" in body["blocked_reason"]


def test_the_three_routes_use_the_same_permission_as_the_existing_decomposition_route():
    from backend.routers import dashboard_range as dr
    perms = {}
    for route in dr.router.routes:
        if route.path.startswith(BASE):
            perms[route.path] = [d.call.__qualname__ for d in route.dependant.dependencies if "permission" in d.call.__qualname__.lower()]
    assert len(perms) == 4
    assert all(v == perms[BASE] != [] for v in perms.values())


def test_the_views_only_read():
    import inspect
    from backend import marts
    for fn in (marts.decomposition_by_product, marts.decomposition_aggregate, marts.decomposition_concentration):
        src = inspect.getsource(fn).upper()
        assert not any(w in src for w in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE"))


# ---- live, read only ---------------------------------------------------------------

live = pytest.mark.skipif(not os.environ.get("SUPABASE_DB_URL"), reason="live DB not configured (SUPABASE_DB_URL unset)")


@live
def test_live_views_agree_with_the_stored_tables():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from backend import marts
    engine = create_engine(os.environ["SUPABASE_DB_URL"])
    try:
        with Session(engine) as db:
            db.execute(text("SET TRANSACTION READ ONLY"))  # first statement of the transaction, never session-level
            if not marts.decomposition_available(db):
                pytest.skip("migration 0063 not applied")
            conc = marts.decomposition_concentration(db, "2024-01", "2026-02", limit=500)
            stored = db.execute(text("SELECT COALESCE(SUM(beyond_pesos), 0) FROM mart.error_decomposition_row "
                                     "WHERE principal = 'unilever' AND month BETWEEN '2024-01' AND '2026-02'")).scalar()
            agg = marts.decomposition_aggregate(db, "2024-01", "2026-02")
            db.rollback()
    finally:
        engine.dispose()
    assert conc["total_beyond_pesos"] == pytest.approx(float(stored), abs=0.5)
    shares = [p["cumulative_share_of_beyond_pesos"] for p in conc["products"]]
    assert shares == sorted(shares)
    if conc["listed"] == conc["products_with_exposure"]:  # the full list ends at the whole
        assert shares[-1] == pytest.approx(1.0)
    else:
        assert shares[-1] < 1.0
    (uni,) = [p for p in agg["principals"] if p["principal"] == "unilever"]
    allrow = next(t for t in uni["tiers"] if t["tier"] == "all")
    assert allrow["beyond_pesos"] == pytest.approx(float(stored), abs=0.5)


def test_every_decomposition_response_states_its_figures_basis():
    """Audit A6 (2026-10-30): window, tier filter and counterfactual inclusion are stated; the default tier is unchanged."""
    from backend.routers import dashboard_range as dr

    b = dr._decomposition_basis("2025-03", "2026-02", tier_filter="all", applies_to=["x"], counterfactual_included=True)
    assert b["window"] == {"start": "2025-03", "end": "2026-02"} and b["tier_filter"] == "all"
    assert b["served_tiers"] == ["A"] and b["counterfactual_tiers"] == ["B", "C"] and b["counterfactual_rows_included"] is True
    import inspect
    assert inspect.signature(dr.get_error_decomposition).parameters["tier"].default.default == "all"
