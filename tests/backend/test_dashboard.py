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

from backend import auth_utils, marts
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
        # Each ranked product's own net revenue at the ABC period
        # (_abc_class_revenue). Empty = not found, which keeps abc_mix on
        # the stored revenue_share sums, as before.
        abc_product_revenue: dict | None = None,
        # VAT inside Purchase_Fact.net_amount per period (Del Monte's is
        # 12/112 of it); subtracted only by a query that asks for it.
        received_tax: dict | None = None,
        # DEC-31 derived Unilever receipts: None = no derived_receipt_fact table
        # (public before migration 0038); a dict = the table, {period: (value, negative_skus, skus)}.
        derived: dict | None = None,
        # Inventory_Fact_Real.snapshot_date per _period (_stock_count_dates):
        # {period: date} for one count day, or {period: (first, last)} for a
        # period whose rows in scope were counted on two different days.
        count_dates: dict | None = None,
        # backend/stock_units.STOCK_COUNTS_SQL: {(principal, period): (row_count,
        # first_date, last_date)}. Empty = no principal counted at any period.
        stock_counts: dict | None = None,
        # ---- the marts (migration 0041, backend/marts.py) ----
        # Each product's net sales over the requested RANGE, per principal:
        # {principal: {product_key: revenue}} — what mart.sales_mart sums;
        # the fake ranks it the way backend/marts.PARETO_SQL does.
        range_revenue: dict | None = None,
        # {product_key: (any_active, any_inactive)} at the range-end count.
        stock_status: dict | None = None,
        # Product keys with a pending row in the LP's current cycle.
        pending_keys: set | None = None,
        # Non-real chart points: {principal: {period: (kind, value)}}.
        estimated_sales: dict | None = None,
        estimated_stock: dict | None = None,
        # Returns flow: {principal: {period: (data_kind, pesos, source_tag)}}.
        returns: dict | None = None,
        # Scored rows mart.accuracy_mart returns for the range.
        accuracy_rows: list | None = None,
        # Unilever pieces per sales month (mart.sales_month).
        sales_pieces: dict | None = None,
    ):
        self.stock_counts = stock_counts or {}
        self.range_revenue = range_revenue or {}
        self.stock_status = stock_status or {}
        self.pending_keys = pending_keys or set()
        self.estimated_sales = estimated_sales or {}
        self.estimated_stock = estimated_stock or {}
        self.returns = returns or {}
        self.accuracy_rows = accuracy_rows or []
        self.sales_pieces = sales_pieces or {}
        # A current stock on an ABC fixture row means a count was taken that
        # month: the safety-stock check reads the count at the range's end.
        if latest_inventory_period is None:
            stocked = [r["period"] for r in (abc_rows or []) if r.get("current_stock") is not None]
            latest_inventory_period = max(stocked) if stocked else None
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
        # policy_comparison rows: [{planning_cycle_date, ss_i, rop_i, forecast_value}]
        self.policy_rows = policy_rows or []
        self.lp_cycle_date = lp_cycle_date
        self.lp_superseded_pending = lp_superseded_pending
        self.lp_generated_at = lp_generated_at
        self.forecast_generated_at = forecast_generated_at
        self.lp_row_count = lp_row_count
        self.lp_stale_rows = lp_stale_rows
        self.stock_coverage = stock_coverage or []
        self.abc_coverage = abc_coverage or []
        self.abc_product_revenue = abc_product_revenue or {}
        self.received_tax = received_tax or {}
        self.derived = derived
        self.count_dates = count_dates or {}
        # Every (sql, params) issued, so a test can assert on the query text
        # itself — the only way to check scope/unit handling that lives in
        # SQL rather than in Python (see this module's docstring).
        self.calls: list[tuple[str, dict]] = []
        # A real Session's per-request dict: backend/marts keeps the month-level
        # snapshot here, so it is read once per request.
        self.info: dict = {}

    def _latest_stock(self, principal, end):
        candidates = {p for p, v in self.soh.items() if v is not None}
        if self.latest_inventory_period:
            candidates.add(self.latest_inventory_period)
        if end is not None:
            candidates = {p for p in candidates if p <= end}
        return max(candidates) if candidates else None

    def _snapshot_rows(self):
        """mart.sales_month / inventory_count / flow_month rows built from the fixtures,
        in backend/marts.SNAPSHOT_SQL's shape."""
        rows = []

        def add(src, who, period, kind, **v):
            rows.append({"src": src, "principal": who, "period": period, "data_kind": kind,
                         "source_tag": v.get("source_tag"), "flow": v.get("flow"), "pesos": v.get("pesos"),
                         "pieces": v.get("pieces"), "recorded_with_tax": v.get("recorded_with_tax", False),
                         "placeholder": v.get("placeholder", False), "first_date": v.get("first_date"),
                         "last_date": v.get("last_date"), "negative_rows": v.get("negative_rows"),
                         "products": v.get("products")})

        # Real sales; the latest-month fixtures count as months on file even with no pesos.
        for who, source, latest in (("unilever", self.sales, self.latest_sales_period),
                                    ("delmonte", self.delmonte_sales, self.delmonte_latest_sales_period)):
            months = set(source) | ({latest} if latest else set())
            if who == "delmonte":
                months |= set(self.dm_tax_inclusive_periods)
            for m in months:
                add("sales", who, m, "real", pesos=source.get(m),
                    pieces=self.sales_pieces.get(m) if who == "unilever" else None,
                    recorded_with_tax=who == "delmonte" and m in self.dm_tax_inclusive_periods)
        for who, by_month in self.estimated_sales.items():
            for m, (kind, value) in by_month.items():
                add("sales", who, m, kind, pesos=value)
        # Real stock counts: Unilever's, plus any principal the coverage fixture names.
        counts = {m for m, v in self.soh.items() if v is not None}
        if self.latest_inventory_period:
            counts.add(self.latest_inventory_period)
        for who in {"unilever"} | set(self.stock_coverage):
            for m in counts:
                _, first, last = self.stock_counts.get((who, m), (None, None, None))
                add("stock", who, m, "real", pesos=self.soh.get(m), first_date=first, last_date=last)
        for who, by_month in self.estimated_stock.items():
            for m, (kind, value) in by_month.items():
                add("stock", who, m, kind, pesos=value)
        # Flows: purchases (Del Monte's ex-VAT in the mart), estimated receipts, returns.
        for who in ("unilever", "delmonte"):
            for m, value in self.received.items():
                if value is not None:
                    add("flow", who, m, "real", flow="purchases", source_tag="real", negative_rows=0,
                        pesos=value - (self.received_tax.get(m, 0.0) if who == "delmonte" else 0.0))
        for m, (value, negative, skus) in (self.derived or {}).items():
            add("flow", "unilever", m, "filled", flow="estimated_receipts", source_tag="derived_stock_balance",
                pesos=value, negative_rows=negative, products=skus)
        for who, by_month in self.returns.items():
            for m, (kind, value, tag) in by_month.items():
                add("flow", who, m, kind, flow="returns", source_tag=tag, pesos=value, negative_rows=0)
        return rows

    def _pareto(self, principal):
        """backend/marts.PARETO_SQL on the fixture: net > 0 only, revenue desc then
        product_key, running share rounded as exact numeric division would be."""
        items = sorted(((k, v) for k, v in self.range_revenue.get(principal, {}).items() if v > 0),
                       key=lambda kv: (-kv[1], kv[0]))
        total = sum(v for _, v in items)
        rows, running = [], 0.0
        for rank, (key, value) in enumerate(items, 1):
            running += value
            cum = round(running / total, 12)
            rows.append({"rank": rank, "product_key": key, "sku_code": f"SKU{key}", "product_name": f"Product {key}",
                         "category_path": None, "brand": None, "revenue": value, "pieces": None,
                         "months_with_sales": 1, "share": value / total, "cumulative_share": cum,
                         "class": "A" if cum <= 0.80 else "B" if cum <= 0.95 else "C"})
        return rows

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, dict(params)))

        # backend/marts.stock_detail_query (2026-10-19, kpis.above_policy): these
        # fixtures carry no per-product stock, so no product rows.
        if "WITH stock AS" in sql and "mart.inventory_mart_real" in sql:
            self.stock_detail_params = dict(params)
            return FakeResult(getattr(self, "stock_detail_rows", []))

        # backend/marts.status: no refresh log in these fixtures.
        if "to_regclass('mart.refresh_log')" in sql:
            return FakeResult([{"present": False}])

        # backend/lp_cycle.stored_run (migration 0037). Before every
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

        # backend/stock_units.stock_counts: which count, and when it was taken.
        if "GROUP BY inv.principal, inv._period" in sql:
            period = params["count_period"]
            return FakeResult([
                {"principal": who, "period": p, "row_count": n, "first_date": first, "last_date": last}
                for (who, p), (n, first, last) in self.stock_counts.items() if p == period
            ])

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

        # tier_stock's pending reorders, before the _SELECT_ONE matcher.
        if "SELECT DISTINCT lr.product_key" in sql:
            return FakeResult([{"product_key": k} for k in sorted(self.pending_keys)])

        # Checked FIRST among the row queries: recommendations._SELECT_ONE
        # (reused verbatim by reorder_preview) embeds its own stock
        # subquery, which a stock matcher below would otherwise claim.
        if "FROM lp_recommendation lr" in sql and "WHERE lr.status = 'pending'" in sql:
            return FakeResult(self.reco_preview_rows)

        if "COUNT(*) AS product_count" in sql:
            return FakeResult([{"product_count": self.recommendation_count}])

        if "COUNT(*) FILTER (WHERE fr.mase >= :mase_gate)" in sql:
            assert params.get("mase_gate") == 1.0, "unreliable_count must gate on MASE >= 1"
            return FakeResult([{"total_count": self.forecast_total, "evaluated_count": self.forecast_evaluated,
                                "unreliable_count": self.forecast_unreliable}])

        # ---- the marts -------------------------------------------------
        if "WITH rev AS" in sql:
            assert "data_kind = 'real'" in sql, "the Pareto ranks real rows only"
            return FakeResult(self._pareto(params["principal"]))

        # backend/marts.SNAPSHOT_SQL: every month-level mart row, one read per request.
        if "'sales' AS src" in sql:
            return FakeResult(self._snapshot_rows())

        if sql.strip().startswith("SELECT 1 FROM mart.inventory_count"):
            return FakeResult([])  # the idle check's "is there a count"

        if "FROM mart.inventory_mart_real" in sql:
            keys = set(params["keys"])
            if "any_active" in sql:
                return FakeResult([{"product_key": k, "any_active": a, "any_inactive": i}
                                   for k, (a, i) in self.stock_status.items() if k in keys])
            return FakeResult([{"product_key": r["product_key"], "pieces": r["current_stock"]}
                               for r in self.abc_rows
                               if r["product_key"] in keys and r.get("current_stock") is not None])

        if "FROM mart.accuracy_mart a" in sql:
            return FakeResult(self.accuracy_rows)

        if "FROM mart.idle_stock" in sql:
            return FakeResult([{"count_date": None, "window_start": None, "window_end": None, "window_months": None,
                                "products": 0, "products_with_value": 0, "pesos": None, "never_sold": 0}])

        if "AS qty" in sql:
            return FakeResult([{"period": p, "qty": v} for p, v in self.portfolio_actual.items()])

        # ---- the stored ABC run (the safety-stock cohort) ------------
        if "MAX(classification_period) AS p FROM ABC_Classification" in sql and "<=" not in sql:
            return FakeResult([{"principal": "unilever", "p": self.latest_abc_period}])

        if "MAX(classification_period) AS p FROM ABC_Classification" in sql and "<=" in sql:
            # _nearest_abc_period_at_or_before: latest fixture period at or
            # before the requested one, mirroring the real MAX(...) <= :period.
            target = params["at_or_before"]
            candidates = sorted({r["period"] for r in self.abc_rows if r["period"] <= target})
            return FakeResult([{"principal": "unilever", "p": candidates[-1] if candidates else None}])

        if "rop.ss_i AS ss_i" in sql:
            period = params["abc_p_unilever"]
            rows = [r for r in self.abc_rows if r["period"] == period and r["tier"] == "A"]
            return FakeResult([
                {"product_key": r["product_key"], "sku_id": f"SKU{r['product_key']}",
                 "product_name": f"Product {r['product_key']}", "revenue_share": r.get("revenue_share"),
                 "ss_i": r["ss_i"], "rop_i": r.get("rop_i"), "q_i": r.get("q_i")}
                for r in rows
            ])

        if "fr.forecast_date = lr.planning_cycle_date" in sql:
            return FakeResult(self.policy_rows)

        if sql.strip() == "SELECT MAX(forecast_date) AS d FROM Forecast_Result":
            return FakeResult([{"d": self.latest_forecast_date}])

        if "fr.mase < :mase_gate" in sql:
            assert params.get("mase_gate") == 1.0, "the portfolio gate must be the LP's own MASE < 1"
            return FakeResult(self.gated_forecast_rows)

        if "SELECT COUNT(*) FROM Forecast_Result fr" in sql:
            return FakeResult([self.scoped_forecast_count])

        if "SELECT EXISTS" in sql and "mart.sales_mart" in sql and "AS present" in sql:
            # marts.pareto_blocked_reason (B3, 2026-10-16): any real sales row for the principal in
            # the range, whatever its sign — the fixture's range_revenue is exactly those rows.
            return FakeResult([{"present": bool(self.range_revenue.get(params["principal"]))}])

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
    assert kpis["soh_value_blocked_reason"] == "No stock count for unilever on or before Feb 2024."


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
    assert "safety stock in the current order plan" in kpis["safety_stock_rate_blocked_reason"]


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
    assert wc["blocked_reason"] == "No stock count for unilever at all."


def test_weeks_of_cover_reads_the_stock_cards_count():
    """Weeks of cover is the stock card's own count — the one at the range's end —
    over the 12 months of sales up to it (DEC-36, 2026-10-04; supersedes the
    2026-09-29 latest-count rule). Ranges of any width that end at the same count
    give the same weeks: the denominator never follows the range's width (it used
    to average the picker's months, reading 3.0-3.5 weeks for one count)."""
    periods = _periods()  # 2023-03 .. 2024-02
    sales = {p: 100.0 for p in periods}
    sales[periods[-1]] = 400.0  # one unusual month
    expected = round(1000.0 / ((sum(sales.values()) / 12) / AVG_WEEKS_PER_MONTH), 2)
    for query in ("", "&start_period=2024-01&period=2024-02", "&start_period=2021-01&period=2024-02"):
        session = FakeSession(latest_inventory_period="2024-02", soh={"2023-07": 300.0, "2024-02": 1000.0},
                              sales=dict(sales))
        wc = _get(session, f"principal=unilever{query}")["kpis"]["weeks_of_cover"]
        assert wc["value"] == pytest.approx(expected), query
        assert wc["stock_period"] == "2024-02" and wc["sales_window"] == {"start": periods[0], "end": periods[-1]}
        assert wc["months_used"] == 12, query
    # A range ending at the July 2023 count reads that count, over the sales up to it.
    session = FakeSession(latest_inventory_period="2024-02", soh={"2023-07": 300.0, "2024-02": 1000.0},
                          sales=dict(sales))
    wc = _get(session, "principal=unilever&start_period=2023-01&period=2023-07")["kpis"]["weeks_of_cover"]
    assert wc["stock_period"] == "2023-07"
    assert wc["value"] == pytest.approx(round(300.0 / (100.0 / AVG_WEEKS_PER_MONTH), 2))
    body = _get(FakeSession(latest_inventory_period="2024-02", soh={"2024-02": 1000.0}, sales=dict(sales)),
                "principal=unilever")["kpis"]
    assert body["weeks_of_cover_range_end"] == body["weeks_of_cover"]


def test_weeks_of_cover_carries_the_territory_caveat_for_unilever_only():
    session = FakeSession(latest_inventory_period="2024-02", soh={"2024-02": 1000.0},
                          sales={p: 100.0 for p in _periods()})
    caveat = _get(session, "principal=unilever")["kpis"]["weeks_of_cover"]["caveat"]
    assert caveat == "stock = Ilocos Sur warehouse; sales = La Union only; territory match unverified"
    dm = FakeSession(latest_sales_period=None, latest_inventory_period="2025-12", soh={"2025-12": 6_683_837.26},
                     stock_coverage=["delmonte"])
    dm.delmonte_latest_sales_period = "2025-12"
    dm.delmonte_sales = {"2025-12": 22_134_295.57}
    assert _get(dm, "principal=delmonte")["kpis"]["weeks_of_cover"]["caveat"] is None


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
    assert series[-1] == {"period": current, "sales": 100.0, "stock_on_hand": None, "stock_count_date": None,
                          "received": None, "received_estimated": None, "received_estimated_negative_skus": None,
                          "sales_estimated": None, "sales_estimated_kind": None,
                          "stock_on_hand_estimated": None, "stock_on_hand_estimated_kind": None,
                          "returns": None, "returns_estimated": None, "returns_estimated_kind": None,
                          "provenance": {"sales": "real", "stock_on_hand": None, "received": None,
                                         "received_estimated": None, "sales_estimated": None,
                                         "stock_on_hand_estimated": None, "returns": None,
                                         "returns_estimated": None}}
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


# ---- sales_vs_stock[].received_estimated (DEC-31 derived Unilever receipts) ----

def test_estimated_received_is_its_own_series_labelled_derived():
    current = _periods()[-1]
    session = FakeSession(received={}, derived={current: (1234.5, 7, 600)})
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    pt = resp.json()["sales_vs_stock"][-1]
    assert pt["received"] is None                                   # never folded into the real series
    assert pt["received_estimated"] == 1234.5 and pt["received_estimated_negative_skus"] == 7
    assert pt["provenance"]["received_estimated"] == "derived" and pt["provenance"]["received"] is None


def test_estimated_received_is_never_shown_under_all_or_delmonte():
    current = _periods()[-1]
    for scope in ("all", "delmonte"):
        session = FakeSession(received={}, derived={current: (1234.5, 7, 600)})
        with make_client(session) as c:
            resp = c.get(f"/dashboard?principal={scope}", headers={"Authorization": f"Bearer {user_token()}"})
        assert all(pt["received_estimated"] is None for pt in resp.json()["sales_vs_stock"])
        assert not any("FROM derived_receipt_fact" in sql for sql, _ in session.calls)


def test_estimated_received_is_null_before_migration_0038():
    session = FakeSession(received={})                              # derived=None: no table
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    assert all(pt["received_estimated"] is None for pt in resp.json()["sales_vs_stock"])
    assert not any("FROM derived_receipt_fact" in sql for sql, _ in session.calls)


# ---- abc_mix ---------------------------------------------------------

def test_abc_mix_counts_and_revenue_share_pct():
    """The ring ranks each product's net sales over the selected range
    (backend/marts.pareto): A while the running share is <= 80%, B <= 95%."""
    session = FakeSession(range_revenue={"unilever": {1: 600.0, 2: 200.0, 3: 150.0, 4: 50.0}})
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    mix = {m["tier"]: m for m in resp.json()["abc_mix"]}
    assert mix["A"]["count"] == 2
    assert mix["A"]["revenue_share_pct"] == pytest.approx(80.0)
    assert mix["A"]["revenue"] == pytest.approx(800.0)
    assert mix["B"]["count"] == 1
    assert mix["B"]["revenue_share_pct"] == pytest.approx(15.0)
    assert mix["C"]["count"] == 1


def test_abc_mix_empty_when_nothing_sold_more_than_it_took_back():
    session = FakeSession(range_revenue={"unilever": {1: -50.0, 2: 0.0}})
    body = _get(session, "principal=unilever")
    assert body["abc_mix"] == []
    assert body["abc_revenue"]["ranked_total"] is None
    assert "took back" in body["abc_revenue"]["blocked_reason"]


def test_abc_mix_ranks_the_selected_range():
    """The picker's start and end are the ranking's window — not a stored
    single-month run — and the ring names that range."""
    session = FakeSession(range_revenue={"unilever": {1: 500.0, 2: 500.0}})
    body = _get(session, "principal=unilever&period=2023-06&start_period=2023-01")
    _, params = _sql_for(session, "WITH rev AS")
    assert (params["start"], params["end"]) == ("2023-01", "2023-06")
    rev = body["abc_revenue"]
    assert (rev["start_period"], rev["end_period"], rev["period"]) == ("2023-01", "2023-06", "2023-06")
    assert rev["label"] == "Jan 2023 – Jun 2023"
    assert rev["basis"] == "range"


# ---- tier_stock (Inventory_Fact_Real.stock_status, dead-stock signal) --

def test_tier_stock_dead_stock_from_stock_status_including_no_data_bucket():
    session = FakeSession(
        latest_inventory_period=FIXED_ANCHOR,
        range_revenue={"unilever": {1: 10.0, 2: 10.0, 3: 10.0, 4: 10.0, 9: 1.0}},
        stock_status={1: (True, False), 2: (False, True),
                      3: (True, True)},  # both flags (several rows): dead stock wins
        # 4: no row at the count -> no_data
        pending_keys={1, 3},
    )
    body = _get(session, "principal=unilever")
    tiers = {t["tier"]: t for t in body["tier_stock"]}
    # Running shares: 10/41, 20/41, 30/41 (A), 40/41 = 0.976 (C), 41/41 (C).
    assert tiers["A"] == {"tier": "A", "in_stock": 1, "dead_stock": 2, "no_data": 0, "pending_reorder_count": 2}
    assert tiers["C"]["no_data"] == 2


def test_tier_stock_pending_reorder_count_is_zero_not_null_when_no_pending_rows():
    session = FakeSession(latest_inventory_period=FIXED_ANCHOR, range_revenue={"unilever": {1: 10.0}},
                          stock_status={1: (True, False)})
    body = _get(session, "principal=unilever")
    assert body["tier_stock"][0]["pending_reorder_count"] == 0


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
        "Unilever (product forecasts that beat a simple last-month guess, the order plan's own check)."
    )
    by_period = {pt["period"]: pt for pt in pf["series"]}
    assert by_period["2024-01"]["actual"] == pytest.approx(90.0)
    assert by_period["2024-02"]["actual"] == pytest.approx(95.0)
    assert by_period["2024-03"]["forecast"] == pytest.approx(150.0)
    # Half-widths 20 and 10 combine as sqrt(20² + 10²) = 22.36, not 30 (the
    # summed bounds, 120-180, that assumed both SKUs miss together).
    assert by_period["2024-03"]["confidence_lower"] == pytest.approx(127.64)
    assert by_period["2024-03"]["confidence_upper"] == pytest.approx(172.36)
    assert by_period["2024-03"]["actual"] is None


def test_portfolio_band_is_root_sum_of_squares_from_the_unfloored_upper_side():
    """Summing per-SKU bounds read 443,592-1,763,518 around 1,085,193 (±62%)
    for Mar 2026. Each SKU's half-width is upper - forecast (its lower bound
    is floored at 0, so it understates); the total's is sqrt(sum of squares),
    and the total's own lower bound is floored at 0."""
    d = datetime.date(2024, 3, 1)
    gated_rows = [
        # Floored per SKU: lower 0 though forecast - 1.645 x RMSE = -30.
        {"product_key": 1, "forecast_date": d, "forecast_value": 30.0,
         "confidence_lower": 0.0, "confidence_upper": 90.0, "mase": 0.5},
        {"product_key": 2, "forecast_date": d, "forecast_value": 1000.0,
         "confidence_lower": 920.0, "confidence_upper": 1080.0, "mase": 0.5},
        # No holdout RMSE: no band, adds nothing to the total's.
        {"product_key": 3, "forecast_date": d, "forecast_value": 70.0,
         "confidence_lower": None, "confidence_upper": None, "mase": 0.5},
    ]
    session = FakeSession(latest_forecast_date=d, gated_forecast_rows=gated_rows)
    with make_client(session) as c:
        series = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()[
            "portfolio_forecast"]["series"]
    bucket = next(pt for pt in series if pt["period"] == "2024-03")
    half = (60.0 ** 2 + 80.0 ** 2) ** 0.5  # 100
    assert bucket["forecast"] == pytest.approx(1100.0)
    assert bucket["confidence_lower"] == pytest.approx(1100.0 - half)
    assert bucket["confidence_upper"] == pytest.approx(1100.0 + half)

    # A small total with a wide band floors at 0, never a negative demand.
    session = FakeSession(latest_forecast_date=d, gated_forecast_rows=gated_rows[:1])
    with make_client(session) as c:
        series = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()[
            "portfolio_forecast"]["series"]
    bucket = next(pt for pt in series if pt["period"] == "2024-03")
    assert bucket["confidence_lower"] == 0.0
    assert bucket["confidence_upper"] == pytest.approx(90.0)


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
        "All principals — only Unilever has product forecasts that beat a simple "
        "last-month guess (the order plan's own check), so this matches the Unilever view."
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

def _reco_row(key, urgency_stock, rop_i, ss_i=50.0):
    """urgency_stock chosen relative to ss_i and rop_i to land in a specific
    urgency bucket (backend/stock_status.py): CRITICAL below ss_i, LOW below
    rop_i, OK at or above it."""
    return {
        "recommendation_key": key,
        "sku_id": f"SKU-{key}",
        "product_name": f"Product {key}",
        "principal": "unilever",
        "planning_cycle_date": "2024-02-01",
        "q_i": 10.0,
        "rop_i": rop_i,
        "ss_i": ss_i,
        "status": "pending",
        "current_stock": urgency_stock,
    }


def test_reorder_preview_top5_sorted_by_urgency_full_set_counts():
    rows = [
        _reco_row(1, urgency_stock=0, rop_i=100),    # CRITICAL (0 < ss 50)
        _reco_row(2, urgency_stock=90, rop_i=100),   # LOW (50 <= 90 < 100)
        _reco_row(3, urgency_stock=150, rop_i=100),  # OK (150 >= 100)
        _reco_row(4, urgency_stock=10, rop_i=100),   # CRITICAL
        _reco_row(5, urgency_stock=20, rop_i=100),   # CRITICAL
        _reco_row(6, urgency_stock=30, rop_i=100),   # CRITICAL
        _reco_row(7, urgency_stock=95, rop_i=100),   # LOW
        _reco_row(8, urgency_stock=40, rop_i=100),   # CRITICAL
    ]
    session = FakeSession(reco_preview_rows=rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    preview = resp.json()["reorder_preview"]
    assert len(preview["rows"]) == 5
    assert all(r["urgency"] == "CRITICAL" for r in preview["rows"])
    assert preview["critical_count"] == 5
    assert preview["low_count"] == preview["urgent_count"] == 2
    assert preview["total_order_qty"] == pytest.approx(80.0)  # 8 rows x q_i=10, full set not just top 5


def test_reorder_preview_critical_means_below_safety_stock_not_half_the_target():
    """Item 9: CRITICAL is stock below ss_i. The old rule said below
    0.5 x rop_i, a threshold with no source."""
    rows = [
        _reco_row(1, urgency_stock=30, rop_i=100, ss_i=20.0),  # was CRITICAL (30 < 50): now URGENT
        _reco_row(2, urgency_stock=70, rop_i=100, ss_i=80.0),  # was URGENT: now CRITICAL (70 < 80)
    ]
    session = FakeSession(reco_preview_rows=rows)
    with make_client(session) as c:
        preview = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()["reorder_preview"]
    # Below the target stock is URGENT on the reorder page (backend/stock_status.URGENCY).
    assert {r["sku_id"]: r["urgency"] for r in preview["rows"]} == {"SKU-1": "URGENT", "SKU-2": "CRITICAL"}
    assert (preview["critical_count"], preview["low_count"], preview["urgent_count"]) == (1, 1, 1)


def test_reorder_preview_empty_when_no_pending_recommendations():
    session = FakeSession(reco_preview_rows=[])
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    preview = resp.json()["reorder_preview"]
    assert preview == {
        "rows": [], "critical_count": 0, "low_count": 0, "urgent_count": 0, "no_data_count": 0, "total_order_qty": 0,
        "lp_weights": {"cost": 0.45, "service_level": 0.35, "storage": 0.2},
        "lp_weights_source": "defaults",
        "stock_counts": [],  # no LP cycle, so no opening count to name
    }


def test_stock_cards_read_the_count_at_the_ranges_end():
    """Every card answers for the selected range (2026-10-04): the stock card
    and the safety-stock check read the latest count on or before the range's
    end — 2026-02, counted 2026-03-02, for a range ending Feb 2026 — not the
    2026-03 count after it. Weeks of cover keeps the latest count (its
    2026-09-29 rule) and offers the range-end figure beside it."""
    session = FakeSession(
        latest_sales_period="2026-02", sales={"2026-02": 27_914_343.91},
        latest_inventory_period="2026-03", soh={"2026-02": 46_576_778.51, "2026-03": 22_700_825.83},
        stock_counts={("unilever", "2026-03"): (785, datetime.date(2026, 4, 6), datetime.date(2026, 4, 6)),
                      ("unilever", "2026-02"): (812, datetime.date(2026, 3, 2), datetime.date(2026, 3, 2))},
    )
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    kpis = body["kpis"]
    assert kpis["soh_period"] == "2026-02"
    assert kpis["soh_value"] == pytest.approx(46_576_778.51)
    assert kpis["soh_count_date"] == "2026-03-02"
    assert kpis["soh_snapshot"]["period"] == "2026-02" and kpis["soh_snapshot"]["is_range_end"] is True
    count = kpis["stock_counts"]
    assert [(x["principal"], x["period"], x["role"], x["counted_on"]) for x in count] == [
        ("unilever", "2026-02", "latest", "2026-03-02")]
    assert body["safety_stock_exposure"]["stock_period"] == "2026-02"
    assert body["safety_stock_exposure"]["stock_counts"] == count
    # Weeks of cover reads the same count (DEC-36, 2026-10-04).
    assert kpis["weeks_of_cover"]["stock_period"] == "2026-02"
    assert kpis["weeks_of_cover"]["stock_count_date"] == "2026-03-02"
    assert kpis["weeks_of_cover_range_end"] == kpis["weeks_of_cover"]
    # The count is the one the team flagged: the card keeps it and says so.
    assert kpis["soh_count_note"] == (
        "Counted 2 Mar 2026: unusually high (₱46.6M), accepted pending SSM confirmation")
    assert kpis["soh_snapshot"]["note"] == kpis["soh_count_note"]
    # A range ending at the next count has nothing to note.
    later = _get(session, "principal=unilever&period=2026-03&start_period=2025-04")["kpis"]
    assert later["soh_period"] == "2026-03" and later["soh_count_note"] is None


def test_reorder_preview_reads_the_count_that_opens_the_cycle():
    """The preview is the Reorder page's first rows, so it checks them
    against the count the plan was made from (2026-02 for cycle 2026-03),
    while the stock card above stays on the latest (2026-03)."""
    session = FakeSession(
        latest_inventory_period="2026-03", lp_cycle_date=datetime.date(2026, 3, 1),
        reco_preview_rows=[_reco_row(1, urgency_stock=10, rop_i=100)],
        stock_counts={("unilever", "2026-02"): (812, datetime.date(2026, 3, 2), datetime.date(2026, 3, 2))},
    )
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    preview_params = next(p for s, p in session.calls if "AS in_stock_count" in s)
    assert preview_params["inv_period"] == "2026-02"
    counts = body["reorder_preview"]["stock_counts"]
    assert [(x["cycle"], x["period"], x["role"], x["counted_on"]) for x in counts] == [
        ("2026-03-01", "2026-02", "opening", "2026-03-02")]


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


def test_abc_revenue_totals_the_ranges_sales():
    """total = the range's net sales (returns included, the sales card's own
    sum); ranked_total = what the shares are shares of."""
    periods = _periods()
    session = FakeSession(sales={periods[0]: 1_000.0, periods[-1]: 2_000.0},
                          range_revenue={"unilever": {1: 2_900.0, 2: 150.0, 3: -50.0}})
    body = _get(session, "principal=unilever")["abc_revenue"]
    assert body["period"] == periods[-1]
    assert body["total"] == pytest.approx(3_000.0)
    assert body["ranked_total"] == pytest.approx(3_050.0)
    assert body["blocked_reason"] is None


def test_abc_revenue_under_all_withholds_shares_when_both_principals_rank():
    """Each principal is ranked against its own revenue: the counts add up,
    the shares would not (Class A summed to ~151% under 'all', 2026-09-29)."""
    session = FakeSession(range_revenue={"unilever": {1: 100.0}, "delmonte": {50: 30.0}})
    body = _get(session, "")
    assert body["abc_coverage"] == ["delmonte", "unilever"]
    # One product each: a lone product's running share is 100%, above the B
    # cutoff, so both are class C (classify_abc's rule).
    assert [(m["tier"], m["count"]) for m in body["abc_mix"]] == [("C", 2)]
    assert all(m["revenue_share_pct"] is None and m["revenue"] is None for m in body["abc_mix"])
    assert body["abc_revenue"]["total"] is None and "not combined" in body["abc_revenue"]["blocked_reason"]


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


def test_safety_stock_exposure_says_why_the_rest_cannot_be_checked():
    """The Below safety stock card's "why N can't be checked" (2026-10-18):
    every Class A row outside the comparison is counted once, by what it
    lacks, so the three counts add up to tier_a_count - comparable_count."""
    rows = [
        _abc_row(1, "A", "2024-02", 0.30, current_stock=10, ss_i=50),     # checked
        _abc_row(2, "A", "2024-02", 0.20, current_stock=80, ss_i=50),     # checked
        _abc_row(3, "A", "2024-02", 0.10, current_stock=None, ss_i=50),   # no stock count
        _abc_row(4, "A", "2024-02", 0.08, current_stock=None, ss_i=50),   # no stock count
        _abc_row(5, "A", "2024-02", 0.06, current_stock=40, ss_i=None),   # no safety stock
        _abc_row(6, "A", "2024-02", 0.04, current_stock=None, ss_i=None), # neither
    ]
    session = FakeSession(latest_abc_period="2024-02", abc_rows=rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    exp = resp.json()["safety_stock_exposure"]
    assert exp["uncheckable"] == {"no_safety_stock": 1, "no_stock_count": 2, "missing_both": 1}
    assert sum(exp["uncheckable"].values()) == exp["tier_a_count"] - exp["comparable_count"]
    # The rows behind the counts (the list the card opens): each once, by reason,
    # then the most revenue first.
    items = exp["uncheckable_items"]
    assert [(i["sku_id"], i["reason"]) for i in items] == [
        ("SKU5", "no_safety_stock"), ("SKU3", "no_stock_count"), ("SKU4", "no_stock_count"), ("SKU6", "missing_both"),
    ]


def test_safety_stock_exposure_blocked_when_nothing_measurable():
    session = FakeSession(latest_abc_period="2024-02", abc_rows=[_abc_row(1, "A", "2024-02", 0.6)])
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    exp = resp.json()["safety_stock_exposure"]
    assert exp["below_count"] is None
    assert exp["below_items"] == []
    assert exp["blocked_reason"]
    assert exp["uncheckable"] is None


def test_safety_stock_exposure_lists_the_products_behind_the_count():
    """The list a reader opens from "N below safety stock" is the rows the
    count was taken from: most revenue first, named, with the shortfall in
    pieces — and never a product that is at or above its safety stock, or
    one with no stock count (2026-10-03)."""
    rows = [
        _abc_row(1, "A", "2024-02", 0.10, current_stock=10, ss_i=50),    # below, smaller share
        _abc_row(2, "A", "2024-02", 0.30, current_stock=0, ss_i=40.5),   # below, biggest share
        _abc_row(3, "A", "2024-02", 0.20, current_stock=80, ss_i=50),    # at/above
        _abc_row(4, "A", "2024-02", 0.25, current_stock=None, ss_i=50),  # not measurable
    ]
    rows[1].update(rop_i=120.0, q_i=300.0)
    session = FakeSession(latest_abc_period="2024-02", abc_rows=rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    exp = resp.json()["safety_stock_exposure"]
    items = exp["below_items"]
    assert len(items) == exp["below_count"] == 2
    assert [i["sku_id"] for i in items] == ["SKU2", "SKU1"]
    assert items[0] == {
        "sku_id": "SKU2", "product_name": "Product 2", "current_stock": 0.0, "ss_i": 40.5,
        "short_by": 40.5, "target_stock": 120.0, "order_qty": 300.0, "revenue_share": 0.30,
    }
    assert items[1]["short_by"] == 40.0 and items[1]["order_qty"] is None


def test_policy_comparison_sums_lp_ss_against_three_week_rule():
    session = FakeSession(policy_rows=[
        {"planning_cycle_date": datetime.date(2024, 3, 1), "ss_i": 40.0, "rop_i": 120.0, "forecast_value": 100.0},
        {"planning_cycle_date": datetime.date(2024, 3, 1), "ss_i": 10.0, "rop_i": 30.0, "forecast_value": 50.0},
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


def test_policy_comparison_headline_is_target_stock_vs_rule():
    """rop_i is the LP's target stock since the 2026-09-30 run. SSM's 3 weeks
    is a target for ALL stock, so the headline compares the targets with it:
    comparing safety stock alone read "less" when the targets hold more."""
    session = FakeSession(policy_rows=[
        {"planning_cycle_date": datetime.date(2024, 3, 1), "ss_i": 40.0, "rop_i": 120.0, "forecast_value": 100.0},
        {"planning_cycle_date": datetime.date(2024, 3, 1), "ss_i": 10.0, "rop_i": 30.0, "forecast_value": 50.0},
    ])
    with make_client(session) as c:
        pc = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()["policy_comparison"]
    rule = 3 * 150.0 / AVG_WEEKS_PER_MONTH
    assert pc["lp_target_stock_units"] == pytest.approx(150.0)
    assert pc["rule_stock_units"] == pytest.approx(rule, rel=1e-4)
    # Targets above the rule read as MORE (negative), while ss alone reads less.
    assert pc["target_vs_rule_pct"] == pytest.approx(round((rule - 150.0) / rule * 100, 1))
    assert pc["target_vs_rule_pct"] < 0 < pc["lp_vs_rule_pct"]
    assert pc["lp_target_weeks"] == pytest.approx(round(150.0 / (150.0 / AVG_WEEKS_PER_MONTH), 2))
    assert pc["skus_above_rule"] == 1  # 120 > 3 weeks of 100; 30 < 3 weeks of 50
    assert pc["window_business_days"] == 8.0
    assert pc["inputs_are_placeholders"] is True


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
    assert pc["target_vs_rule_pct"] is None
    assert pc["lp_target_stock_units"] is None
    assert pc["blocked_reason"]


def test_reorder_preview_unknown_stock_is_no_data_not_critical():
    """Stock that can't be known (no count for the principal at this
    snapshot: in_stock_count is NULL) must stay 'NO DATA', never a
    fabricated CRITICAL from COALESCE(stock, 0)."""
    rows = [
        {**_reco_row(1, urgency_stock=None, rop_i=100), "in_stock_count": None},
        _reco_row(2, urgency_stock=0, rop_i=100),
    ]
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


def test_reorder_preview_product_absent_from_a_taken_count_reads_as_zero():
    """The stock file never lists zero rows, and the LP treats a product
    missing from the count as 0 on hand (scripts/run_lp.py). The preview
    must agree with the plan: 0 on hand, ranked like any other, and flagged
    so the page can say why (2026-10-01; it was 'NO DATA' before)."""
    rows = [{**_reco_row(1, urgency_stock=None, rop_i=100), "in_stock_count": False}]
    session = FakeSession(reco_preview_rows=rows)
    with make_client(session) as c:
        resp = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    preview = resp.json()["reorder_preview"]
    row = preview["rows"][0]
    assert row["current_stock"] == 0
    assert row["stock_not_in_count"] is True
    assert row["urgency"] == "CRITICAL"
    assert preview["critical_count"] == 1
    assert preview["no_data_count"] == 0


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
    36 are. The stock side is mart.inventory_mart's pieces (cases x pack size
    + loose, equal to backend/stock_units.STOCK_PIECES_EXPR on all 27,282 real
    Unilever product-counts, scripts/rehearse_marts.py)."""
    session = FakeSession(latest_abc_period="2024-02", latest_inventory_period="2024-02",
                          abc_rows=[_abc_row(1, "A", "2024-02", 0.3, current_stock=10, ss_i=50)])
    with make_client(session) as c:
        c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    sql, params = _sql_for(session, "FROM mart.inventory_mart_real")
    assert "SELECT product_key, pieces" in sql, "safety stock must compare the converted figure"
    assert params["period"] == "2024-02" and params["keys"] == [1]
    ss_sql, _ = _sql_for(session, "rop.ss_i AS ss_i")
    assert "quantity_on_hand" not in ss_sql, "never the raw case count: that is the bug this guards"


def test_every_lp_read_is_pinned_to_the_current_cycle():
    """Leftover `pending` rows from earlier runs (179 live, back to 2023-05)
    must not reach the page: they made the pending count read 429 not 250."""
    session = FakeSession(lp_cycle_date=datetime.date(2026, 3, 1), latest_abc_period="2024-02",
                          range_revenue={"unilever": {1: 100.0}})
    with make_client(session) as c:
        c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    for needle in ("COUNT(*) AS product_count",            # the KPI card
                   "rop.ss_i AS ss_i",                      # safety stock
                   "fr.forecast_date = lr.planning_cycle_date",  # policy comparison
                   "SELECT DISTINCT lr.product_key"):            # tier_stock
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
    # A plain rerun still leaves them; only --retire-stale-pending clears them.
    assert "plain rerun leaves them" in lp["reason"].lower()
    assert "--retire-stale-pending" in lp["reason"]

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


def test_stock_value_reads_the_marts_count_total():
    """The stock card is mart.inventory_count's total for the count: the
    source's own valuation first (it prices the loose-piece remainder;
    recomputing cases x cost under-counted 3.2% live), cases x unit cost only
    for rows without one — the rule migration 0041 applies, checked against
    inventory_fact by scripts/rehearse_marts.py and tests/test_marts.py."""
    session = FakeSession(latest_inventory_period="2024-02", soh={"2024-02": 22_700_825.83})
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    snapshot_reads = [s for s, _ in session.calls if "FROM mart.inventory_count" in s]
    assert len(snapshot_reads) == 1, "the month-level marts are read once per request"
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
    assert pf["insight"]["text"] == "The Mar 2024 forecast is 150 pieces — 25.0% above the 120 pieces sold in Feb 2024."
    assert pf["insight"]["forecast_period"] == "2024-03"


def test_forecast_block_reports_its_mase_gate():
    session = FakeSession(forecast_total=10, forecast_evaluated=8, forecast_unreliable=3)
    with make_client(session) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["forecast"]["mase_gate"] == 1.0


def test_tier_stock_period_names_the_count_at_the_ranges_end():
    session = FakeSession(latest_inventory_period="2024-03", range_revenue={"unilever": {1: 10.0}},
                          stock_status={1: (True, False)})
    body = _get(session, "principal=unilever&period=2024-03")
    assert body["tier_stock_period"] == "2024-03"
    body = _get(session, "principal=unilever&period=2024-02")
    assert body["tier_stock_period"] is None, "no count on or before Feb 2024"


# ---- stock on hand under 'all', and the reorder card's order (2026-09-29) ---

class _PeriodSumSession:
    """Answers the month-level snapshot with each principal's own stock counts
    (mart.inventory_count): under 'all' a month gets a figure only when both
    principals have one, never the sum of whatever rows existed."""

    def __init__(self, by_principal):
        self.by_principal = by_principal

    def execute(self, stmt, params=None):
        assert "'sales' AS src" in str(stmt)
        return FakeResult([
            {"src": "stock", "principal": who, "period": p, "data_kind": "real", "pesos": v, "pieces": None,
             "first_date": None, "last_date": None, "products": 1}
            for who, by_month in self.by_principal.items() for p, v in by_month.items()
        ])


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
    assert a["vat_basis"] == "selling price, VAT-inclusive"
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
        "ytd_months", "prior_ytd_sales", "prior_ytd_months", "latest_sales", "trend",
        "levels", "vat_basis", "blocked_reason",
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
    assert a["prior_ytd_months"] == 0 and a["prior_ytd_sales"] is None
    assert a["unit"] == "pesos" and a["default_pct"] == 103
    assert [level["pct"] for level in a["levels"]] == [103, 105, 108]
    assert a["levels"][0]["monthly"] == pytest.approx(12_000.0 * 1.03 / 12)


@pytest.mark.parametrize("query", [
    "",                                         # the default range
    "&start_period=2025-01&period=2025-06",     # a range ending mid-year
    "&start_period=2023-01&period=2025-12",     # a three-year range
])
def test_allocation_does_not_follow_the_date_range(query):
    """Since 2026-10-09 (reversing 0a0756f) the allocation is the year being
    planned, with ONE previous year as its basis, whatever the range: 2026's
    allocation from 2025's sales, 2026's sales so far (Jan-Feb), and the same
    months of 2025 for the year-over-year."""
    sales = {
        **{f"2023-{m:02d}": 90.0 for m in range(1, 13)},
        **{f"2024-{m:02d}": 100.0 for m in range(1, 13)},
        **{f"2025-{m:02d}": 110.0 for m in range(1, 13)},
        "2026-01": 120.0, "2026-02": 130.0,
    }
    session = FakeSession(latest_sales_period="2026-02", sales=sales)
    with make_client(session) as c:
        a = c.get(
            f"/dashboard?principal=unilever{query}",
            headers={"Authorization": f"Bearer {user_token()}"},
        ).json()["allocation"]
    assert a["blocked_reason"] is None
    assert (a["allocation_year"], a["basis_year"], a["latest_month"]) == (2026, 2025, "2026-02")
    assert a["basis_sales"] == pytest.approx(1_320.0) and a["basis_months"] == 12
    assert a["ytd_months"] == 2 and a["ytd_sales"] == pytest.approx(250.0)
    assert a["prior_ytd_months"] == 2 and a["prior_ytd_sales"] == pytest.approx(220.0)
    # The latest month is the latest with sales, not the range's last month,
    # with the 12 months up to it (Mar 2025 - Feb 2026).
    assert a["latest_sales"] == pytest.approx(130.0)
    assert [p["period"] for p in a["trend"]["points"]][0] == "2025-03"
    assert a["trend"]["prev_period"] == "2026-01"


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


# ---- LP figures follow lp.view (Yuan's permissions proposal, 2026-09-30) ----

def _lp_rich_session():
    return FakeSession(
        recommendation_count=5,
        reco_preview_rows=[_reco_row(1, urgency_stock=0, rop_i=100)],
        policy_rows=[{"planning_cycle_date": datetime.date(2024, 3, 1), "ss_i": 40.0, "rop_i": 120.0, "forecast_value": 100.0}],
        latest_abc_period="2024-02",
        abc_rows=[_abc_row(1, "A", "2024-02", 0.30, current_stock=10, ss_i=50)],
        range_revenue={"unilever": {1: 80.0, 2: 15.0, 3: 5.0}},  # 1 is class A (running share 80%)
        stock_status={1: (True, False)},
        pending_keys={1},
    )


def test_lp_figures_are_there_for_a_user_with_lp_view():
    with make_client(_lp_rich_session()) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["lp_hidden"] is False
    assert body["reorder_preview"]["critical_count"] == 1
    assert body["policy_comparison"]["sku_count"] == 1
    assert body["safety_stock_exposure"]["below_count"] == 1
    assert body["recommendations"]["product_count"] == 5
    assert body["tier_stock"][0]["pending_reorder_count"] == 1


def test_lp_figures_are_left_out_for_a_user_without_lp_view(monkeypatch):
    """Server-side, not just a hidden tab: the numbers never reach the
    browser. Everything not derived from LP_Recommendation stays."""
    from backend import permissions
    from backend.routers.dashboard import LP_HIDDEN_REASON

    monkeypatch.setattr(permissions, "load_overrides", lambda db, user_id: {"lp.view": False})
    with make_client(_lp_rich_session()) as c:
        body = c.get("/dashboard?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["lp_hidden"] is True
    for key in ("reorder_preview", "policy_comparison", "lp", "safety_stock_exposure"):
        assert body[key] is None, key
    assert body["recommendations"] == {"order_value": None, "product_count": None}
    assert body["kpis"]["safety_stock_rate"] is None
    assert body["kpis"]["safety_stock_rate_blocked_reason"] == LP_HIDDEN_REASON
    assert body["tier_stock"][0] == {
        "tier": "A", "in_stock": 1, "dead_stock": 0, "no_data": 0, "pending_reorder_count": None}
    assert body["abc_mix"] and body["forecast"]["total_count"] == 0


# ---- display fixes (2026-10-01) ------------------------------------------

def _get(session, query):
    with make_client(session) as c:
        resp = c.get(f"/dashboard?{query}", headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_stock_card_compares_with_the_last_count_not_flagged_as_unusual():
    """Unilever's Feb 2026 count (₱46.6M, about twice Jan and Mar) is in the
    reviewed registry (backend/data_notes.py). The card read "↓51.3% vs Feb
    2026"; it now compares Mar 2026 with Jan 2026 and says it skipped Feb.
    The point itself stays — on the sparkline and on the chart, flagged."""
    session = FakeSession(
        latest_sales_period="2026-02",
        sales={"2026-01": 37_165_964.39, "2026-02": 27_914_343.91},
        latest_inventory_period="2026-03",
        soh={"2026-01": 24_339_386.24, "2026-02": 46_576_778.51, "2026-03": 22_700_825.83},
    )
    # The stock card reads the count at the range's end, so the range ends
    # Mar 2026 to put the Mar 2026 count on it.
    body = _get(session, "principal=unilever&period=2026-03&start_period=2025-04")
    trend = body["kpis"]["soh_trend"]
    assert trend["latest_period"] == "2026-03"
    assert trend["prev_period"] == "2026-01"
    assert trend["delta_pct"] == pytest.approx(-6.7)
    assert trend["months_apart"] == 2
    assert [s["period"] for s in trend["skipped"]] == ["2026-02"]
    assert "accepted for planning, pending SSM confirmation" in trend["skipped"][0]["reason"]
    assert "2026-02" in [pt["period"] for pt in trend["points"]], "the count is kept, only not compared against"

    flags = body["stock_on_hand_flags"]
    assert [f["period"] for f in flags] == ["2026-02"]
    assert "₱46.6M" in flags[0]["reason"]
    svs = {pt["period"]: pt for pt in body["sales_vs_stock"]}
    assert svs["2026-02"]["stock_on_hand"] == pytest.approx(46_576_778.51)

    text = body["sales_vs_stock_insight"]["text"]
    assert "stood at ₱22.7M in Mar 2026" in text
    assert "₱46.6M" not in text

    # A range ending Feb 2026 puts the flagged count itself at the range's
    # end: the sentence passes over it to the last ordinary count and says so.
    text = _get(session, "principal=unilever&period=2026-02&start_period=2025-03")["sales_vs_stock_insight"]["text"]
    assert "stood at ₱24.3M in Jan 2026" in text
    assert "₱46.6M" not in text
    assert "Feb 2026's count needs checking" in text


def test_kpi_trend_gives_no_delta_from_an_unusual_latest_month():
    from backend.chart_insights import kpi_trend

    t = kpi_trend({"2026-01": 24.3, "2026-02": 46.6}, "2026-02", unusual={"2026-02": "outlier"})
    assert t["delta_pct"] is None and t["prev_period"] is None
    assert t["latest_unusual"] == "outlier"
    # Without flags, the walk-back is exactly what it was.
    t = kpi_trend({"2026-01": 24.3, "2026-02": 46.6}, "2026-02")
    assert t["prev_period"] == "2026-01" and t["skipped"] == [] and t["latest_unusual"] is None


def test_all_principals_point_carries_a_contributors_unusual_count():
    """Under 'all' a month is the sum of both principals' counts, so Del
    Monte's Ilocos-only Feb 2023 count makes the combined point unusual too,
    and the reason says whose count it is."""
    session = FakeSession(soh={"2023-01": 30_000_000.0, "2023-02": 26_000_000.0, "2023-03": 31_000_000.0},
                          stock_coverage=["delmonte", "unilever"])  # both principals counted each month
    body = _get(session, "period=2023-03&start_period=2023-01")
    flags = body["stock_on_hand_flags"]
    assert [f["period"] for f in flags] == ["2023-02"]
    assert flags[0]["reason"].startswith("Del Monte: Ilocos warehouse only")
    # Unilever's own view of the same month has nothing to flag.
    unilever = _get(FakeSession(soh={"2023-02": 23_000_000.0}), "principal=unilever&period=2023-03&start_period=2023-01")
    assert unilever["stock_on_hand_flags"] == []


def test_del_monte_purchases_are_plotted_ex_vat_like_its_sales():
    """Purchase_Fact.net_amount includes VAT (tax is 12/112 of it); Del
    Monte's sell-out is ex-VAT. Dec 2025 read ₱23.0M of purchases against
    ₱22.1M of sales; ex-VAT it is ₱20.5M."""
    session = FakeSession(
        latest_sales_period=None,
        received={"2025-12": 23_006_527.51},
        received_tax={"2025-12": 2_464_985.05},
    )
    session.delmonte_latest_sales_period = "2025-12"
    session.delmonte_sales = {"2025-12": 22_134_295.57}
    body = _get(session, "principal=delmonte&period=2025-12&start_period=2025-01")
    dec = next(pt for pt in body["sales_vs_stock"] if pt["period"] == "2025-12")
    assert dec["received"] == pytest.approx(20_541_542.46)
    assert body["sales_vs_stock_basis"] == {"sales": "selling price, ex-VAT", "received": "ex-VAT",
                                            "stock_on_hand": "at last purchase price",
                                            "returns": "Net Amount as recorded in the returns file"}
    # The ex-VAT rule is mart.flow_month's (migration 0041, checked against
    # purchase_fact by scripts/rehearse_marts.py): the page plots that flow as is.


def test_unilever_purchases_stay_on_its_vat_inclusive_sales_basis():
    current = _periods()[-1]
    session = FakeSession(received={current: 700.0}, received_tax={current: 75.0})
    body = _get(session, "principal=unilever")
    assert body["sales_vs_stock"][-1]["received"] == 700.0
    assert body["sales_vs_stock_basis"] == {"sales": "selling price, VAT-inclusive", "received": "incl. VAT",
                                            "stock_on_hand": "at last purchase price",
                                            "returns": "Net Amount as recorded in the returns file"}
    # Under 'all' the pesos mix the two bases; vat_note says so instead.
    basis = _get(FakeSession(), "principal=all")["sales_vs_stock_basis"]
    assert (basis["sales"], basis["received"]) == (None, None)


def test_allocation_monthly_is_an_average_basis_month_when_the_basis_is_partial():
    """Del Monte's 2024 basis holds two months (₱21.3M). basis x pct / 12
    drew a ₱1.86M/month allocation beside ~₱10.8M/month of sales; an
    average basis month x pct is ₱11.2M. No annual figure on a partial
    basis — that would be an extrapolation presented as the rule's year."""
    # The basis is the calendar year before the PLANNING month (analytics/
    # allocation.py, 2026-09-30): data through 2025-11 plans 2025-12, so
    # 2024 is the basis. (Through 2025-12 would plan 2026-01, basis 2025.)
    session = FakeSession(latest_sales_period=None)
    session.delmonte_latest_sales_period = "2025-11"
    session.delmonte_sales = {"2024-01": 10_000_000.0, "2024-02": 11_313_205.91, "2025-11": 22_134_295.57}
    a = _get(session, "principal=delmonte&period=2025-11")["allocation"]
    assert a["basis_months"] == 2
    mid = next(level for level in a["levels"] if level["pct"] == 105)
    assert mid["monthly"] == pytest.approx(21_313_205.91 * 1.05 / 2, abs=0.01)
    assert mid["annual"] is None


def test_abc_class_shares_and_revenue_come_from_the_products_own_revenue():
    """Class revenue and share are sums of the products' own unrounded range
    revenue, never of 4-dp stored shares (which drifted: 14.93% for 14.99%)."""
    revenue = {1: 7_999.60, 2: 499.95, 3: 499.95, 4: 499.95, 5: 500.55}
    session = FakeSession(range_revenue={"unilever": revenue}, sales={_periods()[-1]: 9_950.0})
    body = _get(session, "principal=unilever")
    mix = {m["tier"]: m for m in body["abc_mix"]}
    assert mix["A"]["revenue"] == pytest.approx(7_999.60)
    # Running shares: 0.79996 (1, A), 0.850015 (5, B), 0.90001 (2, B),
    # 0.950005 (3, just past the B cutoff: C) — B is 5 + 2 = 10.005%.
    assert mix["B"]["revenue"] == pytest.approx(1_000.50)
    assert mix["B"]["revenue_share_pct"] == pytest.approx(10.005, abs=0.005)
    assert body["abc_revenue"]["total"] == pytest.approx(9_950.0)
    assert body["abc_revenue"]["ranked_total"] == pytest.approx(10_000.0)


@pytest.fixture
def real_rows_only(monkeypatch):
    """marts.COUNT_FILLED_AND_GENERATED off: the rule before 2026-10-11, kept
    tested so it can be switched back on a decision."""
    monkeypatch.setattr(marts, "COUNT_FILLED_AND_GENERATED", False)


def test_complete_months_switch_is_off_since_the_demo_rule():
    """The 2026-10-11 COMPLETE MONTHS switch (a month with no file showed its
    filled or generated figure as sales) is off since 2026-10-15: those sales
    rows are retired for display and schema demo is the only display source for
    generated data (CLAUDE.md hard rule 2, docs/DEMO_DATA.md). A month with no
    real sales is a gap again, and nothing is marked synthetic."""
    assert marts.COUNT_FILLED_AND_GENERATED is False
    periods = _periods()
    session = FakeSession(
        sales={periods[-1]: 500.0},
        estimated_sales={"unilever": {periods[-2]: ("generated", 450.0), periods[-1]: ("filled", 999.0)}},
    )
    body = _get(session, "principal=unilever")
    pts = {pt["period"]: pt for pt in body["sales_vs_stock"]}
    assert pts[periods[-2]]["sales"] is None
    assert pts[periods[-1]]["sales"] == 500.0 and pts[periods[-1]]["provenance"]["sales"] == "real"
    total = body["kpis"]["sales_cumulative"]
    assert total["value"] == 500.0 and total["months_with_data"] == 1
    assert total["synthetic_months"] == []

    sql, _ = _sql_for(session, "WITH rev AS")
    assert "'filled', 'generated'" not in sql
    assert marts._kinds("real", {"data_kind": "generated", "period": "2026-02"}, "2026-02") is False


def test_abc_ranking_reads_real_rows_only(real_rows_only):
    """KPIs, the Pareto and accuracy read data_kind = 'real' (preview adds
    Unilever's placeholder months): a filled or generated row never ranks."""
    session = FakeSession(range_revenue={"unilever": {1: 10.0}})
    _get(session, "principal=unilever")
    sql, _ = _sql_for(session, "WITH rev AS")
    assert "s.data_kind = 'real'" in sql and "generated" not in sql and "filled" not in sql


# ---- the selected range and the marts (migration 0041, 2026-10-04) ---------

def test_sales_card_gives_the_ranges_total_and_its_end_month():
    """Every card answers for the selected range: the range's total over its
    months with real sales, beside the end month's snapshot, each labelled."""
    periods = _periods()
    session = FakeSession(sales={periods[0]: 100.0, periods[5]: 250.0, periods[-1]: 400.0},
                          sales_pieces={periods[0]: 10.0, periods[5]: 25.0, periods[-1]: 40.0})
    kpis = _get(session, "principal=unilever")["kpis"]
    cum, snap = kpis["sales_cumulative"], kpis["sales_snapshot"]
    assert cum["value"] == pytest.approx(750.0)
    assert cum["pieces"] == pytest.approx(75.0)
    assert (cum["start_period"], cum["end_period"]) == (periods[0], periods[-1])
    assert (cum["months_in_range"], cum["months_with_data"]) == (12, 3)
    assert len(cum["missing_months"]) == 9
    assert cum["label"] == "Mar 2023 – Feb 2024"
    assert (snap["value"], snap["period"], snap["label"]) == (400.0, periods[-1], "Feb 2024")
    assert snap["value"] == kpis["sales"] and snap["period"] == kpis["sales_period"]


def test_sales_range_total_has_no_pieces_for_del_monte():
    """Del Monte's sell-out quantity unit is unconfirmed: pesos only."""
    session = FakeSession(latest_sales_period=None)
    session.delmonte_latest_sales_period = "2025-12"
    session.delmonte_sales = {"2025-12": 22_134_295.57}
    cum = _get(session, "principal=delmonte")["kpis"]["sales_cumulative"]
    assert cum["value"] == pytest.approx(22_134_295.57)
    assert cum["pieces"] is None


def test_filled_and_generated_sales_and_stock_are_retired_for_display():
    """2026-10-15: the filled (synthetic_category_split, synthetic_v2_gap) and generated (synthetic_v2) SALES rows are
    no longer served; schema demo is the single display source for generated data. 2026-10-16 (rule 2, B1): stock
    fills followed - every filled/generated inventory_mart row is the retired is_demo family, so
    marts.estimated_stock_by_period returns {} and no stock estimate is drawn either."""
    periods = _periods()
    session = FakeSession(
        sales={periods[-1]: 500.0},
        estimated_sales={"unilever": {periods[-2]: ("filled", 450.0), periods[-1]: ("filled", 999.0),
                                      periods[-3]: ("generated", 777.0)}},
        estimated_stock={"unilever": {periods[-2]: ("filled", 1_000.0)}},
    )
    body = _get(session, "principal=unilever")
    pts = {pt["period"]: pt for pt in body["sales_vs_stock"]}
    gap, real = pts[periods[-2]], pts[periods[-1]]
    assert gap["sales"] is None and gap["sales_estimated"] is None and gap["sales_estimated_kind"] is None
    assert gap["provenance"]["sales_estimated"] is None
    assert gap["stock_on_hand"] is None and gap["stock_on_hand_estimated"] is None
    assert real["sales"] == 500.0 and real["sales_estimated"] is None
    assert body["kpis"]["sales_cumulative"]["value"] == 500.0, "an estimate never reaches a KPI"
    assert pts[periods[-3]]["sales_estimated"] is None, "generated rows are never drawn either"


def test_sales_estimates_under_all_are_retired_too():
    """A fill under 'all' no longer adds a sales estimate for either principal (retired 2026-10-15)."""
    periods = _periods()
    session = FakeSession(sales={periods[-1]: 100.0, periods[-2]: 100.0},
                          estimated_sales={"delmonte": {periods[-1]: ("filled", 30.0)}})
    session.delmonte_latest_sales_period = periods[-3]
    session.delmonte_sales = {periods[-3]: 50.0}
    pts = {pt["period"]: pt for pt in _get(session, "")["sales_vs_stock"]}
    assert pts[periods[-1]]["sales"] is None
    assert pts[periods[-1]]["sales_estimated"] is None
    assert pts[periods[-2]]["sales_estimated"] is None


def test_unilevers_rate_filled_returns_are_never_drawn():
    """Coverage hole H4 used to be closed by drawing Unilever's rate-filled returns as an estimate.
    Retired 2026-10-16 (rule 2, B1): Unilever has no real returns at all, so that line was 100%
    synthetic; marts.flow_by_period never estimates returns, real mode or preview."""
    current = _periods()[-1]
    session = FakeSession(returns={"unilever": {current: ("filled", 912_323.85, "synthetic_rate_transfer")}})
    pt = _get(session, "principal=unilever")["sales_vs_stock"][-1]
    assert pt["returns"] is None
    assert pt["returns_estimated"] is None
    assert pt["returns_estimated_kind"] is None


def _accuracy_row(key, month, forecast, actual, run_length=1, price=10.0, limited=False, label="run"):
    miss = forecast - actual
    return {"run_id": 2, "forecast_source": "backtest_recreated", "run_label": label, "cohort": None,
            "principal": "unilever", "product_key": key, "sku_code": f"SKU{key}", "product_name": f"P{key}",
            "category_path": "CAT", "month": month, "forecast_pieces": forecast, "actual_pieces": actual,
            "ma3_pieces": forecast, "miss_pieces": miss, "abs_miss_pieces": abs(miss),
            "direction": "over" if miss > 0 else "under" if miss < 0 else "exact", "run_length": run_length,
            "price_per_piece": price, "possibly_stock_limited": limited}


def test_error_card_signed_miss_in_pieces_and_pesos_with_review_list():
    rows = [
        _accuracy_row(1, "2024-01", 120, 100, run_length=2),
        _accuracy_row(1, "2024-02", 130, 100, run_length=3, limited=True),   # 3rd over in a row: review
        _accuracy_row(2, "2024-01", 80, 100),
        _accuracy_row(2, "2024-02", 90, 100, price=None),                    # no price: pieces only
    ]
    acc = _get(FakeSession(accuracy_rows=rows), "principal=unilever")["forecast_accuracy"]
    assert acc["forecast_source"] == "backtest_recreated"
    assert (acc["products"], acc["product_months"]) == (2, 4)
    assert acc["net_miss_pieces"] == pytest.approx(20.0)        # 20 + 30 - 20 - 10
    assert acc["abs_miss_pieces"] == pytest.approx(80.0)
    assert acc["surplus_pesos"] == pytest.approx(500.0)         # (20 + 30) x 10
    assert acc["shortage_pesos"] == pytest.approx(200.0)        # 20 x 10; the unpriced miss stays in pieces
    assert acc["direction"] == "over"
    assert [(m["period"], m["direction"]) for m in acc["by_month"]] == [("2024-01", "exact"), ("2024-02", "over")]
    runs = acc["over_forecast_runs"]
    assert runs["run_months"] == 3 and "DEC-33" in runs["rule"]
    assert [it["product_key"] for it in runs["items"]] == [1]
    assert runs["items"][0]["possibly_stock_limited"] is True
    assert acc["possibly_stock_limited"] == 1
    assert acc["products_without_price"] == 0, "product 2 has a price in another month"


def test_error_card_says_why_del_monte_has_none():
    acc = _get(FakeSession(), "principal=delmonte")["forecast_accuracy"]
    assert acc["products"] == 0 and "category grain" in acc["blocked_reason"]


def test_safety_stock_is_not_judged_on_a_count_before_the_plans_opening_count():
    """The only plan in force is cycle 2026-03 (opening count 2026-02); a
    range ending 2025-06 reads the 2025-06 count, which that plan's safety
    stock is not compared with."""
    session = FakeSession(
        lp_cycle_date=datetime.date(2026, 3, 1), latest_abc_period="2025-06",
        abc_rows=[_abc_row(1, "A", "2025-06", 0.3, current_stock=10, ss_i=50)],
        latest_inventory_period="2025-06",
    )
    body = _get(session, "principal=unilever&period=2025-06")
    exp = body["safety_stock_exposure"]
    assert exp["below_count"] is None and exp["comparable_count"] == 0
    assert "Feb 2026" in exp["blocked_reason"] and exp["plan_opening_period"] == "2026-02"
    assert body["kpis"]["safety_stock_rate"] is None


def test_below_safety_stock_list_is_the_rows_behind_the_count():
    """Audrey's below_items: the products the count was taken from, most
    revenue first, pieces throughout."""
    rows = [_abc_row(1, "A", "2024-02", 0.10, current_stock=10, ss_i=50),
            _abc_row(2, "A", "2024-02", 0.30, current_stock=5, ss_i=20),
            _abc_row(3, "A", "2024-02", 0.20, current_stock=90, ss_i=50)]
    exp = _get(FakeSession(latest_abc_period="2024-02", abc_rows=rows), "principal=unilever")["safety_stock_exposure"]
    assert exp["below_count"] == 2
    assert [(i["sku_id"], i["short_by"]) for i in exp["below_items"]] == [("SKU2", 15.0), ("SKU1", 40.0)]
    assert exp["tier_a_period"] == "2024-02"
    assert exp["tier_a_periods"] == {"Unilever": "2024-02"}  # the per-principal view; tier_a_period is unchanged


def test_idle_stock_is_unilever_only_and_says_so_for_del_monte():
    body = _get(FakeSession(), "principal=delmonte")
    assert body["idle_stock"]["products"] == 0
    assert "category" in body["idle_stock"]["blocked_reason"]
    assert body["idle_stock"]["window_rule_months"] == 6


def test_payload_says_when_the_marts_were_refreshed():
    body = _get(FakeSession(), "principal=unilever")
    assert body["marts"]["present"] is False


def test_a_flagged_count_without_a_ruling_gives_its_reviewed_reason():
    from backend.data_notes import UNUSUAL_STOCK_SNAPSHOTS, flagged_count_note

    note = flagged_count_note("delmonte", "2023-02", 2_500_000.0, [8_700_000.0], None)
    assert note == ("Counted for Feb 2023 (exact date not recorded): "
                    + UNUSUAL_STOCK_SNAPSHOTS[("delmonte", "2023-02")])
    assert flagged_count_note("unilever", "2026-01", 24_339_386.24, [46_576_778.51], "2026-02-03") is None


# ---- stock count dates (2026-10-02) -------------------------------------------
# The Technical Adviser's rule: every number states its period. A stock
# snapshot's _period is not the day it was counted — Unilever's "2026-03" is
# the 2026-04-06 count — so GET /dashboard exposes the count day, read-only.

def test_insight_sentence_names_inventory_at_cost_and_its_count_day():
    from backend.chart_insights import sales_vs_stock_insight

    series = [
        {"period": "2026-01", "sales": 30_000_000.0, "stock_on_hand": 24_339_386.24, "stock_count_date": "2026-02-03"},
        {"period": "2026-02", "sales": 27_900_000.0, "stock_on_hand": None, "stock_count_date": None},
    ]
    text = sales_vs_stock_insight(series)["text"]
    assert "inventory at last purchase price stood at ₱24.3M in Jan 2026 (counted Feb 3, 2026)" in text
    # Without a count day the month alone is stated, never a raw string.
    series[0]["stock_count_date"] = None
    text = sales_vs_stock_insight(series)["text"]
    assert "stood at ₱24.3M in Jan 2026." in text and "counted" not in text


def test_day_label():
    from backend.chart_insights import day_label

    assert day_label("2026-04-06") == "Apr 6, 2026"
    assert day_label(None) is None
    assert day_label("not a date") is None


# ---- annual_sales (2026-10-12): the Annual View card's bars ---------------------
# One bar per calendar year = the sum of that year's months, from the same
# per-month sales every other peso figure on the page reads.

def test_annual_sales_totals_each_year_and_agrees_with_the_allocation_card():
    sales = {f"2025-{m:02d}": 100.0 for m in range(1, 13)}
    sales.update({f"2024-{m:02d}": 50.0 for m in (3, 4, 5)})
    sales.update({"2026-01": 110.0, "2026-02": 120.0})
    body = _get(FakeSession(latest_sales_period="2026-02", sales=sales), "principal=unilever")
    annual = body["annual_sales"]
    assert annual["blocked_reason"] is None and annual["window_years"] == 5
    years = {y["year"]: y for y in annual["years"]}
    assert list(years) == [2022, 2023, 2024, 2025, 2026]
    # A year with nothing on record is null with 0 months, never 0 pesos.
    assert years[2022]["sales"] is None and years[2022]["months"] == 0
    assert years[2022]["first_month"] is None and years[2022]["synthetic_months"] == []
    # A part year is the sum of the months it has: no scaling up to 12.
    assert years[2024]["sales"] == pytest.approx(150.0) and years[2024]["months"] == 3
    assert (years[2024]["first_month"], years[2024]["last_month"]) == ("2024-03", "2024-05")
    assert years[2026]["sales"] == pytest.approx(230.0) and years[2026]["months"] == 2
    assert (years[2026]["first_month"], years[2026]["last_month"]) == ("2026-01", "2026-02")
    # The bars and the allocation card are the same sums.
    assert years[2025]["sales"] == body["allocation"]["basis_sales"] == pytest.approx(1200.0)
    assert years[2026]["sales"] == body["allocation"]["ytd_sales"]
    assert annual["earlier_years"] == []


@pytest.mark.parametrize("query", ["principal=unilever", "principal=unilever&start_period=2025-06&period=2025-09"])
def test_annual_sales_does_not_follow_the_date_range(query):
    sales = {f"2025-{m:02d}": 100.0 for m in range(1, 13)}
    sales.update({"2026-01": 110.0})
    annual = _get(FakeSession(latest_sales_period="2026-01", sales=sales), query)["annual_sales"]
    assert [(y["year"], y["sales"], y["months"]) for y in annual["years"][-2:]] == [(2025, 1200.0, 12), (2026, 110.0, 1)]


def test_annual_sales_counts_real_months_only_since_the_demo_rule():
    """Since 2026-10-15 the filled and generated sales rows are retired for
    display (marts.COUNT_FILLED_AND_GENERATED off): a year is the sum of its
    real months, and a year with only generated rows has no sales, not a
    synthetic total."""
    sales = {f"2025-{m:02d}": 100.0 for m in range(1, 11)}
    generated = {f"2020-{m:02d}": ("generated", 10.0) for m in range(1, 13)}
    generated.update({"2025-11": ("generated", 40.0), "2025-12": ("filled", 60.0),
                      "2026-01": ("generated", 999.0), "2025-03": ("generated", 999.0)})
    session = FakeSession(latest_sales_period="2025-10", sales=sales, estimated_sales={"unilever": generated})
    annual = _get(session, "principal=unilever")["annual_sales"]
    years = {y["year"]: y for y in annual["years"]}
    # The window ends at the last year with a real month (2025).
    assert list(years) == [2021, 2022, 2023, 2024, 2025]
    assert years[2025]["sales"] == pytest.approx(1000.0)
    assert years[2025]["months"] == 10 and years[2025]["synthetic_months"] == []
    # 2020 has generated rows only: no sales, so not an earlier year with sales either.
    assert years[2021]["sales"] is None and annual["earlier_years"] == []


def test_annual_sales_leaves_retired_fills_inside_real_history_out():
    sales = {"2025-01": 100.0, "2025-04": 100.0}
    generated = {"2025-02": ("generated", 40.0), "2025-03": ("filled", 60.0)}
    session = FakeSession(latest_sales_period="2025-04", sales=sales, estimated_sales={"unilever": generated})
    year = _get(session, "principal=unilever")["annual_sales"]["years"][-1]
    # Two real months, and "2 of 12 months" on the card: the gap is shown, not filled.
    assert year["year"] == 2025 and year["sales"] == pytest.approx(200.0) and year["months"] == 2
    assert year["synthetic_months"] == []


def test_annual_sales_real_rows_only(real_rows_only):
    sales = {"2025-01": 100.0, "2025-04": 100.0}
    generated = {"2025-02": ("generated", 40.0), "2025-03": ("filled", 60.0)}
    session = FakeSession(latest_sales_period="2025-04", sales=sales, estimated_sales={"unilever": generated})
    year = _get(session, "principal=unilever")["annual_sales"]["years"][-1]
    assert year["sales"] == pytest.approx(200.0) and year["months"] == 2 and year["synthetic_months"] == []


def test_annual_sales_under_all_needs_both_principals_in_a_month():
    """_combine_principal_sums: a month one principal has no figure for is not
    summed as if it were the whole portfolio, so the year says fewer months."""
    session = FakeSession(latest_sales_period="2025-03", sales={"2025-01": 100.0, "2025-02": 100.0, "2025-03": 100.0})
    session.delmonte_latest_sales_period = "2025-02"
    session.delmonte_sales = {"2025-01": 10.0, "2025-02": 20.0}
    year = _get(session, "principal=all")["annual_sales"]["years"][-1]
    assert year["year"] == 2025 and year["sales"] == pytest.approx(230.0) and year["months"] == 2
    assert (year["first_month"], year["last_month"]) == ("2025-01", "2025-02")


def test_annual_sales_is_blocked_with_a_reason_when_there_are_no_sales():
    annual = _get(FakeSession(latest_sales_period=None), "principal=unilever")["annual_sales"]
    assert annual["years"] == [] and "No " in annual["blocked_reason"]
