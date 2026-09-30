"""
tests/backend/test_dashboard.py — GET /dashboard (backend/routers/dashboard.py).

Uses a FakeSession (same pattern as tests/backend/test_abc.py's) so these
never touch a real Supabase instance. Focuses on the honest-null paths for
the kpis/sales_vs_stock/abc_mix/tier_stock/portfolio_forecast/
reorder_preview fields, not just their happy paths — a null with no test
covering it is exactly how a silent fabrication regression would slip in
unnoticed.

BOTH PRINCIPALS (2026-09-17): dashboard.py accepts ?principal= again — the
earlier "UNILEVER ONLY" note this replaced was stale. Scope reaches the SQL
by f-string interpolation (allowlist-validated at dashboard.py:573), NOT as
a bound param, so unlike tests/backend/test_sku.py the matchers below cannot
key off `params["principal"]`; a scoping assertion here has to read the SQL
text. That asymmetry is deliberate — do not "fix" it to match the other
files, it would silently weaken the assertion.
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

    def scalar(self):
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
        forecast_evaluated=0,
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
        scoped_forecast_count: int = 1,
        portfolio_actual: dict | None = None,
        reco_preview_rows: list | None = None,
        policy_rows: list | None = None,
        # LP cycle scoping (2026-09-23, backend/lp_cycle.py). Default None =
        # "nothing pending", which is what the existing fixtures below model;
        # the matchers ignore the cycle filter, so those fixtures keep
        # returning their rows exactly as before.
        lp_cycle_date=None,
        lp_superseded_pending: int = 0,
        lp_generated_at=None,
        forecast_generated_at=None,
        # Pending rows in the LP cycle, and how many predate the forecasts.
        # None = every row is as old as lp_generated_at (one run wrote them).
        lp_row_count: int = 1,
        lp_stale_rows: int | None = None,
        # Principals that actually carry a stock valuation / an ABC run at
        # the resolved period. Empty = "don't narrow", which leaves
        # weeks_of_cover on the requested scope as it was before.
        stock_coverage: list | None = None,
        abc_coverage: list | None = None,
    ):
        self.recommendation_count = recommendation_count
        self.forecast_total = forecast_total
        self.forecast_unreliable = forecast_unreliable
        self.forecast_evaluated = forecast_evaluated
        self.latest_sales_period = latest_sales_period
        self.received = received or {}
        self.sales = sales or {}
        # Del Monte side of the restored per-principal split. These
        # fixtures are Unilever-only by construction, so Del Monte has no
        # sales anywhere — which is also what the live DB looks like for
        # most periods. Tests that care about Del Monte set these.
        self.delmonte_latest_sales_period = None
        self.delmonte_sales = {}
        self.lp_run = None  # the lp_run row stored_run finds; None = table not applied
        # Del Monte months whose sell-out net_amount is tax-inclusive
        # (Kelvin's X2 rule, SellOut_Fact.net_amount_tax_inclusive). Live:
        # 2023-08 only. Empty = every Del Monte peso is ex-VAT.
        self.dm_tax_inclusive_periods: list = []
        self.latest_inventory_period = latest_inventory_period
        self.soh = soh or {}
        self.latest_abc_period = latest_abc_period
        self.abc_rows = abc_rows or []
        self.tier_stock_rows = tier_stock_rows or []
        self.tier_pending_reorder_rows = tier_pending_reorder_rows or []
        self.latest_forecast_date = latest_forecast_date
        self.gated_forecast_rows = gated_forecast_rows or []
        # Forecast_Result rows in scope at the latest forecast_date, gated or
        # not — distinguishes "none pass the gate" from "none exist at all".
        self.scoped_forecast_count = scoped_forecast_count
        self.portfolio_actual = portfolio_actual or {}
        self.reco_preview_rows = reco_preview_rows or []
        # policy_comparison rows: [{planning_cycle_date, ss_i, forecast_value}]
        self.policy_rows = policy_rows or []
        self.lp_cycle_date = lp_cycle_date
        self.lp_superseded_pending = lp_superseded_pending
        self.lp_generated_at = lp_generated_at
        self.forecast_generated_at = forecast_generated_at
        self.lp_row_count = lp_row_count
        self.lp_stale_rows = lp_stale_rows
        self.stock_coverage = stock_coverage or []
        self.abc_coverage = abc_coverage or []
        # Every (sql, params) issued, so a test can assert on the query text
        # itself — the only way to check scope/unit handling that lives in
        # SQL rather than in Python (see this module's docstring).
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, dict(params)))

        # backend/lp_cycle.stored_run (migration 0035). Before every
        # lp_recommendation matcher: its subquery reads that table too.
        if "to_regclass('lp_run')" in sql:
            return FakeResult([{"present": self.lp_run is not None}])
        if "FROM lp_run r" in sql:
            return FakeResult([self.lp_run] if self.lp_run else [])
        # LP cycle + freshness (backend/lp_cycle.py) — checked BEFORE the
        # _SELECT_ONE matcher below, which would otherwise claim these:
        # they read the same table with the same status predicate.
        if "MAX(lr.planning_cycle_date) AS d" in sql:
            return FakeResult([{"d": self.lp_cycle_date}])

        if "MAX(lr.generated_at) AS t" in sql:
            stale = self.lp_stale_rows
            if stale is None:
                fc_at = params.get("fc_at")
                one_old_run = self.lp_generated_at is not None and fc_at is not None and self.lp_generated_at < fc_at
                stale = self.lp_row_count if one_old_run else 0
            return FakeResult([{"t": self.lp_generated_at, "row_count": self.lp_row_count, "stale_count": stale}])

        if "MAX(generated_at) AS t FROM forecast_result" in sql:
            return FakeResult([self.forecast_generated_at])

        if "lr.planning_cycle_date < :cycle" in sql:
            return FakeResult([self.lp_superseded_pending])

        # Checked FIRST among the row queries: recommendations._SELECT_ONE
        # (reused verbatim by reorder_preview) embeds its own stock
        # subquery, which the SOH matcher below would otherwise claim.
        if "FROM lp_recommendation lr" in sql and "WHERE lr.status = 'pending'" in sql:
            return FakeResult(self.reco_preview_rows)

        # Which principals carry a stock valuation at the resolved period —
        # what keeps weeks_of_cover's numerator and denominator on the same
        # principals (_stock_valuation_coverage).
        if "HAVING SUM(COALESCE(valuation" in sql:
            return FakeResult([{"principal": p} for p in self.stock_coverage])

        if "SELECT principal FROM ABC_Classification" in sql:
            return FakeResult([{"principal": p} for p in self.abc_coverage])

        if "COUNT(*) AS product_count" in sql:
            return FakeResult([{"product_count": self.recommendation_count}])

        if "COUNT(*) FILTER (WHERE fr.mase >= :mase_gate)" in sql:
            assert params.get("mase_gate") == 1.0, "unreliable_count must gate on MASE >= 1"
            return FakeResult([{"total_count": self.forecast_total, "evaluated_count": self.forecast_evaluated,
                                "unreliable_count": self.forecast_unreliable}])

        if sql.strip() == "SELECT MAX(calendar_month) AS p FROM Unilever_SKU_Demand_Fact_Real":
            return FakeResult([{"p": self.latest_sales_period}])

        if "MAX(_period) AS p FROM SellOut_Fact_Real" in sql:
            return FakeResult([{"p": self.delmonte_latest_sales_period}])

        if "net_amount_tax_inclusive" in sql:
            return FakeResult([{"p": p} for p in self.dm_tax_inclusive_periods])

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

        # Inventory_Fact.valuation (the source file's own extended total) is
        # preferred over the multiplication since 2026-09-23 — it prices the
        # loose-piece remainder the old product dropped.
        if "SUM(COALESCE(valuation, quantity_on_hand * unit_cost_per_case))" in sql:
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

        if "fr.mase < :mase_gate" in sql:
            assert params.get("mase_gate") == 1.0, "the portfolio gate must be the LP's own MASE < 1"
            return FakeResult(self.gated_forecast_rows)

        if "SELECT COUNT(*) FROM Forecast_Result fr" in sql:
            return FakeResult([self.scoped_forecast_count])

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
    session = FakeSession(recommendation_count=5, forecast_total=10, forecast_evaluated=8, forecast_unreliable=3)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["principal"] == "unilever"
    assert body["inventory"] == {"value": None, "weeks_of_cover": None, "policy_weeks": 3}
    assert body["recommendations"] == {"order_value": None, "product_count": 5}
    assert body["forecast"] == {"unreliable_count": 3, "evaluated_count": 8, "total_count": 10, "mase_gate": 1.0}
    # latest real sales month, overall and per principal (no Del Monte sales in this fixture)
    assert body["latest_data_period"] == FIXED_ANCHOR
    assert body["latest_data_period_by_principal"] == {"unilever": FIXED_ANCHOR, "delmonte": None}
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
    # Shown on the card as is, so it says what is missing in a planner's
    # terms rather than naming the table (2026-09-29).
    assert "safety stock in the LP's current cycle" in kpis["safety_stock_rate_blocked_reason"]


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


def test_weeks_of_cover_does_not_follow_the_date_range():
    """SSM's 3-week policy is judged by this figure, so it is always the
    latest stock over the 12 months of sales up to it, whatever range the
    picker shows. It used to average the picker's months, so the same
    stock read 3.0-3.5 weeks live (2026-09-29)."""
    periods = _periods()  # 2023-03 .. 2024-02
    sales = {p: 100.0 for p in periods}
    sales[periods[-1]] = 400.0  # one unusual month
    expected = round(1000.0 / ((sum(sales.values()) / 12) / AVG_WEEKS_PER_MONTH), 2)
    for query in ("", "&start_period=2024-01&period=2024-02", "&start_period=2023-01&period=2023-07"):
        session = FakeSession(latest_inventory_period="2024-02", soh={"2024-02": 1000.0}, sales=dict(sales))
        with make_client(session) as c:
            wc = c.get(
                f"/dashboard?principal=unilever{query}", headers={"Authorization": f"Bearer {user_token()}"}
            ).json()["kpis"]["weeks_of_cover"]
        assert wc["value"] == pytest.approx(expected), query
        assert wc["sales_window"] == {"start": periods[0], "end": periods[-1]}, query
        assert wc["months_used"] == 12, query


def test_weeks_of_cover_sales_year_ends_at_the_stock_count():
    """Stock and sales must describe the same moment: a snapshot older than
    the latest sales month is measured against the 12 months up to itself."""
    session = FakeSession(
        latest_inventory_period="2023-12", soh={"2023-12": 1000.0}, sales={p: 100.0 for p in _periods()}
    )
    with make_client(session) as c:
        wc = c.get(
            "/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}
        ).json()["kpis"]["weeks_of_cover"]
    assert wc["sales_window"] == {"start": "2023-01", "end": "2023-12"}
    assert wc["months_used"] == 10  # 2023-01 and 2023-02 have no rows: gaps, never zeros
    assert wc["value"] == pytest.approx(round(1000.0 / (100.0 / AVG_WEEKS_PER_MONTH), 2))


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
         "confidence_lower": 80.0, "confidence_upper": 120.0, "mase": 0.5},
        {"product_key": 2, "forecast_date": latest_date, "forecast_value": 50.0,
         "confidence_lower": 40.0, "confidence_upper": 60.0, "mase": 0.75},
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
    assert pf["scope_label"] == (
        "Unilever (SKU-level forecasts that beat a naive baseline — MASE < 1, the LP's own gate)."
    )
    by_period = {pt["period"]: pt for pt in pf["series"]}
    assert by_period["2024-01"]["actual"] == pytest.approx(90.0)
    assert by_period["2024-02"]["actual"] == pytest.approx(95.0)
    assert by_period["2024-03"]["forecast"] == pytest.approx(150.0)
    assert by_period["2024-03"]["confidence_lower"] == pytest.approx(120.0)
    assert by_period["2024-03"]["actual"] is None


def test_portfolio_forecast_all_scope_says_which_principal_it_covers():
    """Under 'all' with only Unilever rows gated, the label must say so —
    otherwise All and Unilever read identically and the card's filter
    looks broken."""
    latest_date = datetime.date(2024, 3, 1)
    gated_rows = [
        {"product_key": 1, "forecast_date": latest_date, "forecast_value": 100.0,
         "confidence_lower": 80.0, "confidence_upper": 120.0, "mase": 0.5, "principal": "unilever"},
    ]
    session = FakeSession(latest_forecast_date=latest_date, gated_forecast_rows=gated_rows,
                          portfolio_actual={"2024-02": 95.0})
    with make_client(session) as c:
        resp = c.get("/dashboard", headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.json()["portfolio_forecast"]["scope_label"] == (
        "All principals — only Unilever has SKU-level forecasts that beat a naive "
        "baseline (MASE < 1, the LP's own gate), so this matches the Unilever view."
    )


def test_portfolio_forecast_empty_when_nothing_passes_the_gate():
    session = FakeSession(latest_forecast_date=datetime.date(2024, 3, 1), gated_forecast_rows=[])
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    pf = resp.json()["portfolio_forecast"]
    assert pf == {
        "series": [],
        "gated_sku_count": 0,
        "scope_label": "No forecasts for this scope currently beat the naive baseline (MASE < 1).",
        "mase_gate": 1.0,
        "insight": None,
    }


def test_portfolio_forecast_delmonte_says_no_forecasts_exist_not_failed_gate():
    # Del Monte has no Forecast_Result rows at all (invoice-grain source, no
    # SKU column) — the label must not read as "forecasts ran and failed".
    session = FakeSession(latest_forecast_date=datetime.date(2024, 3, 1), gated_forecast_rows=[],
                          scoped_forecast_count=0)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=delmonte", headers={"Authorization": f"Bearer {user_token()}"})
    pf = resp.json()["portfolio_forecast"]
    assert pf["series"] == []
    assert pf["gated_sku_count"] == 0
    assert pf["scope_label"].startswith("No SKU-level forecasts exist for Del Monte")


def test_portfolio_forecast_empty_when_forecast_result_has_no_rows_at_all():
    session = FakeSession(latest_forecast_date=None)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    pf = resp.json()["portfolio_forecast"]
    assert pf["series"] == []
    assert pf["gated_sku_count"] == 0
    # No rows at all is "no forecasts exist", never "none pass the gate".
    assert pf["scope_label"] == "No SKU-level forecasts exist for unilever."


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
        "lp_weights_source": "defaults",
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
    rule = 3 * 150.0 / AVG_WEEKS_PER_MONTH
    assert pc["lp_vs_rule_pct"] == pytest.approx(round((rule - 50.0) / rule * 100, 1))
    assert pc["rule_weeks"] == 3
    assert pc["blocked_reason"] is None


def test_principal_echoes_the_requested_scope():
    """Was hard-coded to 'unilever' for every scope."""
    with make_client(FakeSession()) as c:
        body = c.get("/dashboard", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["principal"] == "all"


def test_policy_comparison_blocked_when_no_comparable_rows():
    session = FakeSession(policy_rows=[])
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    pc = resp.json()["policy_comparison"]
    assert pc["lp_safety_stock_units"] is None
    assert pc["rule_safety_stock_units"] is None
    assert pc["lp_vs_rule_pct"] is None
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


# ─── Units, LP cycle scoping and self-labelling (2026-09-23) ──────────────
# These three fixes changed what the page REPORTS, not just how it reads, so
# each is pinned here. The unit and scope logic lives in SQL (see this
# module's docstring on why such assertions read the query text).


def _sql_for(session, needle):
    """The one issued query containing `needle`, with its params."""
    return next((s, p) for s, p in session.calls if needle in s)


def test_safety_stock_compares_pieces_with_pieces_not_cases():
    """quantity_on_hand is CASES and ss_i is PIECES. Comparing them directly
    reported 109 of 120 measurable Category A SKUs below safety stock when
    36 are — the conversion must be in the query."""
    session = FakeSession(latest_abc_period="2024-02", latest_inventory_period="2024-02")
    with make_client(session) as c:
        c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    sql, _ = _sql_for(session, "rop.ss_i AS ss_i")
    assert "stock_pieces" in sql, "safety stock must compare the converted figure"
    assert "pack_size" in sql, "cases are converted to pieces via pack_size"
    # And never the raw case count: that is the bug this guards.
    assert "SUM(inv.quantity_on_hand) AS current_stock" not in sql


def test_every_lp_read_is_pinned_to_the_current_cycle():
    """Leftover `pending` rows from earlier runs (179 live, back to 2023-05)
    must not reach the page: they made the pending count read 429 not 250."""
    session = FakeSession(lp_cycle_date=datetime.date(2026, 3, 1), latest_abc_period="2024-02")
    with make_client(session) as c:
        c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    for needle in ("COUNT(*) AS product_count",            # the KPI card
                   "rop.ss_i AS ss_i",                      # safety stock
                   "fr.forecast_date = lr.planning_cycle_date",  # policy comparison
                   "COUNT(DISTINCT lr.product_key) AS cnt"):     # tier_stock
        sql, params = _sql_for(session, needle)
        assert ":current_cycle" in sql, f"{needle} is not pinned to the LP cycle"
        assert params.get("current_cycle") == datetime.date(2026, 3, 1)


def test_lp_block_reports_the_cycle_and_its_staleness():
    session = FakeSession(
        lp_cycle_date=datetime.date(2026, 3, 1),
        lp_superseded_pending=179,
        lp_generated_at=datetime.datetime(2026, 8, 24, 7, 12),
        forecast_generated_at=datetime.datetime(2026, 9, 21, 10, 8),
    )
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    lp = body["lp"]
    assert lp["cycle_date"] == "2026-03-01"
    assert lp["superseded_pending_count"] == 179
    assert lp["is_stale"] is True, "an LP older than the forecasts it used must be flagged"
    assert "rerun" in lp["reason"].lower()


def test_lp_not_stale_when_run_after_the_forecasts():
    session = FakeSession(
        lp_cycle_date=datetime.date(2026, 3, 1),
        lp_generated_at=datetime.datetime(2026, 9, 22, 9, 0),
        forecast_generated_at=datetime.datetime(2026, 9, 21, 10, 8),
    )
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["lp"]["is_stale"] is False
    assert body["lp"]["reason"] is None


def test_lp_rerun_that_left_rows_behind_is_still_flagged():
    """A rerun refreshes only the products in that run and leaves the
    cycle's other pending rows as they were. Judged by its newest row, the
    cycle read fresh while 177 of its 250 rows still carried the old
    forecasts — and "rerun to clear this" would not have cleared them."""
    session = FakeSession(
        lp_cycle_date=datetime.date(2026, 3, 1),
        lp_generated_at=datetime.datetime(2026, 9, 23, 9, 0),
        forecast_generated_at=datetime.datetime(2026, 9, 21, 10, 8),
        lp_row_count=250,
        lp_stale_rows=177,
    )
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    lp = body["lp"]
    assert lp["is_stale"] is True
    assert (lp["row_count"], lp["stale_row_count"]) == (250, 177)
    assert "177 of the 250 rows" in lp["reason"]
    assert "rerun will not change them" in lp["reason"].lower()

    # Counted against the forecast run, within the page's own principal.
    sql, params = _sql_for(session, "MAX(lr.generated_at) AS t")
    assert params["fc_at"] == datetime.datetime(2026, 9, 21, 10, 8)
    assert params["principal"] == "unilever" and ":principal" in sql


def test_sales_card_reports_the_month_it_is_actually_showing():
    """The caption said "This period's total sales" while the value could be
    any earlier month the walk-back landed on."""
    periods = _periods()
    session = FakeSession(sales={periods[-3]: 1000.0})  # newest two months missing
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["kpis"]["sales"] == 1000.0
    assert body["kpis"]["sales_period"] == periods[-3]


def test_weeks_of_cover_denominator_follows_the_stock_coverage():
    """Under 'all' the stock valuation is Unilever's alone, so the demand
    side must be Unilever's too — not both principals, which produced a
    ratio belonging to neither scope."""
    periods = _periods()
    session = FakeSession(
        latest_inventory_period=periods[-1],
        soh={periods[-1]: 1_000_000.0},
        sales={p: 100_000.0 for p in periods},
        stock_coverage=["unilever"],
    )
    session.delmonte_sales = {periods[-1]: 500_000.0}
    session.delmonte_latest_sales_period = periods[-1]
    with make_client(session) as c:
        body = c.get("/dashboard", headers={"Authorization": f"Bearer {user_token()}"}).json()
    wc = body["kpis"]["weeks_of_cover"]
    assert wc["coverage"] == ["unilever"], "the card must say which principals it covers"
    expected = 1_000_000.0 / (100_000.0 / AVG_WEEKS_PER_MONTH)
    assert wc["value"] == pytest.approx(round(expected, 2)), "Del Monte demand must not enter a Unilever-only ratio"


def test_stock_value_prefers_the_sources_own_valuation():
    """Inventory_Fact.valuation already prices the loose-piece remainder;
    recomputing cases x cost dropped it (a 3.2% under-count live)."""
    session = FakeSession(latest_inventory_period="2024-02", soh={"2024-02": 22_700_825.83})
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    # Needle is the projection itself: "AS total" alone also matches the
    # forecast card's "AS total_count".
    _sql_for(session, "SUM(COALESCE(valuation, quantity_on_hand * unit_cost_per_case))")
    assert body["kpis"]["soh_value"] == 22_700_825.83
    # The legacy field documented as "impossible" now carries the same figure.
    assert body["inventory"]["value"] == 22_700_825.83


# ---- chart story fields (backend/chart_insights.py, 2026-09-26) ---------

def test_kpi_sales_trend_points_and_month_over_month_delta():
    """Sparkline points are the REAL months only, and the delta compares
    the card's month with the nearest earlier month that has data."""
    periods = _periods()
    session = FakeSession(sales={periods[-4]: 120_000.0, periods[-2]: 200_000.0, periods[-1]: 150_000.0})
    with make_client(session) as c:
        kpis = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()["kpis"]
    trend = kpis["sales_trend"]
    assert [pt["period"] for pt in trend["points"]] == [periods[-4], periods[-2], periods[-1]]
    assert trend["latest_period"] == periods[-1]
    assert trend["prev_period"] == periods[-2]
    assert trend["delta_pct"] == pytest.approx(-25.0)


def test_kpi_soh_trend_follows_the_inventory_snapshots():
    periods = _periods()
    session = FakeSession(
        latest_inventory_period=periods[-1],
        soh={periods[-2]: 40_000_000.0, periods[-1]: 46_000_000.0},
    )
    with make_client(session) as c:
        kpis = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()["kpis"]
    trend = kpis["soh_trend"]
    assert trend["latest_period"] == periods[-1]
    assert trend["delta_pct"] == pytest.approx(15.0)


def test_sales_vs_stock_insight_sentence_and_highlights():
    """The hero chart's sentence states the real month-over-month move and
    the highlights mark the window's true peak and low sales months."""
    periods = _periods()
    session = FakeSession(
        sales={periods[-3]: 37_300_000.0, periods[-2]: 41_000_000.0, periods[-1]: 27_900_000.0},
        latest_inventory_period=periods[-1],
        soh={periods[-1]: 46_600_000.0},
    )
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    insight = body["sales_vs_stock_insight"]
    assert "fell 32" in insight["text"]          # (27.9 - 41.0) / 41.0 = -31.95…%
    assert "₱27.9M" in insight["text"]
    assert "₱46.6M" in insight["text"]
    assert insight["peak"]["period"] == periods[-2]
    assert insight["low"]["period"] == periods[-1]
    assert insight["peak"]["value"] == pytest.approx(41_000_000.0)


def test_insight_and_trends_are_null_when_nothing_real_exists():
    session = FakeSession()
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["sales_vs_stock_insight"] is None
    assert body["kpis"]["sales_trend"] is None
    assert body["kpis"]["soh_trend"] is None
    assert body["tier_stock_period"] is None


def test_portfolio_forecast_insight_compares_forecast_with_last_actual():
    latest_date = datetime.date(2024, 3, 1)
    gated_rows = [
        {"product_key": 1, "forecast_date": latest_date, "forecast_value": 100.0,
         "confidence_lower": 80.0, "confidence_upper": 120.0, "mase": 0.5},
        {"product_key": 2, "forecast_date": latest_date, "forecast_value": 50.0,
         "confidence_lower": 40.0, "confidence_upper": 60.0, "mase": 0.75},
    ]
    session = FakeSession(
        latest_forecast_date=latest_date,
        gated_forecast_rows=gated_rows,
        portfolio_actual={"2024-01": 90.0, "2024-02": 120.0},
    )
    with make_client(session) as c:
        pf = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()["portfolio_forecast"]
    assert pf["mase_gate"] == 1.0
    # 150 forecast vs 120 actual = +25%
    assert pf["insight"]["text"] == "The Mar 2024 forecast is 150 pieces — 25.0% above the 120 sold in Feb 2024."
    assert pf["insight"]["forecast_period"] == "2024-03"


def test_forecast_block_reports_its_mase_gate():
    session = FakeSession(forecast_total=10, forecast_evaluated=8, forecast_unreliable=3)
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["forecast"]["mase_gate"] == 1.0


def test_tier_stock_period_names_the_snapshot_month():
    tier_stock_rows = [
        {"product_key": 1, "tier": "A", "period": "2024-02", "any_active": True, "any_inactive": False},
    ]
    session = FakeSession(
        latest_abc_period="2024-02", tier_stock_rows=tier_stock_rows,
        latest_inventory_period="2024-03",
    )
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["tier_stock_period"] == "2024-03"


# ---- stock on hand under 'all', and the reorder card's order (2026-09-29) ---

class _PeriodSumSession:
    """Answers _query_period_sums per principal and refuses an unscoped sum:
    under 'all' that is exactly what mixed the two principals' coverage."""

    def __init__(self, by_principal):
        self.by_principal = by_principal

    def execute(self, stmt, params=None):
        sql = str(stmt)
        who = next((p for p in self.by_principal if f"principal = '{p}'" in sql), None)
        assert who, "the 'all' figure must be built from per-principal sums"
        return FakeResult([{"period": p, "total": v} for p, v in self.by_principal[who].items()])


def test_soh_under_all_counts_only_months_both_principals_have():
    """Summing whatever rows existed put PHP 43.0M (both principals) in
    2025-12 next to PHP 24.3M (Unilever alone) in 2026-01, a drop that never
    happened."""
    from backend.routers.dashboard import _soh_value_by_period

    session = _PeriodSumSession({
        "unilever": {"2025-12": 36_277_133.89, "2026-01": 24_339_386.24},
        "delmonte": {"2025-12": 6_683_837.26},
    })
    out = _soh_value_by_period(session, ["2025-12", "2026-01"], "all")
    assert out["2025-12"] == pytest.approx(42_960_971.15)
    assert out["2026-01"] is None


def test_reorder_preview_ranks_by_priority_within_an_urgency():
    """Urgency alone left the five to the query's order; within an urgency
    the card now ranks like the Reorder page — revenue share x units below
    the reorder point, highest first."""
    shares = {1: 0.01, 4: 0.05, 5: 0.02, 6: 0.04, 8: 0.03, 9: 0.001}
    stock = {1: 0, 4: 10, 5: 20, 6: 30, 8: 40, 9: 5}
    rows = [{**_reco_row(k, urgency_stock=stock[k], rop_i=100), "revenue_share": shares[k]} for k in shares]
    session = FakeSession(reco_preview_rows=rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    preview = resp.json()["reorder_preview"]
    # priority = share x (100 - stock): 4 -> 4.5, 6 -> 2.8, 8 -> 1.8, 5 -> 1.6, 1 -> 1.0, 9 -> 0.095
    assert [r["recommendation_key"] for r in preview["rows"]] == [4, 6, 8, 5, 1]



# ---- chart story fields across gaps (2026-09-29) ----------------------------

def test_kpi_trend_says_how_far_back_its_comparison_month_is():
    """Del Monte's sell-out has no Oct-Nov 2025, so Dec 2025 compares with
    Sep 2025; the card now says it is three months back."""
    from backend.chart_insights import kpi_trend

    t = kpi_trend({"2025-08": 7.9, "2025-09": 7.8, "2025-12": 22.1}, "2025-12")
    assert t["prev_period"] == "2025-09"
    assert t["months_apart"] == 3


def test_portfolio_insight_compares_only_with_the_month_before_the_forecast():
    """A range ending Jun 2024 read "Mar 2026 forecast ... 247.4% above the
    25,973 sold in Jun 2024"; the forecast now stands alone then."""
    from backend.chart_insights import portfolio_forecast_insight

    series = [
        {"period": "2024-06", "actual": 25973.0, "forecast": None},
        {"period": "2026-03", "actual": None, "forecast": 90240.0},
    ]
    assert portfolio_forecast_insight(series)["text"] == "The Mar 2026 forecast is 90,240 pieces."
    series[0]["period"] = "2026-02"
    assert "sold in Feb 2026" in portfolio_forecast_insight(series)["text"]


# ---- allocation (SSM's rule: prior-year sales x 103/105/108%) ------------


def test_allocation_applies_ssm_rule_to_prior_year_sales():
    sales = {f"2025-{m:02d}": 100.0 for m in range(1, 13)}
    sales.update({"2026-01": 110.0, "2026-02": 120.0})
    session = FakeSession(latest_sales_period="2026-02", sales=sales)
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    a = body["allocation"]
    assert a["basis_year"] == 2025
    assert a["basis_sales"] == pytest.approx(1200.0)
    assert a["basis_months"] == 12
    assert a["latest_month"] == "2026-02"
    assert a["ytd_sales"] == pytest.approx(230.0)
    assert a["ytd_months"] == 2
    assert [(level["pct"], level["annual"], level["monthly"]) for level in a["levels"]] == [
        (103, pytest.approx(1236.0), pytest.approx(103.0)),
        (105, pytest.approx(1260.0), pytest.approx(105.0)),
        (108, pytest.approx(1296.0), pytest.approx(108.0)),
    ]
    assert a["vat_basis"] == "incl. VAT"
    assert a["blocked_reason"] is None
    # Single-principal pesos sit on one tax basis, so there is nothing to flag.
    assert body["vat_note"] is None


def test_allocation_says_when_the_basis_year_is_partial():
    sales = {f"2025-{m:02d}": 100.0 for m in (7, 8, 9, 10, 11, 12)}
    sales["2026-01"] = 90.0
    session = FakeSession(latest_sales_period="2026-01", sales=sales)
    with make_client(session) as c:
        a = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()["allocation"]
    # 6 of 12 months on record: the card must call the basis partial, never
    # present half a year as a full prior-year basis.
    assert a["basis_months"] == 6
    assert a["basis_sales"] == pytest.approx(600.0)


def test_allocation_and_combined_pesos_are_withheld_under_all_principals():
    """Allocations are per principal, and the two principals' pesos are on
    different tax bases — under 'all' the rule is not applied and the mixed
    total carries the VAT note."""
    session = FakeSession()
    with make_client(session) as c:
        body = c.get("/dashboard", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert "pick one principal" in body["allocation"]["blocked_reason"]
    # One shape whatever the state: withheld keys are present and null.
    assert set(body["allocation"]) == {
        "basis_year", "basis_sales", "basis_months", "latest_month", "ytd_sales",
        "ytd_months", "levels", "vat_basis", "blocked_reason",
        "planning_month", "allocation_year", "unit", "default_pct",
    }
    assert body["allocation"]["levels"] == [] and body["allocation"]["basis_sales"] is None
    assert body["vat_note"] == (
        "Unilever pesos include VAT; Del Monte pesos exclude it — combined totals mix the two tax bases."
    )


def test_allocation_basis_is_the_year_before_the_planning_month():
    """Item 7: one rule with the LP (analytics/allocation.py). Data through
    December plans January, so the basis is that December's own year and the
    allocation year has no sales yet; the Del Monte card still renders (pesos,
    since Del Monte has no pieces)."""
    session = FakeSession(latest_sales_period=None)
    session.delmonte_sales = {f"2025-{m:02d}": 1_000.0 for m in range(1, 13)}
    session.delmonte_latest_sales_period = "2025-12"
    with make_client(session) as c:
        a = c.get("/dashboard?principal=delmonte", headers={"Authorization": f"Bearer {user_token()}"}).json()["allocation"]
    assert a["blocked_reason"] is None
    assert (a["planning_month"], a["allocation_year"], a["basis_year"]) == ("2026-01", 2026, 2025)
    assert a["basis_sales"] == pytest.approx(12_000.0) and a["basis_months"] == 12
    assert a["ytd_months"] == 0 and a["ytd_sales"] is None
    assert a["unit"] == "pesos" and a["default_pct"] == 103
    assert [level["pct"] for level in a["levels"]] == [103, 105, 108]
    assert a["levels"][0]["monthly"] == pytest.approx(12_000.0 * 1.03 / 12)


def test_allocation_is_withheld_when_the_prior_year_nets_to_zero():
    """Returns and credits can net a year to ₱0 or less; scaling that by
    103-108% would draw a meaningless allocation (and divide by zero)."""
    sales = {f"2025-{m:02d}": 0.0 for m in range(1, 13)}
    sales["2026-01"] = 50.0
    session = FakeSession(latest_sales_period="2026-01", sales=sales)
    with make_client(session) as c:
        a = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()["allocation"]
    assert a["levels"] == []
    assert "₱0 or less" in a["blocked_reason"]



def test_vat_note_names_del_montes_tax_inclusive_month_when_the_range_holds_it():
    """Kelvin's X2 rule loads a Del Monte sheet's tax-inclusive total where
    that was its only amount and flags the rows (live: 2023-08). Inside the
    range the note must name the exception; outside it, it stays plain."""
    session = FakeSession()
    session.dm_tax_inclusive_periods = ["2023-08"]  # inside the default 12 months to 2024-02
    with make_client(session) as c:
        note = c.get("/dashboard", headers={"Authorization": f"Bearer {user_token()}"}).json()["vat_note"]
    assert note == (
        "Unilever pesos include VAT; Del Monte pesos exclude it (except Aug 2023, recorded with tax) — "
        "combined totals mix the two tax bases."
    )

    session = FakeSession()
    session.dm_tax_inclusive_periods = ["2021-08"]  # outside the range
    with make_client(session) as c:
        note = c.get("/dashboard", headers={"Authorization": f"Bearer {user_token()}"}).json()["vat_note"]
    assert "except" not in note
