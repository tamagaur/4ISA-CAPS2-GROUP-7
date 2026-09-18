"""
tests/backend/test_segment.py — GET /segment (backend/routers/segment.py).

FakeSession pattern from tests/backend/test_abc.py — never touches Supabase.
Covers the three honest answers the endpoint has: analyzed, not analyzed
(product exists, no Phase-2 rows), and unknown product (404) — plus the
cv_band display thresholds, which are the endpoint's only derived value.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.routers.segment import cv_band


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
    def __init__(self, products, traits=None, segments=None):
        self.products = products  # sku_code -> row
        self.traits = traits or {}  # product_key -> row
        self.segments = segments or {}  # product_key -> [rows]

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        if "FROM product_dimension" in sql:
            row = self.products.get(params["sku"])
            if row and params.get("principal") and row["principal"] != params["principal"]:
                row = None
            return FakeResult([row] if row else [])
        if "FROM sku_traits" in sql:
            row = self.traits.get(params["product_key"])
            return FakeResult([row] if row else [])
        if "FROM sku_segment" in sql:
            return FakeResult(self.segments.get(params["product_key"], []))
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


PRODUCTS = {
    "69767334": {"product_key": 10, "product_name": "SURF 1KG", "principal": "unilever"},
    "11111111": {"product_key": 11, "product_name": "UNSEEN SKU", "principal": "unilever"},
}
TRAITS = {
    10: {"cohort_period": "2026-02", "history_months": 31, "first_sale_period": "2023-08", "longest_run": 31,
         "trend": "up", "cv": 0.898, "restart_flag": False, "stability_group": "churn", "revenue_share_2026_02": 0.045},
}
SEGMENTS = {
    10: [{"scheme": "length_v1", "abc_method": "single", "cohort_period": "2026-02", "bin": "long",
          "bin_reason": "31 months with sales >= 12"}],
}


def make_client(session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_requires_auth():
    app.dependency_overrides[get_db] = lambda: FakeSession(PRODUCTS)
    with TestClient(app) as c:
        resp = c.get("/segment?sku=69767334")
    assert resp.status_code == 401


def test_analyzed_sku_returns_traits_and_verbatim_bin_reason():
    with make_client(FakeSession(PRODUCTS, TRAITS, SEGMENTS)) as c:
        resp = c.get("/segment?sku=69767334&principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["analyzed"] is True
    assert body["not_analyzed_reason"] is None
    assert body["traits"]["trend"] == "up"
    assert body["traits"]["cv"] == pytest.approx(0.898)
    assert body["traits"]["cv_band"] == "medium"
    assert body["segments"][0]["bin_reason"] == "31 months with sales >= 12"


def test_unanalyzed_sku_is_200_not_analyzed_with_reason():
    with make_client(FakeSession(PRODUCTS, TRAITS, SEGMENTS)) as c:
        resp = c.get("/segment?sku=11111111", headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["analyzed"] is False
    assert body["traits"] is None
    assert body["segments"] == []
    assert "sku_traits" in body["not_analyzed_reason"]


def test_unknown_product_is_404():
    with make_client(FakeSession(PRODUCTS)) as c:
        resp = c.get("/segment?sku=nope", headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.status_code == 404


def test_principal_scope_applies_to_product_lookup():
    with make_client(FakeSession(PRODUCTS, TRAITS, SEGMENTS)) as c:
        resp = c.get("/segment?sku=69767334&principal=delmonte", headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.status_code == 404


@pytest.mark.parametrize("cv,band", [(None, None), (0.16, "low"), (0.49, "low"), (0.5, "medium"), (0.99, "medium"), (1.0, "high"), (6.16, "high")])
def test_cv_band_thresholds(cv, band):
    assert cv_band(cv) == band
