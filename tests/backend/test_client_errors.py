"""Client mistakes answer 400/422 with a message, never a 500 (QA 2026-10-24, findings 4-7).

Each case below was a reproduced 500: from=abc&to=abc on /recommendations, period=0000-01 on twelve routes, a NUL
character in a text field (including the unauthenticated sign-in password), and a JSON NaN/Infinity literal.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Match

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.periods import PERIOD_PATTERN


class NoDatabase:
    """Any use means the request got past the guard it was meant to stop at."""

    def execute(self, *a, **k):
        raise AssertionError("the request reached the database")

    def __getattr__(self, name):
        raise AssertionError(f"the request reached the database ({name})")


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: NoDatabase()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin(client):
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=2, email="admin@ssmcapstone.com", role="admin", full_name="Admin"))
    return client


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


# ── NUL characters: the unauthenticated sign-in first ────────────────────────────────────────────────────────
def test_sign_in_with_a_nul_in_the_password_is_a_400_not_a_500(client):
    resp = client.post("/auth/login", json={"email": "someone@ssmcapstone.com", "password": "a\u0000b"})
    assert resp.status_code == 400 and "NUL" in resp.json()["detail"]


def test_sign_in_with_a_nul_in_the_email_is_a_400(client):
    resp = client.post("/auth/login", json={"email": "a\u0000@ssmcapstone.com", "password": "x"})
    assert resp.status_code == 400


def test_a_nul_in_a_json_key_is_refused(client):
    assert client.post("/auth/login", json={"pass\u0000word": "x"}).status_code == 400


def test_a_nul_nested_in_a_body_is_refused(admin):
    resp = admin.post("/sku", json={"sku_code": "99999998", "principal": "unilever", "product_name": "x\u0000"})
    assert resp.status_code == 400


@pytest.mark.parametrize("path", [
    "/audit-log?action=a%00b", "/recommendations?status=%00", "/sku?status=a%00", "/forecast/a%00b",
    "/dashboard/error-decomposition/product/a%00b", "/abc?classification_period=2026-02%00",
])
def test_a_nul_in_the_path_or_query_is_a_400(client, path):
    resp = client.get(path)
    assert resp.status_code == 400 and "NUL" in resp.json()["detail"]


def test_an_escaped_backslash_followed_by_u0000_is_not_a_nul(client):
    """The two-character text \u0000 (a backslash, then u0000) is ordinary text, not U+0000."""
    resp = client.post("/auth/login", content=b'{"email":"a@b.org","password":"' + b"\\" * 2 + b'u0000"}',
                       headers={"content-type": "application/json"})
    assert resp.status_code != 400   # it went on to the (absent) database, which this fixture turns into a 500


# ── NaN and Infinity ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_a_json_non_finite_number_is_a_400_not_a_500(admin, literal):
    resp = admin.post("/recommendations/379/quantity-change", content=('{"quantity": %s}' % literal).encode(),
                      headers={"content-type": "application/json"})
    assert resp.status_code == 400 and "NaN" in resp.json()["detail"]


def test_a_non_finite_number_on_the_decision_route_is_a_400(admin):
    resp = admin.patch("/recommendations/379", content=b'{"status":"accepted","reviewed": -Infinity}',
                       headers={"content-type": "application/json"})
    assert resp.status_code == 400


def test_a_body_that_passes_the_guard_reaches_the_route_unchanged(client):
    """The body is read once by the guard and replayed: a missing field is still the framework's 422."""
    resp = client.post("/auth/login", json={"email": "someone@ssmcapstone.com"})
    assert resp.status_code == 422
    assert any(e["loc"][-1] == "password" for e in resp.json()["detail"])


def test_invalid_json_is_left_to_the_framework(client):
    resp = client.post("/auth/login", content=b"{not json", headers={"content-type": "application/json"})
    assert resp.status_code == 422


# ── dates ────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("query", ["from=abc&to=abc", "from=2026-13-45&to=2026-14-45", "from=2026-01-01&to=abc"])
def test_recommendations_dates_that_are_not_dates_are_a_422(admin, query):
    resp = admin.get(f"/recommendations?principal=unilever&{query}")
    assert resp.status_code == 422
    assert any(e["loc"][-1] in ("from", "to") for e in resp.json()["detail"])


def test_the_period_pattern_refuses_year_zero_and_keeps_real_months():
    for bad in ("0000-01", "0000-12", "0001-01", "1899-12", "2100-01", "2026-13", "2026-00", "2026-1", "abcd-01"):
        assert re.fullmatch(PERIOD_PATTERN, bad) is None, bad
    for good in ("2023-01", "2026-02", "2026-12", "1900-01", "2099-12"):
        assert re.fullmatch(PERIOD_PATTERN, good), good


def _period_params():
    """(path, name, pattern) for every 'period'-named query parameter, read from the OpenAPI document (this FastAPI
    includes routers lazily, so app.routes does not list them)."""
    for path, operations in app.openapi()["paths"].items():
        for operation in operations.values():
            for param in operation.get("parameters", []):
                if param["in"] == "query" and "period" in param["name"]:
                    schema = param["schema"]
                    options = schema.get("anyOf") or [schema]
                    yield path, param["name"], next((o.get("pattern") for o in options if o.get("pattern")), None)


def test_no_route_takes_year_zero_as_a_period():
    """Every 'period'-named query parameter that has a pattern must refuse 0000-01, whichever router declares it."""
    patterned = 0
    for path, name, pattern in _period_params():
        if pattern:
            patterned += 1
            assert re.fullmatch(pattern, "0000-01") is None, f"{path} ?{name} admits 0000-01"
    assert patterned >= 12   # the routes the QA reproduced it on, and more


@pytest.mark.parametrize("path", [
    "/dashboard", "/dashboard/accuracy", "/dashboard/class-changes", "/dashboard/error-decomposition",
    "/dashboard/error-decomposition/aggregate", "/dashboard/error-decomposition/concentration",
    "/dashboard/pareto", "/dashboard/product-sales", "/dashboard/yoy", "/category-trends",
])
def test_year_zero_is_a_422_on_the_routes_that_500ed(admin, path):
    resp = admin.get(f"{path}?principal=unilever&period=0000-01")
    assert resp.status_code == 422, path
