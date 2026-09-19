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


# --------------------------------------------------------------------------
# GET /segment/summary — added 2026-09-20 with the principal-scoping fix.
# The endpoint had no coverage at all, and the existing FakeSession's
# "FROM sku_traits" branch does params["product_key"], which KeyErrors on
# the summary queries — hence a separate fake rather than overloading it.
# --------------------------------------------------------------------------


class FakeSummaryResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar(self):
        return self._rows[0]["p"] if self._rows else None


class FakeSummarySession:
    """Cohort rows keyed by principal, so an UNSCOPED MAX(cohort_period)
    resolves to Unilever's cohort for a Del Monte request — exactly the
    defect this endpoint carried."""

    def __init__(self, traits_by_principal):
        self.traits_by_principal = traits_by_principal
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        params = params or {}
        self.calls.append((sql, dict(params)))
        scope = params.get("principal")
        if "MAX(cohort_period) AS p FROM sku_traits" in sql:
            pool = (
                [c for rows in self.traits_by_principal.values() for c, _ in rows]
                if scope is None
                else [c for c, _ in self.traits_by_principal.get(scope, [])]
            )
            return FakeSummaryResult([{"p": max(pool)}] if pool else [])
        if "FROM sku_traits st" in sql:
            rows = self.traits_by_principal.get(scope, []) if scope else [
                r for v in self.traits_by_principal.values() for r in v
            ]
            return FakeSummaryResult([t for c, t in rows if c == params.get("cohort")])
        raise AssertionError(f"Unexpected query in FakeSummarySession: {sql}")

    def close(self):
        pass


SUMMARY_TRAITS = {
    "unilever": [("2026-02", {"cv": 0.9, "trend": "up", "revenue_share": 0.045})],
    # Live shape 2026-09-20: sku_traits holds zero Del Monte rows.
    "delmonte": [],
}


def test_summary_unilever_reports_its_own_cohort():
    session = FakeSummarySession(SUMMARY_TRAITS)
    with make_client(session) as c:
        body = c.get("/segment/summary?principal=unilever").json()
    assert body["cohort_period"] == "2026-02"
    assert body["analyzed_count"] == 1


def test_summary_delmonte_cohort_is_null_not_borrowed():
    """Unscoped, MAX(cohort_period) returned Unilever's 2026-02 for a Del
    Monte request. Scoped, it is None."""
    session = FakeSummarySession(SUMMARY_TRAITS)
    with make_client(session) as c:
        body = c.get("/segment/summary?principal=delmonte").json()
    assert body["cohort_period"] is None
    assert body["analyzed_count"] == 0


def test_summary_delmonte_reason_does_not_claim_the_run_never_ran():
    """The run HAS executed; it just does not cover Del Monte. Claiming
    otherwise would be a false statement, not a missing one."""
    session = FakeSummarySession(SUMMARY_TRAITS)
    with make_client(session) as c:
        reason = c.get("/segment/summary?principal=delmonte").json()["blocked_reason"]
    assert "has not been executed" not in reason
    assert "2026-02" in reason and "delmonte" in reason


def test_summary_reports_never_run_only_when_truly_empty():
    session = FakeSummarySession({"unilever": [], "delmonte": []})
    with make_client(session) as c:
        reason = c.get("/segment/summary?principal=delmonte").json()["blocked_reason"]
    assert reason == "The segmentation run has not been executed yet."


def test_summary_cohort_anchor_carries_the_principal_bind():
    session = FakeSummarySession(SUMMARY_TRAITS)
    with make_client(session) as c:
        c.get("/segment/summary?principal=unilever")
    anchors = [(s, p) for s, p in session.calls if "MAX(cohort_period)" in s]
    assert anchors, "no cohort anchor was issued at all"
    assert anchors[0][1].get("principal") == "unilever"
    assert not any("WHERE TRUE" in s for s, _ in session.calls)
