"""
tests/backend/test_dashboard.py — GET /dashboard (backend/routers/dashboard.py).

Uses a FakeSession (same pattern as tests/backend/test_abc.py's) so these
never touch a real Supabase instance. Focuses on the honest-null paths for
the kpis/sales_vs_stock/abc_mix/tier_stock/portfolio_forecast/
reorder_preview fields, not just their happy paths — a null with no test
covering it is exactly how a silent fabrication regression would slip in
unnoticed.

UNILEVER ONLY (2026-09): dashboard.py no longer accepts a ?principal= param
and every query is hardcoded to principal='unilever' in the SQL text
itself, not a bound parameter — so FakeSession's matchers below don't
filter by principal at all (there's nothing in `params` to filter on
anymore). Confirming Del Monte data can't leak through is a live-database
check (see the plan's verification section), not something a fixture-based
unit test can meaningfully assert.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.routers.dashboard import AVG_WEEKS_PER_MONTH, _last_12_periods


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")


def user_token():
    return auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="staff", full_name="Staff")


# Fixed, arbitrary anchor for _last_12_periods() in tests — deterministic
# regardless of real wall-clock date at test-run time. FakeSession defaults
# to this so a bare FakeSession() is enough to compute the same period list
# the real request will use.
FIXED_ANCHOR = "2024-02"


def _periods():
    """The same 12-month list the real endpoint would compute, given
    FIXED_ANCHOR — call this instead of _last_12_periods() directly so
    tests never depend on the real wall-clock date. (Named with a leading
    underscore so `periods = _periods()` in test bodies below can't shadow
    it into an UnboundLocalError.)"""
    return _last_12_periods(FakeSession())


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
    """Matches only the query shapes backend/routers/dashboard.py actually
    issues. Fixture inputs are already in the shape each query's own SELECT
    projects (same simplification test_abc.py's FakeSession uses — no
    attempt to simulate real joins from raw fact-table rows)."""

    def __init__(
        self,
        *,
        recommendation_count=0,
        forecast_total=0,
        forecast_unreliable=0,
        latest_sales_period: str | None = FIXED_ANCHOR,
        received: dict | None = None,
        sales: dict | None = None,
        latest_inventory_period: str | None = None,
        soh: dict | None = None,
        latest_abc_period: str | None = None,
        abc_rows: list | None = None,
        tier_stock_rows: list | None = None,
        tier_pending_reorder_rows: list | None = None,
        latest_forecast_date=None,
        gated_forecast_rows: list | None = None,
        portfolio_actual: dict | None = None,
        reco_preview_rows: list | None = None,
        policy_rows: list | None = None,
    ):
        self.recommendation_count = recommendation_count
        self.forecast_total = forecast_total
        self.forecast_unreliable = forecast_unreliable
        self.latest_sales_period = latest_sales_period
        self.received = received or {}
        self.sales = sales or {}
        # Del Monte side of the restored per-principal split. These
        # fixtures are Unilever-only by construction, so Del Monte has no
        # sales anywhere — which is also what the live DB looks like for
        # most periods. Tests that care about Del Monte set these.
        self.delmonte_latest_sales_period = None
        self.delmonte_sales = {}
        self.latest_inventory_period = latest_inventory_period
        self.soh = soh or {}
        self.latest_abc_period = latest_abc_period
        self.abc_rows = abc_rows or []
        self.tier_stock_rows = tier_stock_rows or []
        self.tier_pending_reorder_rows = tier_pending_reorder_rows or []
        self.latest_forecast_date = latest_forecast_date
        self.gated_forecast_rows = gated_forecast_rows or []
        self.portfolio_actual = portfolio_actual or {}
        self.reco_preview_rows = reco_preview_rows or []
        # policy_comparison rows: [{planning_cycle_date, ss_i, forecast_value}]
        self.policy_rows = policy_rows or []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}

        # Checked FIRST: recommendations._SELECT_ONE (reused verbatim by
        # reorder_preview) now embeds its own SUM(quantity_on_hand *
        # unit_cost_per_case) subquery, which the SOH matcher below would
        # otherwise claim.
        if "FROM lp_recommendation lr" in sql and "WHERE lr.status = 'pending'" in sql:
            return FakeResult(self.reco_preview_rows)

        if "COUNT(*) AS product_count" in sql:
            return FakeResult([{"product_count": self.recommendation_count}])

        if "COUNT(*) FILTER (WHERE fr.mape >= :mape_gate)" in sql:
            return FakeResult([{"total_count": self.forecast_total, "unreliable_count": self.forecast_unreliable}])

        if sql.strip() == "SELECT MAX(calendar_month) AS p FROM Unilever_SKU_Demand_Fact_Real":
            return FakeResult([{"p": self.latest_sales_period}])

        if "MAX(_period) AS p FROM SellOut_Fact_Real" in sql:
            return FakeResult([{"p": self.delmonte_latest_sales_period}])

        if "FROM SellOut_Fact_Real" in sql and "SUM(net_amount)" in sql:
            periods = params["periods"]
            return FakeResult([
                {"period": p, "total": v}
                for p, v in self.delmonte_sales.items() if p in periods and v is not None
            ])

        if "FROM Purchase_Fact_Real" in sql:
            periods = params["periods"]
            return FakeResult([
                {"period": p, "total": v} for p, v in self.received.items() if p in periods and v is not None
            ])

        if "FROM Unilever_SKU_Demand_Fact_Real" in sql and "SUM(net_amount)" in sql:
            periods = params["periods"]
            return FakeResult([
                {"period": p, "total": v} for p, v in self.sales.items() if p in periods and v is not None
            ])

        if "MAX(_period) AS p FROM Inventory_Fact_Real" in sql:
            return FakeResult([{"p": self.latest_inventory_period}])

        if "SUM(quantity_on_hand * unit_cost_per_case)" in sql:
            periods = params["periods"]
            return FakeResult([
                {"period": p, "total": v} for p, v in self.soh.items() if p in periods and v is not None
            ])

        if "MAX(classification_period) AS p FROM ABC_Classification" in sql and "<=" not in sql:
            return FakeResult([{"p": self.latest_abc_period}])

        if "MAX(classification_period) AS p FROM ABC_Classification" in sql and "<=" in sql:
            # _nearest_abc_period_at_or_before: latest fixture period at or
            # before the requested one, mirroring the real MAX(...) <= :period.
            target = params["period"]
            candidates = sorted({r["period"] for r in self.abc_rows if r["period"] <= target})
            return FakeResult([{"p": candidates[-1] if candidates else None}])

        if "rop.ss_i AS ss_i" in sql:
            period = params["period"]
            rows = [r for r in self.abc_rows if r["period"] == period and r["tier"] == "A"]
            return FakeResult([
                {"product_key": r["product_key"], "revenue_share": r.get("revenue_share"),
                 "current_stock": r["current_stock"], "ss_i": r["ss_i"]}
                for r in rows
            ])

        if "fr.forecast_date = lr.planning_cycle_date" in sql:
            return FakeResult(self.policy_rows)

        if "SUM(revenue_share) AS rev_share_sum" in sql:
            period = params["period"]
            rows = [r for r in self.abc_rows if r["period"] == period]
            by_tier: dict = {}
            for r in rows:
                b = by_tier.setdefault(r["tier"], {"cnt": 0, "rev": 0.0})
                b["cnt"] += 1
                b["rev"] += r.get("revenue_share") or 0.0
            return FakeResult([{"tier": t, "cnt": b["cnt"], "rev_share_sum": b["rev"]} for t, b in by_tier.items()])

        if "BOOL_OR(stock_status = 'Active') AS any_active" in sql:
            period = params["period"]
            rows = [r for r in self.tier_stock_rows if r["period"] == period]
            return FakeResult([{"tier": r["tier"], "any_active": r["any_active"], "any_inactive": r["any_inactive"]} for r in rows])

        if sql.strip() == "SELECT MAX(forecast_date) AS d FROM Forecast_Result":
            return FakeResult([{"d": self.latest_forecast_date}])

        if "fr.mape < :mape_gate" in sql:
            return FakeResult(self.gated_forecast_rows)

        if "SUM(quantity_sold) AS qty" in sql:
            return FakeResult([{"period": p, "qty": v} for p, v in self.portfolio_actual.items()])

        if "COUNT(DISTINCT lr.product_key) AS cnt" in sql:
            period = params["period"]
            rows = [r for r in self.tier_pending_reorder_rows if r["period"] == period]
            by_tier: dict = {}
            for r in rows:
                by_tier.setdefault(r["tier"], set()).add(r["product_key"])
            return FakeResult([{"tier": t, "cnt": len(keys)} for t, keys in by_tier.items()])

        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


def make_client(session: FakeSession):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_requires_auth():
    session = FakeSession()
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        resp = c.get("/dashboard?principal=unilever")
    assert resp.status_code == 401


def test_original_fields_unchanged():
    session = FakeSession(recommendation_count=5, forecast_total=10, forecast_unreliable=3)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["principal"] == "unilever"
    assert body["inventory"] == {"value": None, "weeks_of_cover": None, "policy_weeks": 3}
    assert body["recommendations"] == {"order_value": None, "product_count": 5}
    assert body["forecast"] == {"unreliable_count": 3, "total_count": 10}
    assert len(body["cover_series"]) == 12
    assert all(pt["weeks_of_cover"] is None for pt in body["cover_series"])


# ---- kpis.sales ------------------------------------------------------

def test_kpis_sales_real_when_present_for_current_period():
    current = _periods()[-1]
    session = FakeSession(sales={current: 1000.0})
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    kpis = resp.json()["kpis"]
    assert kpis["sales"] == 1000.0
    assert kpis["sales_blocked_reason"] is None


def test_kpis_sales_null_when_no_current_period_data():
    session = FakeSession(sales={})
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    kpis = resp.json()["kpis"]
    assert kpis["sales"] is None
    assert "Unilever_SKU_Demand_Fact_Real" in kpis["sales_blocked_reason"]


# ---- kpis.soh_value ----------------------------------------------------

def test_kpis_soh_value_real_when_present():
    session = FakeSession(latest_inventory_period="2024-02", soh={"2024-02": 2000.0})
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    kpis = resp.json()["kpis"]
    assert kpis["soh_value"] == 2000.0
    assert kpis["soh_value_blocked_reason"] is None


def test_kpis_soh_value_null_when_inventory_fact_real_empty():
    session = FakeSession(latest_inventory_period=None)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    kpis = resp.json()["kpis"]
    assert kpis["soh_value"] is None
    assert kpis["soh_value_blocked_reason"] == "Inventory_Fact_Real has no rows for unilever at all."


# ---- kpis.safety_stock_rate --------------------------------------------

def test_kpis_safety_stock_rate_computed_from_comparable_products_only():
    abc_rows = [
        {"product_key": 1, "tier": "A", "period": "2024-02", "current_stock": 120, "ss_i": 100, "revenue_share": 0.5},
        {"product_key": 2, "tier": "A", "period": "2024-02", "current_stock": 40, "ss_i": 100, "revenue_share": 0.3},
        # No ss_i (no pending LP_Recommendation) — must be excluded from both numerator and denominator.
        {"product_key": 3, "tier": "A", "period": "2024-02", "current_stock": 10, "ss_i": None, "revenue_share": 0.2},
        # Tier B — must not count toward Category A's rate at all.
        {"product_key": 4, "tier": "B", "period": "2024-02", "current_stock": 5, "ss_i": 1, "revenue_share": 0.1},
    ]
    session = FakeSession(latest_abc_period="2024-02", abc_rows=abc_rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    kpis = resp.json()["kpis"]
    # 1 of 2 comparable Category A products (product 1) has current_stock >= ss_i.
    assert kpis["safety_stock_rate"] == pytest.approx(0.5)
    assert kpis["safety_stock_rate_blocked_reason"] is None


def test_kpis_safety_stock_rate_null_when_lp_recommendation_empty():
    abc_rows = [
        {"product_key": 1, "tier": "A", "period": "2024-02", "current_stock": 120, "ss_i": None, "revenue_share": 1.0},
    ]
    session = FakeSession(latest_abc_period="2024-02", abc_rows=abc_rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    kpis = resp.json()["kpis"]
    assert kpis["safety_stock_rate"] is None
    assert "LP_Recommendation" in kpis["safety_stock_rate_blocked_reason"]


def test_kpis_safety_stock_rate_null_when_no_abc_classification_at_all():
    session = FakeSession(latest_abc_period=None)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    kpis = resp.json()["kpis"]
    assert kpis["safety_stock_rate"] is None
    assert kpis["safety_stock_rate_blocked_reason"] == "ABC_Classification has no rows for unilever yet."


# ---- kpis.weeks_of_cover -------------------------------------------------

def test_kpis_weeks_of_cover_real_value():
    periods = _periods()
    p1, p2 = periods[0], periods[1]
    session = FakeSession(
        # avg monthly = weekly_target * AVG_WEEKS_PER_MONTH -> weekly demand = weekly_target exactly.
        sales={p1: AVG_WEEKS_PER_MONTH * 10, p2: AVG_WEEKS_PER_MONTH * 10},  # weekly demand = 10
        latest_inventory_period="2024-02",
        soh={"2024-02": 100.0},  # -> 100/10 = 10.0 weeks
    )
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    wc = resp.json()["kpis"]["weeks_of_cover"]
    assert wc["value"] == pytest.approx(10.0)
    assert wc["blocked_reason"] is None


def test_kpis_weeks_of_cover_null_when_weekly_demand_is_zero():
    periods = _periods()
    p1 = periods[0]
    session = FakeSession(
        sales={p1: 0.0},
        latest_inventory_period="2024-02",
        soh={"2024-02": 100.0},
    )
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    wc = resp.json()["kpis"]["weeks_of_cover"]
    assert wc["value"] is None
    assert "zero" in wc["blocked_reason"]


def test_kpis_weeks_of_cover_null_when_no_inventory_data_at_all():
    session = FakeSession(latest_inventory_period=None)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    wc = resp.json()["kpis"]["weeks_of_cover"]
    assert wc["value"] is None
    assert wc["blocked_reason"] == "Inventory_Fact_Real has no rows for unilever at all."


# ---- sales_vs_stock ------------------------------------------------------

def test_sales_vs_stock_has_12_points_with_nulls_for_missing_periods():
    current = _periods()[-1]
    session = FakeSession(sales={current: 100.0})
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    series = resp.json()["sales_vs_stock"]
    assert len(series) == 12
    assert series[-1] == {"period": current, "sales": 100.0, "stock_on_hand": None, "received": None}
    assert all(pt["sales"] is None for pt in series[:-1])


def test_sales_vs_stock_anchors_to_latest_real_sales_period_not_today():
    """Regression test for the empty-chart bug: the window must end at the
    most recent real sales period, not today's wall-clock date, or a
    real-but-stale window can leave too few/non-adjacent points for the
    line chart to render anything at all."""
    session = FakeSession(latest_sales_period="2023-06")
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    series = resp.json()["sales_vs_stock"]
    periods_in_series = [pt["period"] for pt in series]
    assert periods_in_series[-1] == "2023-06"
    assert periods_in_series[0] == "2022-07"


def test_sales_vs_stock_period_query_param_overrides_latest_sales_period_anchor():
    """The frontend date-range picker's applied end month/year is passed as
    ?period=YYYY-MM (Dashboard.jsx) — it must win over _latest_sales_period,
    the same way passing an explicit classification_period overrides
    GET /abc's own latest-period default."""
    session = FakeSession(latest_sales_period="2024-02")
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever&period=2023-06", headers={"Authorization": f"Bearer {user_token()}"})
    periods_in_series = [pt["period"] for pt in resp.json()["sales_vs_stock"]]
    assert periods_in_series[-1] == "2023-06"
    assert periods_in_series[0] == "2022-07"


def test_sales_vs_stock_period_query_param_rejects_malformed_value():
    session = FakeSession()
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever&period=not-a-period", headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.status_code == 422


def test_sales_vs_stock_start_period_widens_window_beyond_fixed_12_months():
    """Regression test for the range-picker bug: applying a > 12-month
    range (e.g. Apr 2023 - Mar 2026) must render the FULL range, not
    silently clip to the trailing 12 months ending at `period` — the chart
    was doing exactly that until start_period was wired in, which reads as
    "the start month I picked was ignored" from the UI."""
    session = FakeSession(latest_sales_period="2024-02")
    with make_client(session) as c:
        resp = c.get(
            "/dashboard?start_period=2023-04&period=2026-03",
            headers={"Authorization": f"Bearer {user_token()}"},
        )
    periods_in_series = [pt["period"] for pt in resp.json()["sales_vs_stock"]]
    assert periods_in_series[0] == "2023-04"
    assert periods_in_series[-1] == "2026-03"
    assert len(periods_in_series) == 36  # Apr 2023 through Mar 2026 inclusive


def test_sales_vs_stock_start_period_can_be_narrower_than_12_months():
    session = FakeSession(latest_sales_period="2024-02")
    with make_client(session) as c:
        resp = c.get(
            "/dashboard?start_period=2023-11&period=2024-01",
            headers={"Authorization": f"Bearer {user_token()}"},
        )
    periods_in_series = [pt["period"] for pt in resp.json()["sales_vs_stock"]]
    assert periods_in_series == ["2023-11", "2023-12", "2024-01"]


def test_sales_vs_stock_start_period_without_explicit_end_uses_resolved_anchor():
    """start_period with no `period` still needs an end — falls back to
    _latest_sales_period, same anchor _last_12_periods itself falls back
    to, rather than requiring the frontend to always send both."""
    session = FakeSession(latest_sales_period="2023-08")
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever&start_period=2023-05", headers={"Authorization": f"Bearer {user_token()}"})
    periods_in_series = [pt["period"] for pt in resp.json()["sales_vs_stock"]]
    assert periods_in_series == ["2023-05", "2023-06", "2023-07", "2023-08"]


def test_sales_vs_stock_start_period_after_end_period_is_swapped_not_empty():
    """DateFilter.jsx's start/end month+year are 4 independent <select>s
    with no ordering constraint — an inverted pick (start after end) is
    reachable from the UI and must still render a real window, not an
    empty/inverted one."""
    session = FakeSession(latest_sales_period="2024-02")
    with make_client(session) as c:
        resp = c.get(
            "/dashboard?start_period=2024-01&period=2023-11",
            headers={"Authorization": f"Bearer {user_token()}"},
        )
    periods_in_series = [pt["period"] for pt in resp.json()["sales_vs_stock"]]
    assert periods_in_series == ["2023-11", "2023-12", "2024-01"]


def test_sales_vs_stock_falls_back_to_today_only_when_no_sales_data_exists():
    session = FakeSession(latest_sales_period=None)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    series = resp.json()["sales_vs_stock"]
    today = datetime.date.today()
    assert series[-1]["period"] == f"{today.year:04d}-{today.month:02d}"


# ---- sales_vs_stock[].received (supplier-allocation proxy) -------------

def test_sales_vs_stock_received_real_when_present():
    current = _periods()[-1]
    session = FakeSession(received={current: 700.0})
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    series = resp.json()["sales_vs_stock"]
    assert series[-1]["received"] == 700.0


def test_sales_vs_stock_received_null_gap_when_purchase_fact_has_no_rows():
    """A period Purchase_Fact_Real has no rows for must render as a gap
    (null), never a fabricated 0."""
    session = FakeSession(received={})
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    series = resp.json()["sales_vs_stock"]
    assert series[-1]["received"] is None


# ---- abc_mix ---------------------------------------------------------

def test_abc_mix_counts_and_revenue_share_pct():
    abc_rows = [
        {"product_key": 1, "tier": "A", "period": "2024-02", "current_stock": None, "ss_i": None, "revenue_share": 0.6},
        {"product_key": 2, "tier": "A", "period": "2024-02", "current_stock": None, "ss_i": None, "revenue_share": 0.2},
        {"product_key": 3, "tier": "B", "period": "2024-02", "current_stock": None, "ss_i": None, "revenue_share": 0.15},
    ]
    session = FakeSession(latest_abc_period="2024-02", abc_rows=abc_rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    mix = {m["tier"]: m for m in resp.json()["abc_mix"]}
    assert mix["A"]["count"] == 2
    assert mix["A"]["revenue_share_pct"] == pytest.approx(80.0)
    assert mix["B"]["count"] == 1
    assert mix["B"]["revenue_share_pct"] == pytest.approx(15.0)


def test_abc_mix_empty_when_no_classification_rows_exist():
    session = FakeSession(latest_abc_period=None)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.json()["abc_mix"] == []


def test_abc_mix_period_query_param_overrides_latest_abc_period_anchor():
    """Same override convention as sales_vs_stock's period param — the
    picker's applied end month/year must win over _latest_abc_period, an
    EXACT match with no 'nearest available' fallback (mirrors GET /abc's
    own classification_period param). Without this, abc_mix (and
    tier_stock / kpis.safety_stock_rate, which share the same abc_period)
    always showed the latest classification run regardless of the shared
    date filter."""
    abc_rows = [
        {"product_key": 1, "tier": "A", "period": "2023-06", "current_stock": None, "ss_i": None, "revenue_share": 0.5},
        # A different classification run the endpoint must NOT read from
        # once an explicit period is requested.
        {"product_key": 2, "tier": "B", "period": "2024-02", "current_stock": None, "ss_i": None, "revenue_share": 0.9},
    ]
    session = FakeSession(latest_abc_period="2024-02", abc_rows=abc_rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever&period=2023-06", headers={"Authorization": f"Bearer {user_token()}"})
    mix = resp.json()["abc_mix"]
    assert [m["tier"] for m in mix] == ["A"]
    assert mix[0]["revenue_share_pct"] == pytest.approx(50.0)


# ---- tier_stock (Inventory_Fact_Real.stock_status, dead-stock signal) --

def test_tier_stock_dead_stock_from_stock_status_including_no_data_bucket():
    tier_stock_rows = [
        {"product_key": 1, "tier": "A", "period": "2024-02", "any_active": True, "any_inactive": False},
        {"product_key": 2, "tier": "A", "period": "2024-02", "any_active": False, "any_inactive": True},
        # Both flags true (e.g. multiple snapshot rows) — dead stock takes priority.
        {"product_key": 3, "tier": "A", "period": "2024-02", "any_active": True, "any_inactive": True},
        # No Inventory_Fact_Real row at all (LEFT JOIN miss) — must land in no_data.
        {"product_key": 4, "tier": "A", "period": "2024-02", "any_active": None, "any_inactive": None},
    ]
    tier_pending_reorder_rows = [
        {"product_key": 1, "tier": "A", "period": "2024-02"},
        {"product_key": 3, "tier": "A", "period": "2024-02"},
    ]
    session = FakeSession(
        latest_abc_period="2024-02", tier_stock_rows=tier_stock_rows,
        tier_pending_reorder_rows=tier_pending_reorder_rows,
    )
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    tier_a = next(t for t in resp.json()["tier_stock"] if t["tier"] == "A")
    assert tier_a == {"tier": "A", "in_stock": 1, "dead_stock": 2, "no_data": 1, "pending_reorder_count": 2}


def test_tier_stock_pending_reorder_count_is_zero_not_null_when_no_pending_rows():
    tier_stock_rows = [
        {"product_key": 1, "tier": "B", "period": "2024-02", "any_active": True, "any_inactive": False},
    ]
    session = FakeSession(latest_abc_period="2024-02", tier_stock_rows=tier_stock_rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    tier_b = next(t for t in resp.json()["tier_stock"] if t["tier"] == "B")
    assert tier_b["pending_reorder_count"] == 0


# ---- portfolio_forecast ------------------------------------------------

def test_portfolio_forecast_scope_label_and_series():
    latest_date = datetime.date(2024, 3, 1)
    gated_rows = [
        {"product_key": 1, "forecast_date": latest_date, "forecast_value": 100.0,
         "confidence_lower": 80.0, "confidence_upper": 120.0, "mape": 10.0},
        {"product_key": 2, "forecast_date": latest_date, "forecast_value": 50.0,
         "confidence_lower": 40.0, "confidence_upper": 60.0, "mape": 15.0},
    ]
    session = FakeSession(
        latest_forecast_date=latest_date,
        gated_forecast_rows=gated_rows,
        portfolio_actual={"2024-01": 90.0, "2024-02": 95.0},
    )
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    pf = resp.json()["portfolio_forecast"]
    assert pf["gated_sku_count"] == 2
    assert pf["avg_mape"] == pytest.approx(12.5)
    assert pf["scope_label"] == "Unilever only (SKU-level MA3 forecasts meeting the MAPE gate)."
    by_period = {pt["period"]: pt for pt in pf["series"]}
    assert by_period["2024-01"]["actual"] == pytest.approx(90.0)
    assert by_period["2024-02"]["actual"] == pytest.approx(95.0)
    assert by_period["2024-03"]["forecast"] == pytest.approx(150.0)
    assert by_period["2024-03"]["confidence_lower"] == pytest.approx(120.0)
    assert by_period["2024-03"]["actual"] is None


def test_portfolio_forecast_empty_when_nothing_passes_the_gate():
    session = FakeSession(latest_forecast_date=datetime.date(2024, 3, 1), gated_forecast_rows=[])
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    pf = resp.json()["portfolio_forecast"]
    assert pf == {
        "series": [],
        "gated_sku_count": 0,
        "avg_mape": None,
        "scope_label": "No products currently meet the MAPE < 20% gate.",
    }


def test_portfolio_forecast_empty_when_forecast_result_has_no_rows_at_all():
    session = FakeSession(latest_forecast_date=None)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    pf = resp.json()["portfolio_forecast"]
    assert pf["series"] == []
    assert pf["gated_sku_count"] == 0
    assert pf["avg_mape"] is None


# ---- reorder_preview -----------------------------------------------------

def _reco_row(key, urgency_stock, rop_i):
    """urgency_stock chosen relative to rop_i to land in a specific urgency
    bucket, matching backend.routers.recommendations._to_item's own rule."""
    return {
        "recommendation_key": key,
        "sku_id": f"SKU-{key}",
        "product_name": f"Product {key}",
        "principal": "unilever",
        "planning_cycle_date": "2024-02-01",
        "q_i": 10.0,
        "rop_i": rop_i,
        "ss_i": 5.0,
        "status": "pending",
        "current_stock": urgency_stock,
    }


def test_reorder_preview_top5_sorted_by_urgency_full_set_counts():
    rows = [
        _reco_row(1, urgency_stock=0, rop_i=100),    # CRITICAL (0 < 50)
        _reco_row(2, urgency_stock=90, rop_i=100),   # URGENT (50 <= 90 < 100)
        _reco_row(3, urgency_stock=150, rop_i=100),  # PLANNED (150 >= 100)
        _reco_row(4, urgency_stock=10, rop_i=100),   # CRITICAL
        _reco_row(5, urgency_stock=20, rop_i=100),   # CRITICAL
        _reco_row(6, urgency_stock=30, rop_i=100),   # CRITICAL
        _reco_row(7, urgency_stock=95, rop_i=100),   # URGENT
        _reco_row(8, urgency_stock=40, rop_i=100),   # CRITICAL
    ]
    session = FakeSession(reco_preview_rows=rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    preview = resp.json()["reorder_preview"]
    assert len(preview["rows"]) == 5
    assert all(r["urgency"] == "CRITICAL" for r in preview["rows"])
    assert preview["critical_count"] == 5
    assert preview["urgent_count"] == 2
    assert preview["total_order_qty"] == pytest.approx(80.0)  # 8 rows x q_i=10, full set not just top 5


def test_reorder_preview_empty_when_no_pending_recommendations():
    session = FakeSession(reco_preview_rows=[])
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    preview = resp.json()["reorder_preview"]
    assert preview == {
        "rows": [], "critical_count": 0, "urgent_count": 0, "no_data_count": 0, "total_order_qty": 0,
        "lp_weights": {"cost": 0.45, "service_level": 0.35, "storage": 0.2},
    }


def test_reorder_preview_lp_weights_always_present_and_matches_solver_constants():
    """lp_weights is a fixed mirror of analytics/optimization/lp.py's W1/W2/W3
    (0.45/0.35/0.20) — always present regardless of whether there are any
    pending recommendations to preview, since it's a solver-wide constant,
    not derived from rows."""
    session = FakeSession(reco_preview_rows=[])
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    weights = resp.json()["reorder_preview"]["lp_weights"]
    assert weights == {"cost": 0.45, "service_level": 0.35, "storage": 0.2}
    assert pytest.approx(sum(weights.values())) == 1.0


# ---- narrative-band fields (2026-09-18) ---------------------------------

def _abc_row(product_key, tier, period, revenue_share, current_stock=None, ss_i=None):
    return {"product_key": product_key, "tier": tier, "period": period, "revenue_share": revenue_share,
            "current_stock": current_stock, "ss_i": ss_i}


def test_abc_revenue_totals_the_abc_periods_sales():
    session = FakeSession(
        latest_abc_period="2024-02",
        abc_rows=[_abc_row(1, "A", "2024-02", 0.6)],
        sales={"2024-02": 27_914_343.91},
    )
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    body = resp.json()["abc_revenue"]
    assert body["period"] == "2024-02"
    assert body["total"] == pytest.approx(27_914_343.91)
    assert body["blocked_reason"] is None


def test_abc_revenue_blocked_when_no_sales_for_abc_period():
    session = FakeSession(latest_abc_period="2024-02", abc_rows=[_abc_row(1, "A", "2024-02", 0.6)], sales={})
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    body = resp.json()["abc_revenue"]
    assert body["total"] is None
    assert "2024-02" in body["blocked_reason"]


def test_safety_stock_exposure_counts_below_and_sums_their_revenue_share():
    rows = [
        _abc_row(1, "A", "2024-02", 0.30, current_stock=10, ss_i=50),   # below
        _abc_row(2, "A", "2024-02", 0.20, current_stock=80, ss_i=50),   # at/above
        _abc_row(3, "A", "2024-02", 0.10, current_stock=None, ss_i=50), # not measurable
        _abc_row(4, "B", "2024-02", 0.05, current_stock=0, ss_i=1),     # not tier A
    ]
    session = FakeSession(latest_abc_period="2024-02", abc_rows=rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    exp = resp.json()["safety_stock_exposure"]
    assert exp["tier_a_count"] == 3
    assert exp["comparable_count"] == 2
    assert exp["below_count"] == 1
    assert exp["below_revenue_share"] == pytest.approx(0.30)
    assert exp["blocked_reason"] is None


def test_safety_stock_exposure_blocked_when_nothing_measurable():
    session = FakeSession(latest_abc_period="2024-02", abc_rows=[_abc_row(1, "A", "2024-02", 0.6)])
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    exp = resp.json()["safety_stock_exposure"]
    assert exp["below_count"] is None
    assert exp["blocked_reason"]


def test_policy_comparison_sums_lp_ss_against_three_week_rule():
    session = FakeSession(policy_rows=[
        {"planning_cycle_date": datetime.date(2024, 3, 1), "ss_i": 40.0, "forecast_value": 100.0},
        {"planning_cycle_date": datetime.date(2024, 3, 1), "ss_i": 10.0, "forecast_value": 50.0},
    ])
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    pc = resp.json()["policy_comparison"]
    assert pc["cycle_date"] == "2024-03-01"
    assert pc["sku_count"] == 2
    assert pc["lp_safety_stock_units"] == pytest.approx(50.0)
    assert pc["rule_safety_stock_units"] == pytest.approx(3 * 150.0 / AVG_WEEKS_PER_MONTH, rel=1e-4)
    assert pc["rule_weeks"] == 3
    assert pc["blocked_reason"] is None


def test_policy_comparison_blocked_when_no_comparable_rows():
    session = FakeSession(policy_rows=[])
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    pc = resp.json()["policy_comparison"]
    assert pc["lp_safety_stock_units"] is None
    assert pc["rule_safety_stock_units"] is None
    assert pc["blocked_reason"]


def test_reorder_preview_no_stock_row_is_no_data_not_critical():
    """A product with no Inventory_Fact_Real row used to COALESCE to 0 and
    read as CRITICAL — a fabricated alert. It must now be 'NO DATA'."""
    rows = [_reco_row(1, urgency_stock=None, rop_i=100), _reco_row(2, urgency_stock=0, rop_i=100)]
    session = FakeSession(reco_preview_rows=rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    preview = resp.json()["reorder_preview"]
    by_key = {r["recommendation_key"]: r for r in preview["rows"]}
    assert by_key[1]["urgency"] == "NO DATA"
    assert by_key[1]["current_stock"] is None
    assert by_key[2]["urgency"] == "CRITICAL"
    assert preview["critical_count"] == 1
    assert preview["no_data_count"] == 1
