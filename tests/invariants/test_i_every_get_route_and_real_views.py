"""Invariant I: every GET route the API serves answers against LIVE, and the six `_Real` views exclude labelled rows ON LIVE.

Written 2026-11-17 (final sweep). Before it, most routes' SQL ran only against fake sessions in tests/backend (a fake
answers by SQL-text needle, so a column renamed on live, a join that errors, or a GET that tries to write stayed green);
the invariants executed the SQL of about ten routes. This file asks every GET route once, in-process, on the same
read-only live transaction as the other invariants (conftest.db: SET TRANSACTION READ ONLY, rolled back), each inside its
own savepoint so one failure is reported as itself and not as a cascade. A route not named below FAILS the test: a new
GET route must be added here, with the answer it gives on live.

Hard rule 1's views were checked only in analytics/db/schema.sql (tests/etl/test_real_views.py, source text). A later
migration redefining one, or the practice copy's redefinition reaching live, would have stayed green.
"""
from __future__ import annotations

import pytest

# GET routes NOT asked here, each with why. Everything else must answer 200 (or its declared status below).
NOT_ASKED = {
    # Each starts scripts.demo_session / scripts.batch_status as a child process with its own connection to live,
    # outside this read-only transaction. The month-load panel and its rehearsal cover them.
    "/batch/status": "spawns a child process with its own live connection",
    "/batch/job": "spawns a child process with its own live connection",
    "/batch/checklist": "spawns a child process with its own live connection",
    "/batch/feedback": "spawns a child process with its own live connection",
}
# Declared non-200 answers on live, with why.
DECLARED = {
    # Behind DM_DEMO_ENABLED (default off; tests/conftest.py keeps it off): 404 is the switched-off answer.
    "/demo/index?principal=delmonte": 404,
    "/demo/series?principal=delmonte&key=x": 404,
    "/demo/totals": 404,
}


def _paths(sql, plan) -> dict[str, str]:
    """route template -> concrete path asked on live."""
    sku = next(it["sku_id"] for it in plan["items"])
    key = next(it["recommendation_key"] for it in plan["items"])
    users = sql("SELECT user_id AS id FROM app.users ORDER BY user_id LIMIT 1")
    uid = users[0]["id"] if users else 1
    u = "principal=unilever"
    return {
        "/abc": f"/abc?{u}",
        "/admin/permissions/catalog": "/admin/permissions/catalog",
        "/admin/users/{user_id}/permissions": f"/admin/users/{uid}/permissions",
        "/audit-log": "/audit-log",
        "/audit-log/users": "/audit-log/users",
        "/auth/forgot-password": "/auth/forgot-password",
        "/auth/me": "/auth/me",
        "/auth/mfa": "/auth/mfa",
        "/category-trends": f"/category-trends?{u}",
        "/dashboard": f"/dashboard?{u}",
        "/dashboard/accuracy": "/dashboard/accuracy",
        "/dashboard/class-changes": f"/dashboard/class-changes?{u}",
        "/dashboard/error-decomposition": "/dashboard/error-decomposition",
        "/dashboard/error-decomposition/aggregate": "/dashboard/error-decomposition/aggregate",
        "/dashboard/error-decomposition/concentration": "/dashboard/error-decomposition/concentration",
        "/dashboard/error-decomposition/product/{sku_code}": f"/dashboard/error-decomposition/product/{sku}",
        "/dashboard/forecast-runs": "/dashboard/forecast-runs",
        "/dashboard/idle-stock": f"/dashboard/idle-stock?{u}",
        "/dashboard/pareto": f"/dashboard/pareto?{u}",
        "/dashboard/product-sales": f"/dashboard/product-sales?{u}",
        "/dashboard/stock-detail": f"/dashboard/stock-detail?{u}",
        "/dashboard/yoy": f"/dashboard/yoy?{u}",
        "/data-mode": "/data-mode",
        "/decomposition": f"/decomposition?sku={sku}",
        "/demo/index": "/demo/index?principal=delmonte",
        "/demo/series": "/demo/series?principal=delmonte&key=x",
        "/demo/totals": "/demo/totals",
        "/forecast/{sku_id}": f"/forecast/{sku}?{u}",
        "/fsn": "/fsn",
        "/health": "/health",
        "/inventory/current": f"/inventory/current?{u}",
        "/inventory/movement": f"/inventory/movement?{u}",
        "/inventory/receipt-signals": "/inventory/receipt-signals",
        "/notifications": "/notifications",
        "/pareto": f"/pareto?{u}",
        "/policy-comparison": f"/policy-comparison?{u}",
        "/recommendations": "/recommendations?cycle=all",
        "/recommendations/changes": "/recommendations/changes?state=all",
        "/recommendations/direct-apply-grants": "/recommendations/direct-apply-grants",
        "/recommendations/direct-apply-grants/me": "/recommendations/direct-apply-grants/me",
        "/recommendations/dismissal-requests": "/recommendations/dismissal-requests?state=all",
        "/recommendations/open-requests": "/recommendations/open-requests",
        "/recommendations/stock-observations": "/recommendations/stock-observations",
        "/recommendations/{recommendation_key}/history": f"/recommendations/{key}/history",
        "/segment": f"/segment?sku={sku}",
        "/sku": "/sku",
        "/status": "/status",
        "/users": "/users",
    }


def _get_routes() -> set[str]:
    from tests.backend.test_permissions import _api_routes
    return {r.path for r in _api_routes() if "GET" in r.methods}


def test_every_get_route_is_asked_or_excused(sql, plan):
    routes = _get_routes()
    assert len(routes) > 40, f"the route walk found {len(routes)} GET routes"
    named = set(_paths(sql, plan)) | set(NOT_ASKED)
    assert routes - named == set(), f"GET routes this invariant does not ask (add them): {sorted(routes - named)}"
    assert named - routes == set(), f"routes named here that the app no longer serves: {sorted(named - routes)}"


@pytest.mark.slow_live   # about 60 s: check.sh --full runs it, --fast deselects it (scripts/check.sh)
def test_every_get_route_answers_on_live(api, db, sql, plan):
    client, headers = api
    users = sql("SELECT user_id AS id, email, role FROM app.users ORDER BY user_id LIMIT 1")
    if users:   # the routes that read the caller's own row read a real one
        from backend.auth_utils import create_access_token
        headers = {"Authorization": "Bearer " + create_access_token(
            user_id=users[0]["id"], email=users[0]["email"], role=users[0]["role"] or "admin", full_name="Invariants")}
    bad, asked = [], 0
    for template, path in sorted(_paths(sql, plan).items()):
        want = DECLARED.get(path, 200)
        nested = db.begin_nested()     # a savepoint: a failing route cannot abort the others' transaction
        try:
            r = client.get(path, headers=headers)
            asked += 1
            if r.status_code != want:
                bad.append(f"GET {path} answered {r.status_code} (want {want}): {r.text[:160]}")
            elif want == 200 and r.headers.get("content-type", "").startswith("application/json"):
                r.json()               # parses: no NaN/Infinity reached the body
        except Exception as exc:       # noqa: BLE001  (reported, not swallowed: it fails the test below)
            bad.append(f"GET {path} raised {type(exc).__name__}: {str(exc)[:160]}")
        finally:
            nested.rollback()
    assert asked >= 45, asked
    assert bad == [], "\n".join(bad)


REAL_VIEWS = ("inventory_fact_real", "purchase_fact_real", "sales_fact_real", "salesreturn_fact_real",
              "sellout_fact_real", "unilever_sku_demand_fact_real")


@pytest.mark.parametrize("view", REAL_VIEWS)
def test_real_view_on_live_excludes_labelled_rows(sql, view):
    """Hard rule 1: each `_Real` view is its base table WHERE is_demo = false, as defined on live (not in schema.sql).
    The practice copy's own unilever_sku_demand_fact_real admits one tag; that definition must never be live's."""
    rows = sql("""SELECT pg_get_viewdef(c.oid) AS d FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                  WHERE n.nspname = 'public' AND c.relkind = 'v' AND c.relname = :v""", v=view)
    assert rows, f"view {view} does not exist on live"
    d = " ".join(rows[0]["d"].split()).rstrip(";").lower()
    base = view[: -len("_real")]
    assert f"from {base} where (is_demo = false)" in d, d[-200:]
    assert d.endswith("where (is_demo = false)"), f"{view} has more than the is_demo filter: {d[-200:]}"
    assert "qa_synthetic" not in d and "_src_file" not in d.split(" from ")[-1], d[-200:]
