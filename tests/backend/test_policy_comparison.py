"""
tests/backend/test_policy_comparison.py — GET /policy-comparison (backend/routers/policy_comparison.py).

FakeSession pattern from tests/backend/test_segment.py — never touches
Supabase. Covers the per-SKU rule-vs-LP arithmetic, the roll-up (which must
equal GET /dashboard's policy_comparison), ordering, the honest nulls for
the peso and stockout fields, and the blocked answer when nothing compares.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.routers.dashboard import AVG_WEEKS_PER_MONTH


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
    def __init__(self, rows, cycle=None):
        self.rows = rows
        self.last_params = None
        # The LP's current planning cycle (backend/lp_cycle.py). The router
        # resolves it under the request's own scope instead of the unscoped
        # MAX() subquery it used to inline, so the fake has to answer it.
        self.cycle = cycle if cycle is not None else datetime.date(2026, 3, 1)

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "MAX(lr.planning_cycle_date) AS d" in sql:
            return FakeResult([{"d": self.cycle}])
        self.last_params = params or {}
        if "FROM LP_Recommendation lr" in sql and "fr.forecast_date = lr.planning_cycle_date" in sql:
            self.last_sql = sql
            return FakeResult(self.rows)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


CYCLE = datetime.date(2026, 3, 1)
ROWS = [
    # rop_i is the LP's target stock since the 2026-09-30 run. A1's target
    # sits ABOVE its 3 weeks (volatile SKU), B2's well below it.
    {"planning_cycle_date": CYCLE, "ss_i": 40.0, "rop_i": 120.0, "forecast_value": 100.0, "sku_id": "A1", "product_name": "ABOVE RULE", "principal": "unilever"},
    {"planning_cycle_date": CYCLE, "ss_i": 10.0, "rop_i": 60.0, "forecast_value": 500.0, "sku_id": "B2", "product_name": "BIG GAP", "principal": "unilever"},
    {"planning_cycle_date": CYCLE, "ss_i": None, "rop_i": 50.0, "forecast_value": 80.0, "sku_id": "C3", "product_name": "NO SS", "principal": "unilever"},
]


def make_client(session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_requires_auth():
    app.dependency_overrides[get_db] = lambda: FakeSession(ROWS)
    with TestClient(app) as c:
        assert c.get("/policy-comparison").status_code == 401


def test_per_sku_rule_vs_lp_and_rollup():
    with make_client(FakeSession(ROWS)) as c:
        body = c.get("/policy-comparison?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["cycle_date"] == "2026-03-01"
    assert body["rule_weeks"] == 3
    # The row with no ss_i is dropped from BOTH sides, never one.
    assert [i["sku_id"] for i in body["items"]] == ["B2", "A1"]  # biggest gap first
    big = body["items"][0]
    assert big["rule_stock_units"] == pytest.approx(3 * 500.0 / AVG_WEEKS_PER_MONTH, rel=1e-4)
    assert big["rule_safety_stock_units"] == big["rule_stock_units"]  # old name kept
    assert big["lp_target_stock_units"] == pytest.approx(60.0)
    # The gap is target vs rule — the like-for-like pair — not ss vs rule.
    assert big["difference_units"] == pytest.approx(3 * 500.0 / AVG_WEEKS_PER_MONTH - 60.0, rel=1e-4)
    rule_total = 3 * 600.0 / AVG_WEEKS_PER_MONTH
    pf = body["portfolio"]
    assert pf["sku_count"] == 2
    assert pf["lp_target_stock_units"] == pytest.approx(180.0)
    assert pf["lp_safety_stock_units"] == pytest.approx(50.0)
    assert pf["rule_stock_units"] == pytest.approx(rule_total, rel=1e-4)
    assert pf["target_vs_rule_pct"] == pytest.approx(round((rule_total - 180.0) / rule_total * 100, 1))
    assert "lp_vs_rule_pct" not in pf
    # A1's target is above its 3 weeks, so only B2 holds less.
    assert pf["skus_lp_holds_less"] == 1


def test_money_and_stockout_fields_are_null_with_reason():
    with make_client(FakeSession(ROWS)) as c:
        body = c.get("/policy-comparison", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["working_capital"] is None
    assert body["capital_freed"] is None
    assert body["est_stockout_rate"] is None
    assert "pesos" in body["valuation_blocked_reason"]


def test_principal_scope_is_bound_not_interpolated():
    session = FakeSession(ROWS)
    with make_client(session) as c:
        c.get("/policy-comparison?principal=delmonte", headers={"Authorization": f"Bearer {user_token()}"})
    # The scope reaches SQL as a BIND, never as a literal. Asserted on the
    # bind itself plus the query text rather than on the whole params dict,
    # which also carries the LP cycle bind since 2026-09-23.
    assert session.last_params["principal"] == "delmonte"
    assert "delmonte" not in session.last_sql
    # The cycle is bound too, for the same reason.
    assert ":current_cycle" in session.last_sql
    assert "current_cycle" in session.last_params


def test_blocked_when_nothing_compares():
    with make_client(FakeSession([])) as c:
        body = c.get("/policy-comparison", headers={"Authorization": f"Bearer {user_token()}"}).json()
    assert body["items"] == []
    assert "lp_vs_rule_pct" not in body["portfolio"]
    assert body["portfolio"]["target_vs_rule_pct"] is None
    assert body["blocked_reason"]


# ---- pesos at last purchase price (pending SSM confirmation) -----------------

PRICED_ROWS = [
    {**ROWS[0], "price_per_piece": 10.0},
    {**ROWS[1], "price_per_piece": 2.0},
    # No last purchase price: left out of the peso sums and counted, never defaulted.
    {"planning_cycle_date": CYCLE, "ss_i": 5.0, "rop_i": 30.0, "forecast_value": 90.0, "sku_id": "D4",
     "product_name": "NO PRICE", "principal": "unilever", "price_per_piece": None},
]


def test_pesos_headline_is_average_stock_with_peak_alongside():
    with make_client(FakeSession(PRICED_ROWS)) as c:
        body = c.get("/policy-comparison?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"}).json()
    pesos = body["pesos"]
    assert pesos["status"] == "pending_ssm_confirmation" and "Pending SSM confirmation" in pesos["status_label"]
    assert "last purchase price" in pesos["price_basis"]
    assert pesos["headline"] == "average"
    assert (pesos["sku_count"], pesos["skus_without_price"]) == (2, 1)
    w1, w2 = 100.0 / AVG_WEEKS_PER_MONTH, 500.0 / AVG_WEEKS_PER_MONTH
    rule = 10.0 * 3 * w1 + 2.0 * 3 * w2
    # Average on hand = safety stock + half of one weekly order (review_days = 5 = one week).
    average = 10.0 * (40.0 + w1 / 2) + 2.0 * (10.0 + w2 / 2)
    peak = 10.0 * 120.0 + 2.0 * 60.0
    assert pesos["average"]["rule_stock_pesos"] == pytest.approx(rule, abs=0.01)
    assert pesos["average"]["lp_stock_pesos"] == pytest.approx(average, abs=0.01)
    assert pesos["average"]["difference_pesos"] == pytest.approx(average - rule, abs=0.01)
    assert pesos["average"]["pct_vs_rule"] == pytest.approx(round((average - rule) / rule * 100, 1))
    assert pesos["average"]["direction"] == "less"
    assert pesos["peak"]["lp_stock_pesos"] == pytest.approx(peak, abs=0.01)
    assert pesos["peak"]["difference_pesos"] == pytest.approx(peak - rule, abs=0.01)
    rule_avg = rule - (10.0 * w1 + 2.0 * w2) / 2
    assert pesos["rule_average_if_three_weeks_is_a_peak"]["rule_stock_pesos"] == pytest.approx(rule_avg, abs=0.01)
    items = {i["sku_id"]: i for i in body["items"]}
    assert items["A1"]["lp_peak_stock_pesos"] == pytest.approx(1200.0)
    assert items["A1"]["lp_average_stock_pesos"] == pytest.approx(10.0 * (40.0 + w1 / 2), abs=0.01)
    assert items["D4"]["price_per_piece"] is None and items["D4"]["rule_stock_pesos"] is None
    # No capital-freed claim rides on the peso block.
    assert body["working_capital"] is None and body["capital_freed"] is None


def test_pesos_reads_the_last_purchase_price_from_the_stock_file():
    session = FakeSession(PRICED_ROWS)
    with make_client(session) as c:
        c.get("/policy-comparison?principal=unilever", headers={"Authorization": f"Bearer {user_token()}"})
    assert "inventory_fact_real" in session.last_sql and "unit_cost_per_case > 0" in session.last_sql
    assert "AS price_per_piece" in session.last_sql


def test_pesos_blocked_when_no_product_has_a_price():
    with make_client(FakeSession(ROWS)) as c:   # ROWS carry no price column at all
        body = c.get("/policy-comparison", headers={"Authorization": f"Bearer {user_token()}"}).json()
    pesos = body["pesos"]
    assert pesos["average"] is None and pesos["peak"] is None and pesos["blocked_reason"]
    assert pesos["status"] == "pending_ssm_confirmation"
    assert pesos["skus_without_price"] == 2


def test_pesos_reproduce_the_lp_logic_check_totals():
    """reports/diagnostics/lp_logic_check_2026-10-03 section 4, from its full per-product table
    (git-ignored local/ copy: per-product prices are never committed). Skipped without it."""
    import csv
    from pathlib import Path

    from backend.routers.policy_comparison import pesos_comparison

    path = (Path(__file__).resolve().parents[2] / "reports" / "diagnostics" / "lp_logic_check_2026-10-03"
            / "local" / "issue4_policy_card_per_product.csv")
    if not path.exists():
        pytest.skip("local/issue4_policy_card_per_product.csv is not on this machine")
    with path.open(encoding="utf-8") as f:
        table = list(csv.DictReader(f))
    assert len(table) == 73
    rows = [{"ss_units": float(r["safety_stock_pcs"]), "target_units": float(r["order_up_to_pcs"]),
             "weekly_units": float(r["forecast_mar2026_pcs"]) / AVG_WEEKS_PER_MONTH,
             "rule_units": 3 * float(r["forecast_mar2026_pcs"]) / AVG_WEEKS_PER_MONTH,
             "price": float(r["cost_per_piece_php"])} for r in table]
    pesos = pesos_comparison(rows)
    # The table is rounded (price to 4 places), so pesos match to a few pesos, percents exactly.
    assert pesos["average"]["pct_vs_rule"] == -28.1
    assert pesos["peak"]["pct_vs_rule"] == 8.6
    assert pesos["peak"]["difference_pesos"] == pytest.approx(706_464, abs=25)
    assert pesos["average"]["lp_stock_pesos"] == pytest.approx(5_906_832, abs=25)
    assert pesos["average"]["rule_stock_pesos"] == pytest.approx(8_211_106, abs=25)
    assert pesos["rule_average_if_three_weeks_is_a_peak"]["average_pct_vs_rule"] == -13.7


def test_pesos_on_the_synthetic_per_product_table():
    """The same table shape as the real one above, with four INVENTED products (tests/fixtures/policy_card_synthetic.csv),
    so the arithmetic and its column mapping run on every checkout. The expected pesos were worked by hand from the four
    rows: rule = sum(price x 3 weeks), peak = sum(price x order-up-to), average = sum(price x (safety stock + half a
    weekly order)). It says nothing about SSM's real totals; the test above does, and is opt-in."""
    import csv
    from pathlib import Path

    from backend.routers.policy_comparison import pesos_comparison

    path = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "policy_card_synthetic.csv"
    with path.open(encoding="utf-8") as f:
        table = list(csv.DictReader(f))
    assert len(table) == 4
    rows = [{"ss_units": float(r["safety_stock_pcs"]), "target_units": float(r["order_up_to_pcs"]),
             "weekly_units": float(r["forecast_mar2026_pcs"]) / AVG_WEEKS_PER_MONTH,
             "rule_units": 3 * float(r["forecast_mar2026_pcs"]) / AVG_WEEKS_PER_MONTH,
             "price": float(r["cost_per_piece_php"])} for r in table]
    pesos = pesos_comparison(rows)
    assert pesos["sku_count"] == 4 and pesos["skus_without_price"] == 0
    assert pesos["average"]["rule_stock_pesos"] == pytest.approx(11_216.09, abs=0.01)
    assert pesos["average"]["lp_stock_pesos"] == pytest.approx(5_519.35, abs=0.01)
    assert pesos["peak"]["lp_stock_pesos"] == pytest.approx(9_050.00, abs=0.01)
    assert pesos["average"]["pct_vs_rule"] == -50.8
    assert pesos["peak"]["pct_vs_rule"] == -19.3
    assert pesos["rule_average_if_three_weeks_is_a_peak"]["average_pct_vs_rule"] == -40.9
    assert pesos["average"]["direction"] == "less"
