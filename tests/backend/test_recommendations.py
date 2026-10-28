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

from analytics.params import abc_method_sql
from backend import auth_utils, data_notes
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
        self.lp_run = None  # the lp_run row stored_run finds; None = table not applied
        # The live shape: Unilever's '2026-02' count (taken 2 Mar 2026) opens
        # the 2026-03 cycle; its '2026-03' count was taken on 6 Apr 2026.
        self.count_date_by_period = {"2026-02": datetime.date(2026, 3, 2), "2026-03": datetime.date(2026, 4, 6),
                                     "2025-12": datetime.date(2025, 12, 1)}
        # backend/stock_units.STOCK_COUNTS_SQL: {(principal, period): (row_count,
        # first_date, last_date)}. Unilever's count of 2026-02, counted
        # 2026-03-02, opens the sample rows' cycle 2026-03.
        self.stock_counts = {("unilever", "2026-02"): (812, datetime.date(2026, 3, 2), datetime.date(2026, 3, 2))}
        self.calls: list[tuple[str, dict]] = []
        # Migration 0042's review_flag table and PO Qty columns
        # (recommendations._present). Off by default: the tests written
        # before them see the database they were written against.
        self.present = {"review_flag": False, "on_order": False}

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, dict(params)))
        scope = params.get("principal")
        if "to_regclass('review_flag')" in sql:
            return FakeResult([self.present])
        # backend/lp_cycle.stored_run (migration 0037). Before every
        # lp_recommendation matcher: its subquery reads that table too.
        if "to_regclass('lp_run')" in sql:
            return FakeResult([{"present": self.lp_run is not None}])
        if "FROM lp_run r" in sql:
            return FakeResult([self.lp_run] if self.lp_run else [])
        if "MAX(_period) AS p FROM Inventory_Fact_Real" in sql:
            return FakeResult([{"p": self.inventory_period_by_scope.get(scope)}])
        if "MAX(classification_period) AS p FROM ABC_Classification" in sql:
            return FakeResult([
                {"principal": who, "p": self.abc_period_by_scope.get(who)}
                for who in (("unilever", "delmonte") if scope is None else (scope,))
            ])
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
        # label_context: one row of dates, for the page's period labels.
        if "MAX(snapshot_date) FROM inventory_fact_real" in sql:
            count_date = self.count_date_by_period.get(params.get("inv_period"))
            return FakeResult([{"count_date": count_date, "sales_start": "2025-12", "sales_end": "2026-02"}])
        if "lr.planning_cycle_date < :cycle" in sql:
            return FakeResult([self.superseded_pending])
        if "GROUP BY inv.principal, inv._period" in sql:
            period = params["count_period"]
            return FakeResult([
                {"principal": who, "period": p, "row_count": n, "first_date": first, "last_date": last}
                for (who, p), (n, first, last) in self.stock_counts.items() if p == period
            ])
        # cycle=all lists its cycles first, then reads each one's rows.
        if "SELECT DISTINCT lr.planning_cycle_date AS d" in sql:
            cycles = {datetime.date.fromisoformat(r["planning_cycle_date"])
                      for r in self.rows if scope is None or r["principal"] == scope}
            return FakeResult([{"d": d} for d in sorted(cycles)])
        if "FROM lp_recommendation lr" in sql:
            matched = [r for r in self.rows if scope is None or r["principal"] == scope]
            out = []
            for r in matched:
                stock = self.stock_by_period.get((r["product_key"], params.get("inv_period")))
                share = r["revenue_share"] if r["_abc_period"] == params.get("abc_p_" + r["principal"]) else None
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
        stock_by_period={(1, "2026-02"): 120.0, (1, "2026-03"): 7.0},  # opening count, then the later one
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
    assert "classification_period = CASE principal" in row_query
    assert abc_method_sql() in row_query   # each principal's Tier A basis (migration 0044)


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
    # stock_pieces NULL while the snapshot row exists (cases present) —
    # projected explicitly since 2026-10-01, when a product with NO row
    # became 0 on hand instead (test_not_in_stock_count_is_zero_as_the_lp_reads_it).
    sample_rows[0].update(in_stock_count=True, current_stock_cases=42.0)
    session = FakeSession(
        sample_rows, stock_by_period={}, inventory_period_by_scope={"unilever": "2026-03"},
        abc_period_by_scope={"unilever": "2026-02"},
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        body = c.get("/recommendations?principal=unilever",
                     headers={"Authorization": f"Bearer {user_token()}"}).json()
    item = body["items"][0]
    assert item["urgency"] == "NO DATA"
    assert item["current_stock"] is None
    assert item["stock_not_in_count"] is False
    assert "pack size" in item["stock_blocked_reason"]
    assert item["priority_score"] is None  # unranked, never ranked as zero


# ---- not in the stock count = 0, as the LP reads it; pack size (2026-10-01) --

def test_not_in_stock_count_is_zero_as_the_lp_reads_it():
    """scripts/run_lp.py plans a product missing from its principal's latest
    stock count as 0 on hand (the file lists no zero-stock rows). The API
    read it as 'NO DATA', so the page counted 37 cut SKUs where the LP cut
    40. Live figures for 64971078, one of the three: cut 1,272 pieces."""
    from backend.routers.recommendations import _to_item

    item = _to_item(_item_row(
        in_stock_count=False, current_stock=None, forecast_units=3456.0, rop_i=3364.96, q_i=5549.27,
        revenue_share=0.0025, avg_monthly_pieces=900.0, pack_size=48,
    ))
    assert item.stock_not_in_count is True
    assert item.current_stock == 0.0
    assert item.stock_blocked_reason is None
    assert item.urgency == "CRITICAL"
    assert item.short_units == pytest.approx(3456.0 + 3364.96 - 5549.27)
    assert item.stockout_gap == 3364.96
    assert item.priority_score == pytest.approx(0.0025 * 3364.96, abs=1e-4)
    assert item.days_of_cover == 0.0  # nothing on hand, sales known
    assert item.pack_size == 48.0


def test_no_count_for_the_principal_stays_no_data():
    """A missing row only means 0 when the principal WAS counted at that
    snapshot. With no count at all (in_stock_count NULL) — or a caller that
    doesn't project the flag — it says nothing, so 'NO DATA' as before."""
    from backend.routers.recommendations import _to_item

    for row in (_item_row(in_stock_count=None, current_stock=None, forecast_units=100.0, rop_i=50.0, q_i=10.0),
                _item_row(current_stock=None, forecast_units=100.0, rop_i=50.0, q_i=10.0)):
        item = _to_item(row)
        assert item.urgency == "NO DATA"
        assert item.current_stock is None
        assert item.stock_not_in_count is False
        assert item.short_units is None
        assert item.stock_blocked_reason


def test_missing_from_a_count_that_lists_zeros_stays_no_data():
    """Only Unilever's stock file omits zero-stock items (0 of 27,321 raw SOH
    rows read 0/0, checked 2026-10-02). Del Monte's inventory files list
    Quantity-0 rows, so a Del Monte product missing from one is unknown, not
    0 on hand (backend/stock_status.COUNT_OMITS_ZERO_STOCK)."""
    from backend.routers.recommendations import _to_item

    item = _to_item(_item_row(principal="delmonte", in_stock_count=False, current_stock=None,
                              forecast_units=100.0, rop_i=50.0, q_i=10.0))
    assert item.urgency == "NO DATA"
    assert item.current_stock is None
    assert item.stock_not_in_count is False
    assert "lists zero-stock items" in item.stock_blocked_reason


def test_not_in_count_reaches_the_response(sample_rows):
    sample_rows[0].update(in_stock_count=False, forecast_units=40.0, pack_size=12)
    session = FakeSession(
        sample_rows, stock_by_period={}, inventory_period_by_scope={"unilever": "2026-03"},
        abc_period_by_scope={"unilever": "2026-02"},
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        item = c.get("/recommendations?principal=unilever",
                     headers={"Authorization": f"Bearer {user_token()}"}).json()["items"][0]
    assert item["stock_not_in_count"] is True
    assert item["current_stock"] == 0.0
    assert item["urgency"] == "CRITICAL"
    assert item["short_units"] == pytest.approx(40.0 + 30.0 - 50.0)  # forecast + target - q_i
    assert item["priority_score"] == pytest.approx(0.6 * 30.0)
    assert item["pack_size"] == 12.0


def test_row_query_carries_pack_size_and_the_count_flag():
    """pack_size uses stock_units' usable-number rule on the row's own
    Product_Dimension; the count flag is FALSE only when the principal has
    a stock count at :inv_period that the product is missing from."""
    from backend.routers.recommendations import select_one

    sql = " ".join(select_one()[0].split())
    assert "CASE WHEN pd.pack_size ~ '^[0-9]+(\\.[0-9]+)?$' AND pd.pack_size::numeric > 0 THEN pd.pack_size::numeric END AS pack_size" in sql
    assert "WHEN inv.product_key IS NOT NULL THEN TRUE WHEN counted.principal IS NOT NULL THEN FALSE END AS in_stock_count" in sql
    assert "SELECT DISTINCT principal FROM inventory_fact_real WHERE _period = :inv_period" in sql
    assert "counted.principal = pd.principal" in sql


def test_pack_size_is_passed_through_or_none():
    from backend.routers.recommendations import _to_item

    assert _to_item(_item_row(current_stock=10.0, rop_i=50.0, q_i=10.0, pack_size=288)).pack_size == 288.0
    assert _to_item(_item_row(current_stock=10.0, rop_i=50.0, q_i=10.0, pack_size=None)).pack_size is None
    assert _to_item(_item_row(current_stock=10.0, rop_i=50.0, q_i=10.0)).pack_size is None


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
    Both read analytics.params, so they are the same objects."""
    from statistics import NormalDist

    from analytics import params
    from analytics.optimization import lp
    from backend.lp_cycle import LP_SERVICE_LEVEL_PCT, LP_SERVICE_Z, LP_WEIGHTS

    assert LP_WEIGHTS is params.LP_WEIGHTS and LP_SERVICE_Z is params.SERVICE_Z is lp.Z_SCORE
    assert [LP_WEIGHTS["cost"], LP_WEIGHTS["service_level"], LP_WEIGHTS["storage"]] == [lp.W1, lp.W2, lp.W3]
    assert round(NormalDist().cdf(LP_SERVICE_Z) * 100) == LP_SERVICE_LEVEL_PCT


def test_lp_inputs_the_api_states_are_the_ones_run_lp_uses():
    """lp_model_info serves analytics/params.PLACEHOLDERS, the
    dict scripts/run_lp.py takes its defaults from, flagged as placeholders.
    The LP's weeks convention and 3-week rule are the dashboard's own."""
    from analytics.params import PLACEHOLDERS, WEEKS_PER_MONTH
    from backend.lp_cycle import lp_model_info
    from backend.routers.dashboard import AVG_WEEKS_PER_MONTH, POLICY_WEEKS

    info = lp_model_info()
    assert info["inputs"] == PLACEHOLDERS
    assert info["inputs_are_placeholders"] is True
    assert "independent" in info["safety_stock_assumption"]
    assert WEEKS_PER_MONTH == AVG_WEEKS_PER_MONTH
    assert PLACEHOLDERS["target_weeks"] == POLICY_WEEKS


def test_lp_model_states_defaults_when_no_run_is_recorded(client):
    """Item 8: without lp_run (migration 0037 unapplied) the model is the
    defaults, and says so."""
    body = client.get("/recommendations?principal=unilever").json()
    assert body["lp_model"]["inputs_source"] == "defaults"
    assert body["lp_model"]["run"] is None


def test_lp_model_serves_what_the_stored_run_used(session, client):
    """Item 8: with an lp_run behind the current cycle, the API states that
    run's inputs, not the defaults, and names the ones that differ."""
    from analytics.params import PLACEHOLDERS

    inputs = {**PLACEHOLDERS, "allocation_pct": 108.0}
    session.lp_run = {
        "run_key": 7, "planning_cycle_date": datetime.date(2026, 3, 1), "principal_scope": "both",
        "inputs": inputs, "code_version": "abc123",
        "created_at": datetime.datetime(2026, 3, 2, 8, 0, tzinfo=datetime.timezone.utc),
        "model": {"weights": {"cost": 0.45, "service_level": 0.35, "storage": 0.2},
                  "z_score": 1.28, "service_level_pct": 90,
                  "allocation": {"pct": 108.0, "unit": "pieces", "basis_year": 2025}},
    }
    lp_model = client.get("/recommendations?principal=unilever").json()["lp_model"]
    assert lp_model["inputs_source"] == "run"
    assert lp_model["inputs"]["allocation_pct"] == 108.0
    assert lp_model["inputs_differing_from_defaults"] == ["allocation_pct"]
    assert lp_model["run"]["run_key"] == 7 and lp_model["allocation"]["basis_year"] == 2025


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
        stock_by_period={(1, "2026-02"): 120.0, (1, "2026-03"): 7.0},  # opening count, then the later one
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


def test_response_states_the_periods_its_figures_were_read_at(client, session):
    """The page labels every number with its period (2026-10-02): the stock
    count's own date, the ABC month revenue share is from, and the sales
    months cover averages. Since the stock-timing fix (2026-10-03) the stock
    is the count that OPENS the cycle: for 2026-03, the '2026-02' count of
    2 Mar 2026, not the later '2026-03' count of 6 Apr 2026."""
    body = client.get("/recommendations?principal=unilever").json()
    assert body["stock_period"] == "2026-02"
    assert body["stock_count_date"] == "2026-03-02"
    assert body["abc_period"] == "2026-02"
    assert (body["cover_sales_start"], body["cover_sales_end"]) == ("2025-12", "2026-02")
    # The count date is read in the same principal scope as the stock itself.
    sql, params = next((s, p) for s, p in session.calls if "MAX(snapshot_date)" in s)
    assert params["inv_period"] == "2026-02" and params["principal"] == "unilever"
    assert "principal = :principal" in sql


def test_period_labels_are_none_without_a_stock_period(session, client):
    session.inventory_period_by_scope["delmonte"] = None
    body = client.get("/recommendations?principal=delmonte").json()
    assert body["stock_count_date"] is None and body["stock_period"] is None
    assert not any("MAX(snapshot_date)" in s for s, _ in session.calls)
# ---- stock timing (2026-10-03) ----------------------------------------------
# The rows are checked against the count that OPENS their cycle, the one
# scripts/run_lp.py now plans from, never the latest (counted after the
# month's sales). The response says which count and when it was taken.


def _get(session, url):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        return c.get(url, headers={"Authorization": f"Bearer {user_token()}"}).json()


def _row_queries(session):
    return [(s, p) for s, p in session.calls if "FROM lp_recommendation lr" in s and "abc_classification" in s.lower()]


def test_rows_are_checked_against_the_cycles_opening_count(session):
    body = _get(session, "/recommendations?principal=unilever")
    assert [p["inv_period"] for _, p in _row_queries(session)] == ["2026-02"]
    assert body["items"][0]["current_stock"] == 120.0  # the 2026-02 count, not the later 7.0
    assert body["stock_counts"] == [{
        "cycle": "2026-03-01", "principal": "unilever", "period": "2026-02", "role": "opening", "available": True,
        "counted_on": "2026-03-02", "counted_on_note": None, "row_count": 812,
        "flag": data_notes.OPENING_COUNT_RULINGS[("unilever", "2026-02")][1], "reason": None,
        "opening_basis": "count",
    }]


def test_a_missing_opening_count_is_reported_not_replaced(sample_rows):
    """No 2026-02 count: the later 2026-03 one must not stand in. Each row
    and the response carry the reason the app shows."""
    sample_rows[0].update(in_stock_count=None)
    session = FakeSession(
        sample_rows, stock_by_period={(1, "2026-03"): 7.0},
        inventory_period_by_scope={"unilever": "2026-03"}, abc_period_by_scope={"unilever": "2026-02"},
    )
    session.stock_counts = {("unilever", "2026-03"): (785, datetime.date(2026, 4, 6), datetime.date(2026, 4, 6))}
    body = _get(session, "/recommendations?principal=unilever")
    reason = "no opening stock count for March 2026: unilever has no stock count for February 2026"
    assert body["stock_counts"][0]["available"] is False and body["stock_counts"][0]["reason"] == reason
    item = body["items"][0]
    assert item["current_stock"] is None and item["urgency"] == "NO DATA"
    assert item["stock_blocked_reason"] == reason


def test_cycle_all_reads_each_cycle_at_its_own_opening_count(sample_rows):
    sample_rows.append({**sample_rows[0], "recommendation_key": 2, "planning_cycle_date": "2026-01-01"})
    session = FakeSession(
        sample_rows, stock_by_period={}, inventory_period_by_scope={"unilever": "2026-03"},
        abc_period_by_scope={"unilever": "2026-02"},
    )
    body = _get(session, "/recommendations?principal=unilever&cycle=all")
    # Newest cycle first, each against the month before it.
    assert [p["inv_period"] for _, p in _row_queries(session)] == ["2026-02", "2025-12"]
    assert [(c["cycle"], c["period"]) for c in body["stock_counts"]] == [("2026-03-01", "2026-02"), ("2026-01-01", "2025-12")]


def test_a_decision_returns_the_row_against_its_cycles_opening_count():
    """PATCH re-reads the decided row; its stock is its own cycle's opening
    count, as GET showed it, not the latest."""
    from backend.routers.recommendations import update_recommendation
    from backend.schemas.recommendations import RecommendationDecision

    class _PatchSession:
        def __init__(self):
            self.calls: list[tuple[str, dict]] = []

        def execute(self, stmt, params=None):
            sql = str(stmt)
            self.calls.append((sql, dict(params or {})))
            if "UPDATE lp_recommendation" in sql:
                return FakeResult([{"sku": "U-1", "planning_cycle_date": datetime.date(2026, 3, 1)}])
            if "MAX(classification_period) AS p FROM ABC_Classification" in sql:
                return FakeResult([{"principal": "unilever", "p": "2026-02"}])
            if "FROM lp_recommendation lr" in sql:
                return FakeResult([_item_row(current_stock=120.0, rop_i=30.0, q_i=50.0)])
            return FakeResult([])  # the audit-log insert

        def commit(self):
            pass

        def rollback(self):
            pass

    db = _PatchSession()
    item = update_recommendation(1, RecommendationDecision(status="accepted"), db=db,
                                 current_user=auth_utils.decode_access_token(user_token()))
    assert item.current_stock == 120.0
    row_params = next(p for s, p in db.calls if "FROM lp_recommendation lr" in s)
    assert row_params["inv_period"] == "2026-02"


# ---- on order and the review flag (2026-10-04, migration 0042) -------------
# on_order is the opening count's PO Qty in pieces, information only (its
# meaning is unverified, DEC-34); unknown is None with a reason, never 0. A product flagged for review is never accepted without a
# person confirming it (PATCH reviewed=true), so bulk accept can't take it.


def _counted(**overrides):
    return _item_row(**{"current_stock": 120.0, "rop_i": 30.0, "q_i": 50.0, "in_stock_count": True,
                        "on_order_pieces": 576.0, "on_order_cases": 2.0, "on_order_unparsed": 0, **overrides})


def test_on_order_is_the_counts_po_qty_shown_but_never_subtracted():
    """DEC-34 (2026-10-04): PO Qty's meaning is unverified, so on_order is
    information only — labelled, and no quantity on the row moves with it."""
    from backend.routers.recommendations import ON_ORDER_NOTE, _to_item
    from backend.schemas.recommendations import RecommendationItem

    row = _counted(q_i=1000.0, forecast_units=900.0)
    item = _to_item(row, {"review_flag": True, "on_order": True})
    assert (item.on_order, item.on_order_cases, item.on_order_blocked_reason) == (576.0, 2.0, None)
    assert item.on_order_note == ON_ORDER_NOTE and "unverified" in ON_ORDER_NOTE and "never subtracted" in ON_ORDER_NOTE
    without = _to_item({**row, "on_order_pieces": None, "on_order_cases": None, "on_order_unparsed": None})
    for field in ("q_i", "rop_i", "ss_i", "short_units", "stockout_gap", "priority_score", "urgency"):
        assert getattr(item, field) == getattr(without, field), field
    assert not any("net" in f for f in RecommendationItem.model_fields if f.startswith(("q_", "on_order")))
    # The file had a blank PO Qty: 0 is the figure as recorded.
    assert _to_item(_counted(on_order_pieces=0.0, on_order_cases=0.0)).on_order == 0.0


def test_on_order_unknown_is_none_with_a_reason_never_zero():
    from backend.routers.recommendations import _to_item

    cases = {
        "not loaded yet": (_counted(), {"review_flag": True, "on_order": False}, "migration 0042"),
        "loaded before 0042": (_counted(on_order_unparsed=3, on_order_pieces=None, on_order_cases=None), None,
                               "not reloaded while its meaning is unverified"),
        "no pack size": (_counted(on_order_pieces=None), None, "no usable pack size"),
        "Del Monte": (_counted(principal="delmonte"), None, "no purchase-order column"),
        "not in the count": (_counted(in_stock_count=False, current_stock=None, on_order_unparsed=None,
                                      on_order_pieces=None, on_order_cases=None), None, "not in the cycle's opening"),
    }
    for name, (row, present, reason) in cases.items():
        item = _to_item(row, present)
        assert item.on_order is None, name
        assert reason in item.on_order_blocked_reason, name


def test_row_query_reads_0042_only_where_it_exists():
    from backend.routers.recommendations import select_one
    from backend.stock_units import ON_ORDER_ABSENT_SQL, ON_ORDER_AT_PERIOD_SQL

    on, _ = select_one(present={"review_flag": True, "on_order": True})
    assert ON_ORDER_AT_PERIOD_SQL in on and "FROM review_flag" in on
    assert "rf.planning_cycle_date = lr.planning_cycle_date" in " ".join(on.split())
    off, _ = select_one(present={"review_flag": False, "on_order": False})
    assert ON_ORDER_ABSENT_SQL in off and "FROM review_flag" not in off and "po_qty" not in off
    assert "{_" not in on + off  # every placeholder filled


def test_review_flag_reaches_the_response(sample_rows):
    sample_rows[0].update(needs_review=True, review_reasons=["collapse", "over_forecast_run"],
                          review_over_run_months=6, review_collapse_ratio=0.1836,
                          on_order_pieces=288.0, on_order_cases=1.0, on_order_unparsed=0, in_stock_count=True)
    session = FakeSession(
        sample_rows, stock_by_period={(1, "2026-02"): 120.0},
        inventory_period_by_scope={"unilever": "2026-03"}, abc_period_by_scope={"unilever": "2026-02"},
    )
    session.present = {"review_flag": True, "on_order": True}
    item = _get(session, "/recommendations?principal=unilever")["items"][0]
    assert item["needs_review"] is True
    assert item["review_reasons"] == ["collapse", "over_forecast_run"]
    assert (item["review_over_run_months"], item["review_collapse_ratio"]) == (6, 0.1836)
    assert item["on_order"] == 288.0 and "q_net_of_on_order" not in item
    assert "unverified" in item["on_order_note"]


def test_not_assessed_is_none_not_false(client):
    item = client.get("/recommendations?principal=unilever",
                      headers={"Authorization": f"Bearer {user_token()}"}).json()["items"][0]
    assert item["needs_review"] is None and item["review_reasons"] == []


class _GuardSession:
    """PATCH with review_flag present; `flagged` = the row's reasons or None."""

    def __init__(self, flagged):
        self.flagged = flagged
        self.calls: list[str] = []
        self.audit: list[dict] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append(sql)
        if "to_regclass('review_flag')" in sql:
            return FakeResult([{"review_flag": True, "on_order": True}])
        if "JOIN review_flag rf" in sql:
            return FakeResult([{"reasons": self.flagged}] if self.flagged else [])
        if "UPDATE lp_recommendation" in sql:
            return FakeResult([{"sku": "U-1", "planning_cycle_date": datetime.date(2026, 3, 1)}])
        if "MAX(classification_period) AS p FROM ABC_Classification" in sql:
            return FakeResult([{"principal": "unilever", "p": "2026-02"}])
        if "FROM lp_recommendation lr" in sql:
            return FakeResult([_counted(needs_review=bool(self.flagged), review_reasons=self.flagged or [])])
        if "audit_log" in sql.lower():
            self.audit.append(dict(params or {}))
        return FakeResult([])

    def commit(self):
        pass

    def rollback(self):
        pass


def _decide(db, **body):
    from backend.routers.recommendations import update_recommendation
    from backend.schemas.recommendations import RecommendationDecision

    return update_recommendation(1, RecommendationDecision(**body), db=db,
                                 current_user=auth_utils.decode_access_token(user_token()))


def test_a_flagged_row_is_never_accepted_without_review():
    from fastapi import HTTPException

    db = _GuardSession(["collapse"])
    with pytest.raises(HTTPException) as err:
        _decide(db, status="accepted", reason="Accepted in bulk")
    assert err.value.status_code == 409 and "collapse" in err.value.detail
    assert not any("UPDATE lp_recommendation" in s for s in db.calls)  # nothing written

    item = _decide(_GuardSession(["collapse"]), status="accepted", reviewed=True)
    assert item.needs_review is True
    # Dismissing needs no confirmation; an unflagged row accepts as before.
    _decide(_GuardSession(["over_forecast_run"]), status="dismissed", reason="Not needed")
    _decide(_GuardSession(None), status="accepted")


def test_reviewed_accept_is_recorded_in_the_audit_log(monkeypatch):
    from backend import audit

    recorded = []
    monkeypatch.setattr(audit, "record", lambda db, action, detail, actor=None: recorded.append(detail))
    _decide(_GuardSession(["collapse", "over_forecast_run"]), status="accepted", reviewed=True, reason="Checked")
    assert recorded == ["SKU U-1: Checked [flagged for review: collapse, over_forecast_run; reviewed]"]


def test_an_aged_tier_is_display_only_and_never_ranked():
    """A tier carried forward from before the cycle's ABC run is shown with its
    period but has no share, so it has no priority score; the guard in _to_item
    trips if a query ever lets an aged tier's share through."""
    from backend.routers.recommendations import _to_item

    aged = _to_item(_item_row(
        tier="C", tier_period="2025-06", tier_is_current=False, revenue_share=None,
        current_stock=5.0, rop_i=50.0, q_i=45.0,
    ))
    assert (aged.tier, aged.tier_period, aged.tier_is_current) == ("C", "2025-06", False)
    assert aged.revenue_share is None and aged.priority_score is None

    current = _to_item(_item_row(tier="A", tier_period="2026-02", tier_is_current=True, current_stock=5.0, rop_i=50.0, q_i=45.0))
    assert current.tier_is_current is True and current.priority_score is not None

    with pytest.raises(AssertionError, match="aged tier"):
        _to_item(_item_row(tier="C", tier_period="2025-06", tier_is_current=False, revenue_share=0.01, current_stock=5.0, rop_i=50.0, q_i=45.0))


def test_reorder_sql_reads_shares_from_the_exact_run_and_the_tier_from_the_carried_one():
    from backend.routers.recommendations import _SELECT_ONE

    assert "abc_last.tier AS tier" in _SELECT_ONE and "abc_last.classification_period AS tier_period" in _SELECT_ONE
    assert "abc.revenue_share AS revenue_share" in _SELECT_ONE  # exact-period join, never abc_last
    assert "abc_last.revenue_share" not in _SELECT_ONE
    assert "ac.classification_period <= CASE ac.principal" in _SELECT_ONE  # carried: at or before, per principal
