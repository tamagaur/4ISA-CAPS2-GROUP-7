"""
tests/backend/test_forecast.py — GET /forecast/{sku_id} (backend/routers/forecast.py).

FakeSession pattern from tests/backend/test_segment.py — never touches
Supabase. Covers what the frontend reads: each point's status / mase /
model_params pass through, the response's principal is the resolved
product's own (it was hard-coded to 'unilever'), a resolved product with no
Forecast_Result rows is a 200 with forecast: [], and scope/unknown are 404.
"""
from __future__ import annotations

import datetime

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


class FakeSession:
    def __init__(self, products, forecasts=None, actuals=None):
        self.products = products  # sku_code -> row
        self.forecasts = forecasts or {}  # product_key -> [rows]
        self.actuals = actuals or {}  # product_key -> [rows], newest first like the query

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        if "FROM Product_Dimension" in sql:
            row = self.products.get(params["sku_id"])
            if row and params.get("principal") and row["principal"] != params["principal"]:
                row = None
            return FakeResult([row] if row else [])
        if "FROM forecast_result" in sql:
            return FakeResult(self.forecasts.get(params["product_key"], []))
        if "FROM unilever_sku_demand_fact_real" in sql:
            return FakeResult(self.actuals.get(params["product_key"], []))
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


PRODUCTS = {
    "21051980": {"product_key": 1, "product_name": "SURF HS STD PWDR", "principal": "unilever"},
    "64861460": {"product_key": 2, "product_name": "NEW LAUNCH SKU", "principal": "unilever"},
    "64980626": {"product_key": 3, "product_name": "TIER C SKU", "principal": "unilever"},
    "DM-ONLY": {"product_key": 4, "product_name": "DEL MONTE ROW", "principal": "delmonte"},
}
MARCH = datetime.date(2026, 3, 1)
FORECASTS = {
    1: [{"forecast_date": MARCH, "forecast_value": 441.91, "confidence_lower": 193.0, "confidence_upper": 691.0,
         "mape": 31.852, "mase": 0.4263, "status": "ok",
         "model_params": {"method": "xgb_ma3_avg", "bin": "long", "sales_months": 37, "ma3_value": 396.0,
                          "components": {"ma3": 396.0, "xgb": 487.827}, "wape": 0.2587}}],
    2: [{"forecast_date": MARCH, "forecast_value": 1190.0, "confidence_lower": None, "confidence_upper": None,
         "mape": None, "mase": None, "status": "insufficient_data",
         "model_params": {"method": "trailing_average", "provisional": True, "ma3_value": 1190.0}}],
}
ACTUALS = {1: [{"calendar_month": "2026-02", "quantity_sold": 436.0}, {"calendar_month": "2026-01", "quantity_sold": 420.0}]}


def make_client(session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def get(client, path):
    return client.get(path, headers={"Authorization": f"Bearer {user_token()}"})


def test_requires_auth():
    app.dependency_overrides[get_db] = lambda: FakeSession(PRODUCTS)
    with TestClient(app) as c:
        resp = c.get("/forecast/21051980")
    assert resp.status_code == 401


def test_served_forecast_carries_status_mase_and_model_params():
    with make_client(FakeSession(PRODUCTS, FORECASTS, ACTUALS)) as c:
        resp = get(c, "/forecast/21051980?principal=unilever")
    assert resp.status_code == 200
    body = resp.json()
    point = body["forecast"][0]
    assert point["status"] == "ok"
    assert point["mase"] == pytest.approx(0.4263)
    assert point["mape"] == pytest.approx(31.852)
    assert point["model_params"]["method"] == "xgb_ma3_avg"
    assert point["model_params"]["components"] == {"ma3": 396.0, "xgb": 487.827}
    # actuals come back oldest first
    assert [a["period"] for a in body["actuals"]] == ["2026-01", "2026-02"]


def test_provisional_row_has_status_and_null_mase():
    with make_client(FakeSession(PRODUCTS, FORECASTS)) as c:
        point = get(c, "/forecast/64861460").json()["forecast"][0]
    assert point["status"] == "insufficient_data"
    assert point["mase"] is None
    assert point["model_params"]["provisional"] is True


def test_principal_is_the_resolved_products_not_hardcoded():
    with make_client(FakeSession(PRODUCTS, FORECASTS)) as c:
        body = get(c, "/forecast/DM-ONLY").json()
    assert body["principal"] == "delmonte"
    assert body["forecast"] == []


def test_resolved_product_without_forecast_is_200_empty():
    with make_client(FakeSession(PRODUCTS, FORECASTS)) as c:
        resp = get(c, "/forecast/64980626")
    assert resp.status_code == 200
    assert resp.json()["forecast"] == []
    assert resp.json()["principal"] == "unilever"


def test_unknown_and_out_of_scope_are_404():
    with make_client(FakeSession(PRODUCTS, FORECASTS)) as c:
        assert get(c, "/forecast/nope").status_code == 404
        assert get(c, "/forecast/21051980?principal=delmonte").status_code == 404
