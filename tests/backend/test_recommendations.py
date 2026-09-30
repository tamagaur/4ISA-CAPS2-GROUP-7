"""
tests/backend/test_recommendations.py — GET /recommendations
(backend/routers/recommendations.py).

New 2026-09-20 alongside the principal-scoping fix; this router had no
tests. Same principal-keyed fake as tests/backend/test_sku.py: the anchor
answer is derived from the :principal bind, and the fixture makes the two
principals disagree about their max inventory period, so an unscoped anchor
produces NULL stock and fails outright rather than merely going unasserted.

Live shape for reference (2026-09-20): lp_recommendation holds 430 Unilever
rows and zero Del Monte rows, so the Del Monte list is legitimately empty.
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


@pytest.fixture(autouse=True)
def clear_overrides():
    """app.dependency_overrides is module-level state on the shared app. A
    test that sets it without the `client` fixture would otherwise leak an
    always-authenticated user into every later test file — which is exactly
    how tests/backend/test_segment.py::test_requires_auth started passing
    a 200 where it asserts a 401."""
    yield
    app.dependency_overrides.clear()


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self, rows, stock_by_period, inventory_period_by_scope, abc_period_by_scope,
                 cycle_by_scope=None, superseded_pending=0,
                 lp_generated_at=None, forecast_generated_at=None):
        self.rows = rows
        self.stock_by_period = stock_by_period
        self.inventory_period_by_scope = inventory_period_by_scope
        self.abc_period_by_scope = abc_period_by_scope
        # The LP's current planning cycle per scope (backend/lp_cycle.py).
        # Defaults to the cycle the sample rows carry, so a fixture written
        # before cycle scoping existed still returns its rows.
        # A real date, like the column — freshness() calls .isoformat() on it.
        self.cycle_by_scope = cycle_by_scope if cycle_by_scope is not None else {
            None: datetime.date(2026, 3, 1), "unilever": datetime.date(2026, 3, 1), "delmonte": None,
        }
        self.superseded_pending = superseded_pending
        self.lp_generated_at = lp_generated_at
        self.forecast_generated_at = forecast_generated_at
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, dict(params)))
        scope = params.get("principal")
        if "MAX(_period) AS p FROM Inventory_Fact_Real" in sql:
            return FakeResult([{"p": self.inventory_period_by_scope.get(scope)}])
        if "MAX(classification_period) AS p FROM ABC_Classification" in sql:
            return FakeResult([{"p": self.abc_period_by_scope.get(scope)}])
        # LP cycle + freshness — must precede the row matcher below, which
        # reads the same table with the same status predicate.
        if "MAX(lr.planning_cycle_date) AS d" in sql:
            return FakeResult([{"d": self.cycle_by_scope.get(scope)}])
        if "MAX(lr.generated_at) AS t" in sql:
            # One run's rows, all as old as lp_generated_at.
            fc_at = params.get("fc_at")
            stale = int(self.lp_generated_at is not None and fc_at is not None and self.lp_generated_at < fc_at)
            return FakeResult([{"t": self.lp_generated_at, "row_count": 1, "stale_count": stale}])
        if "MAX(generated_at) AS t FROM forecast_result" in sql:
            return FakeResult([self.forecast_generated_at])
        if "lr.planning_cycle_date < :cycle" in sql:
            return FakeResult([self.superseded_pending])
        if "FROM lp_recommendation lr" in sql:
            matched = [r for r in self.rows if scope is None or r["principal"] == scope]
            out = []
            for r in matched:
                stock = self.stock_by_period.get((r["product_key"], params.get("inv_period")))
                share = r["revenue_share"] if r["_abc_period"] == params.get("abc_period") else None
                out.append({
                    **r, "current_stock": stock, "stock_value_pesos": None,
                    "revenue_share": share, "avg_monthly_sales_pesos": None,
                })
            return FakeResult(out)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


@pytest.fixture
def sample_rows():
    return [
        {"recommendation_key": 1, "product_key": 1, "sku_id": "U-1", "product_name": "Uni One",
         "principal": "unilever", "q_i": 50.0, "rop_i": 30.0, "ss_i": 10.0, "status": "pending",
         "planning_cycle_date": "2026-03-01", "decided_at": None, "decided_by": None,
         "generated_at": None, "tier": "A", "revenue_share": 0.6, "_abc_period": "2026-02"},
    ]


@pytest.fixture
def session(sample_rows):
    return FakeSession(
        sample_rows,
        stock_by_period={(1, "2026-03"): 120.0},
        inventory_period_by_scope={None: "2026-03", "unilever": "2026-03", "delmonte": "2025-12"},
        abc_period_by_scope={None: "2026-02", "unilever": "2026-02", "delmonte": None},
    )


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
        resp = c.get("/recommendations")
    app.dependency_overrides.clear()
    assert resp.status_code == 401


def test_unilever_stock_resolves(client):
    resp = client.get("/recommendations?principal=unilever")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["current_stock"] == 120.0
    assert items[0]["urgency"] != "NO DATA"


def test_delmonte_returns_empty_not_borrowed_rows(client):
    """Zero Del Monte LP rows live. The list must be honestly empty, never
    Unilever rows leaking through an unscoped anchor."""
    resp = client.get("/recommendations?principal=delmonte")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_anchors_carry_the_principal_bind(client, session):
    client.get("/recommendations?principal=unilever")
    flat = [" ".join(s.split()).lower() for s, _ in session.calls]
    assert not any("max(_period) from inventory_fact_real)" in s for s in flat)
    anchors = [(s, p) for s, p in session.calls if "max(" in s.lower() and " as p " in s.lower()]
    assert anchors, "no anchor query was issued at all"
    assert all(p.get("principal") == "unilever" for _, p in anchors)


def test_abc_join_is_pinned_to_one_period(client, session):
    """The DISTINCT ON walk it replaced mixed classification vintages."""
    client.get("/recommendations?principal=unilever")
    # The ROW query, not the cycle lookup that now precedes it — both read
    # lp_recommendation, so match on the join this assertion is about.
    row_query = next(
        s for s, _ in session.calls
        if "FROM lp_recommendation lr" in s and "abc_classification" in s.lower()
    )
    assert "classification_period = :abc_period" in row_query
    assert "method = 'single'" in row_query


# ─── LP cycle scoping and stock units (2026-09-23) ───────────────────────


def test_superseded_cycles_are_withheld_by_default(client, session):
    """179 pending rows live are leftovers from runs going back to 2023-05.
    They are not recommendations anyone should act on today."""
    body = client.get("/recommendations?principal=unilever").json()
    assert body["planning_cycle_date"] == "2026-03-01"
    row_sql = next(s for s, _ in session.calls
                   if "FROM lp_recommendation lr" in s and "abc_classification" in s.lower())
    assert ":current_cycle" in row_sql, "the default list must be pinned to the current cycle"


def test_cycle_all_is_the_explicit_audit_escape_hatch(client, session):
    client.get("/recommendations?principal=unilever&cycle=all")
    row_sql = next(s for s, _ in session.calls
                   if "FROM lp_recommendation lr" in s and "abc_classification" in s.lower())
    assert ":current_cycle" not in row_sql


def test_no_pending_cycle_returns_empty_not_every_decided_row(sample_rows):
    """'current' with nothing pending has no cycle to scope to — returning
    the whole table there would contradict the filter."""
    session = FakeSession(
        sample_rows, stock_by_period={}, inventory_period_by_scope={"unilever": "2026-03"},
        abc_period_by_scope={"unilever": "2026-02"},
        cycle_by_scope={"unilever": None, None: None},
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        body = c.get("/recommendations?principal=unilever",
                     headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["items"] == []
    assert body["planning_cycle_date"] is None


def test_unconvertible_stock_is_no_data_not_a_false_critical(sample_rows):
    """A product whose cases can't be converted to pieces (no usable pack
    size) must drop out of the comparison, not be judged with the wrong
    unit — which is what made 215 of 429 rows CRITICAL."""
    session = FakeSession(
        sample_rows, stock_by_period={}, inventory_period_by_scope={"unilever": "2026-03"},
        abc_period_by_scope={"unilever": "2026-02"},
    )
    # stock_pieces NULL while the snapshot row exists (cases present).
    session.stock_by_period = {}
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        body = c.get("/recommendations?principal=unilever",
                     headers={"Authorization": f"Bearer {user_token()}"}).json()
    item = body["items"][0]
    assert item["urgency"] == "NO DATA"
    assert item["current_stock"] is None
    assert item["stock_blocked_reason"]


def test_freshness_flags_an_lp_older_than_its_forecasts(sample_rows):
    session = FakeSession(
        sample_rows, stock_by_period={}, inventory_period_by_scope={"unilever": "2026-03"},
        abc_period_by_scope={"unilever": "2026-02"},
        lp_generated_at=datetime.datetime(2026, 8, 24, 7, 12),
        forecast_generated_at=datetime.datetime(2026, 9, 21, 10, 8),
        superseded_pending=179,
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        body = c.get("/recommendations?principal=unilever",
                     headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["freshness"]["is_stale"] is True
    assert body["superseded_count"] == 179


# ---- the LP's settings, each row's tier, whole-unit totals (2026-09-29) ------

def test_lp_settings_the_api_states_are_the_solvers():
    """GET /recommendations' lp_model and GET /dashboard's lp_weights come
    from backend/lp_cycle.py; analytics/optimization/lp.py is what solves.
    Read as text: lp.py imports the pulp solver."""
    import re
    from pathlib import Path
    from statistics import NormalDist

    from backend.lp_cycle import LP_SERVICE_LEVEL_PCT, LP_SERVICE_Z, LP_WEIGHTS

    source = (Path(__file__).resolve().parents[2] / "analytics/optimization/lp.py").read_text(encoding="utf-8")
    w = re.search(r"^W1, W2, W3 = ([0-9.]+), ([0-9.]+), ([0-9.]+)", source, re.M)
    z = re.search(r"^Z_SCORE = ([0-9.]+)", source, re.M)
    assert w and z
    assert [LP_WEIGHTS["cost"], LP_WEIGHTS["service_level"], LP_WEIGHTS["storage"]] == [float(v) for v in w.groups()]
    assert LP_SERVICE_Z == float(z.group(1))
    assert round(NormalDist().cdf(LP_SERVICE_Z) * 100) == LP_SERVICE_LEVEL_PCT


def test_lp_inputs_the_api_states_are_the_ones_run_lp_uses():
    """lp_model_info serves analytics/optimization/lp_inputs.PLACEHOLDERS, the
    dict scripts/run_lp.py takes its defaults from, flagged as placeholders.
    The LP's weeks convention and 3-week rule are the dashboard's own."""
    from analytics.optimization.lp_inputs import PLACEHOLDERS, WEEKS_PER_MONTH
    from backend.lp_cycle import lp_model_info
    from backend.routers.dashboard import AVG_WEEKS_PER_MONTH, POLICY_WEEKS

    info = lp_model_info()
    assert info["inputs"] == PLACEHOLDERS
    assert info["inputs_are_placeholders"] is True
    assert "independent" in info["safety_stock_assumption"]
    assert WEEKS_PER_MONTH == AVG_WEEKS_PER_MONTH
    assert PLACEHOLDERS["target_weeks"] == POLICY_WEEKS


def test_response_carries_the_lp_model_and_each_rows_tier(client):
    body = client.get("/recommendations?principal=unilever").json()
    assert body["lp_model"]["weights"] == {"cost": 0.45, "service_level": 0.35, "storage": 0.2}
    assert body["lp_model"]["service_level_pct"] == 90
    assert body["lp_model"]["inputs_are_placeholders"] is True
    assert body["items"] and all("tier" in item for item in body["items"])


def test_whole_units_round_up_but_ignore_float_noise():
    """The Reorder page's rounding (formatNumber.js wholeUnits), so the
    Dashboard's total equals the sum of the rows a planner sees."""
    from backend.routers.recommendations import whole_units

    assert whole_units(9818339.99) == 9818340
    assert whole_units(1782.0000000002) == 1782
    assert whole_units(10.0) == 10


def _item_row(**overrides):
    row = {"recommendation_key": 1, "sku_id": "U-1", "product_name": "Uni One", "principal": "unilever",
           "planning_cycle_date": "2026-03-01", "status": "pending", "tier": "A", "revenue_share": 0.03,
           "ss_i": 10.0, "current_stock_cases": None, "stock_value_pesos": None, "avg_monthly_sales_pesos": None}
    return {**row, **overrides}


def test_short_units_is_the_lp_arithmetic_since_the_target_stock_run():
    """Since the 2026-09-30 run, q_i = the month's forecast + target (rop_i)
    - stock, less any cut to fit the allocation. The live figures for the
    Reorder page's #1 (filled) and #11 (cut) rows, and an overstocked SKU."""
    from backend.routers.recommendations import _to_item

    filled = _to_item(_item_row(forecast_units=20970.0, rop_i=14418.0, current_stock=22.0, q_i=35366.0))
    assert filled.forecast_units == 20970.0
    assert filled.short_units == 0.0

    cut = _to_item(_item_row(forecast_units=5800.0, rop_i=3867.0, current_stock=8.0, q_i=7524.0))
    assert cut.short_units == pytest.approx(5800.0 + 3867.0 - 8.0 - 7524.0)

    # Stock above forecast + target: the need floors at 0 and orders 0 — not short.
    over = _to_item(_item_row(forecast_units=677.78, rop_i=504.9, current_stock=2689.0, q_i=0.0))
    assert over.short_units == 0.0

    # Float noise under a piece is rounding, not a cut.
    assert _to_item(_item_row(forecast_units=100.0, rop_i=50.0, current_stock=0.0, q_i=149.4)).short_units == 0.0

    # Nothing to work it out from: unknown, never 0.
    assert _to_item(_item_row(forecast_units=None, rop_i=50.0, current_stock=0.0, q_i=10.0)).short_units is None
    assert _to_item(_item_row(forecast_units=100.0, rop_i=50.0, current_stock=None, q_i=10.0)).short_units is None


def test_forecast_is_the_cycle_months_own():
    """The forecast the row is explained by is the one for its planning
    month — joined on the cycle date, never the product alone (which would
    fan a row out across every forecast month)."""
    from backend.routers.recommendations import select_one

    sql, _ = select_one()
    assert "fr.forecast_date = lr.planning_cycle_date" in " ".join(sql.split())
    assert "fr.forecast_value AS forecast_units" in sql


def test_response_carries_forecast_and_short(sample_rows):
    sample_rows[0].update(forecast_units=40.0)  # need = 40 + 30 - 120 < 0 -> 0
    session = FakeSession(
        sample_rows,
        stock_by_period={(1, "2026-03"): 120.0},
        inventory_period_by_scope={None: "2026-03", "unilever": "2026-03", "delmonte": "2025-12"},
        abc_period_by_scope={None: "2026-02", "unilever": "2026-02", "delmonte": None},
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        item = c.get("/recommendations?principal=unilever",
                     headers={"Authorization": f"Bearer {user_token()}"}).json()["items"][0]
    assert item["forecast_units"] == 40.0
    assert item["short_units"] == 0.0
