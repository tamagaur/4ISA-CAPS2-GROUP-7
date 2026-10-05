"""
tests/backend/test_dashboard_range.py — the GET /dashboard/* range endpoints
(backend/routers/dashboard_range.py), read from the marts (migration 0041).

A FakeSession routes each query by a SQL fragment (the test_descriptive_endpoints
pattern), so these never touch a database; the SQL itself is checked against live
data by tests/test_marts.py and scripts/rehearse_marts.py.
"""
from __future__ import annotations

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
    yield
    app.dependency_overrides.clear()


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


def snap(src, principal, period, pesos=None, kind="real", **extra):
    """One backend/marts.SNAPSHOT_SQL row."""
    return {"src": src, "principal": principal, "period": period, "data_kind": kind, "source_tag": None,
            "flow": None, "pesos": pesos, "pieces": None, "recorded_with_tax": False, "placeholder": False,
            "first_date": None, "last_date": None, "negative_rows": None, "products": None, **extra}


class FakeSession:
    """routes: list of (sql fragment, rows or callable(params) -> rows); first match wins.
    The month-level snapshot defaults to Unilever's real sales ending 2026-02."""

    def __init__(self, routes, snapshot=None):
        default = [snap("sales", "unilever", "2026-02", 1.0)]
        self.routes = [("'sales' AS src", default if snapshot is None else snapshot)] + routes
        self.calls: list[tuple[str, dict]] = []
        self.info: dict = {}

    def execute(self, stmt, params=None):
        sql, params = str(stmt), dict(params or {})
        self.calls.append((sql, params))
        for fragment, rows in self.routes:
            if fragment in sql:
                return FakeResult(rows(params) if callable(rows) else rows)
        raise AssertionError(f"Unexpected query in FakeSession: {sql}")

    def close(self):
        pass


def get(session, path):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        resp = c.get(path, headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ranked(principal, rows):
    """Rows as backend/marts.PARETO_SQL returns them."""
    def answer(params):
        if params["principal"] != principal:
            return []
        return [{"rank": i, "product_key": k, "sku_code": f"S{k}", "product_name": f"P{k}", "category_path": "C",
                 "brand": None, "revenue": rev, "pieces": 10.0, "months_with_sales": 3, "share": share,
                 "cumulative_share": cum, "class": cls}
                for i, (k, rev, share, cum, cls) in enumerate(rows, 1)]
    return answer


def test_pareto_lists_the_products_in_each_class_for_the_range():
    session = FakeSession([
        ("WITH rev AS", _ranked("unilever", [(1, 700.0, 0.7, 0.7, "A"), (2, 200.0, 0.2, 0.9, "B"),
                                             (3, 100.0, 0.1, 1.0, "C")])),
    ], snapshot=[snap("sales", "unilever", "2026-02", 1.0), snap("sales", "unilever", "2025-09", 1_000.0),
                 snap("sales", "unilever", "2025-10", -20.0)])
    body = get(session, "/dashboard/pareto?principal=unilever&period=2025-12&start_period=2025-07")
    assert (body["start_period"], body["end_period"], body["label"]) == ("2025-07", "2025-12", "Jul 2025 – Dec 2025")
    _, params = next((s, p) for s, p in session.calls if "WITH rev AS" in s)
    assert (params["start"], params["end"], params["a"], params["b"]) == ("2025-07", "2025-12", 0.8, 0.95)
    uni = body["principals"][0]
    assert uni["grain"] == "sku" and uni["ranked_count"] == 3 and uni["ranked_revenue"] == 1000.0
    assert uni["net_sales"] == 980.0, "net sales include the returns the ranking leaves out"
    classes = {c["tier"]: c for c in uni["classes"]}
    assert [p["sku_id"] for p in classes["A"]["products"]] == ["S1"]
    assert classes["B"]["products"][0]["cumulative_share"] == 0.9
    assert classes["C"]["share"] == pytest.approx(0.1)
    assert uni["pareto_check"]["top_count"] == 1


def test_pareto_counts_a_returns_heavy_month_as_zero():
    """One revenue rule everywhere (Yuan, 2026-10-05): the stored ABC run's, orchestrate_abc.py:208."""
    from backend.marts import PARETO_SQL
    assert "SUM(GREATEST(s.pesos, 0)) AS revenue" in PARETO_SQL
    assert "SUM(s.pesos) AS revenue" not in PARETO_SQL


def test_pareto_ranks_del_monte_by_category_and_says_when_nothing_ranks():
    session = FakeSession([("WITH rev AS", lambda p: [])])
    body = get(session, "/dashboard/pareto?principal=delmonte&period=2025-12")
    dm = body["principals"][0]
    assert dm["grain"] == "category" and dm["ranked_count"] == 0
    assert "took back" in dm["blocked_reason"]


def test_yoy_compares_the_same_months_a_year_earlier():
    def yoy(params):
        assert (params["start"], params["end"], params["pstart"], params["pend"]) == (
            "2025-03", "2026-02", "2024-03", "2025-02")
        return [
            {"product_key": 1, "sku_code": "S1", "product_name": "P1", "category_path": "C", "pesos": 150.0,
             "pieces": 15.0, "months": 12, "prior_pesos": 100.0, "prior_pieces": 10.0, "prior_months": 12},
            {"product_key": 2, "sku_code": "S2", "product_name": "P2", "category_path": "C", "pesos": 50.0,
             "pieces": 5.0, "months": 2, "prior_pesos": None, "prior_pieces": None, "prior_months": None},
        ]
    body = get(FakeSession([("WITH cur AS", yoy)]), "/dashboard/yoy?principal=unilever")
    assert body["prior_label"] == "Mar 2024 – Feb 2025"
    rows = {r["sku_id"]: r for r in body["principals"][0]["rows"]}
    assert rows["S1"]["change_pct"] == pytest.approx(50.0)
    assert rows["S2"]["prior_pesos"] is None and rows["S2"]["change_pct"] is None, "a new product is not +100%"
    assert body["principals"][0]["prior_pesos"] == 100.0


def _acc(key, month, forecast, actual, cat="CAT"):
    miss = forecast - actual
    return {"run_id": 2, "forecast_source": "backtest_recreated", "run_label": "b", "cohort": None,
            "principal": "unilever", "product_key": key, "sku_code": f"S{key}", "product_name": f"P{key}",
            "category_path": cat, "month": month, "forecast_pieces": forecast, "actual_pieces": actual,
            "ma3_pieces": actual, "miss_pieces": miss, "abs_miss_pieces": abs(miss),
            "direction": "over" if miss > 0 else "under", "run_length": 1, "price_per_piece": 2.0,
            "miss_pesos": miss * 2.0, "abs_miss_pesos": abs(miss) * 2.0, "surplus_pesos": max(miss, 0) * 2.0,
            "shortage_pesos": max(-miss, 0) * 2.0, "opening_pieces": 5.0, "closing_pieces": 0.0,
            "possibly_stock_limited": miss > 0, "method": "ma3", "bin": "short"}


def test_accuracy_by_category_and_by_product():
    rows = [_acc(1, "2025-12", 120, 100, "SOAP"), _acc(2, "2025-12", 50, 100, "TEA")]
    session = FakeSession([("FROM mart.accuracy_mart a", rows)])
    body = get(session, "/dashboard/accuracy?principal=unilever&level=category")
    cats = {c["category_path"]: c for c in body["rows"]}
    assert cats["SOAP"]["surplus_pesos"] == 40.0 and cats["TEA"]["shortage_pesos"] == 100.0
    assert body["forecast_source"] == "backtest_recreated" and body["coverage"] == ["unilever"]
    body = get(session, "/dashboard/accuracy?principal=unilever&level=product")
    assert [(r["product_key"], r["direction"], r["possibly_stock_limited"]) for r in body["rows"]] == [
        (1, "over", True), (2, "under", False)]


def test_accuracy_reads_a_chosen_run():
    session = FakeSession([("FROM mart.accuracy_mart a", [])])
    get(session, "/dashboard/accuracy?principal=unilever&run_id=3")
    _, params = next((s, p) for s, p in session.calls if "FROM mart.accuracy_mart a" in s)
    assert params["run_id"] == 3


def test_accuracy_and_idle_stock_say_why_del_monte_has_none():
    acc = get(FakeSession([]), "/dashboard/accuracy?principal=delmonte")
    assert acc["rows"] == [] and "category grain" in acc["blocked_reason"]
    idle = get(FakeSession([]), "/dashboard/idle-stock?principal=delmonte")
    assert idle["products"] == 0 and "category" in idle["blocked_reason"]


def test_idle_stock_lists_products_at_the_count_on_or_before_the_end():
    head = [{"count_date": None, "window_start": "2025-09", "window_end": "2026-02", "window_months": 6,
             "products": 2, "products_with_value": 1, "pesos": 1_000.0, "never_sold": 1}]
    items = [{"product_key": 7, "sku_code": "S7", "product_name": "P7", "category_path": "C", "pesos": 1_000.0,
              "pieces": 40.0, "cases": 1.0, "last_sale_period": None, "never_sold": True}]
    session = FakeSession([
        ("SELECT MIN(count_date)", head),
        ("FROM mart.idle_stock i", items),
    ], snapshot=[snap("sales", "unilever", "2026-02", 1.0), snap("stock", "unilever", "2026-02", 5.0),
                 snap("stock", "unilever", "2026-03", 5.0)])
    body = get(session, "/dashboard/idle-stock?principal=unilever")
    assert (body["count_period"], body["products"], body["pesos"]) == ("2026-02", 2, 1_000.0)
    assert body["items"][0]["never_sold"] is True and body["window_rule_months"] == 6
    _, params = next((s, p) for s, p in session.calls if "FROM mart.idle_stock i" in s)
    assert params["period"] == "2026-02", "the count on or before the range's end, not the later 2026-03 one"


def test_product_sales_label_the_del_monte_split_as_estimated():
    rows = [{"product_key": 9, "sku_code": "D9", "product_name": "Peaches", "level": "product", "period": "2025-12",
             "data_kind": "filled", "source_tag": "synthetic_category_split", "pesos": 120.0, "pieces": 4.0,
             "pieces_unit_confirmed": False, "pesos_basis": "ex_vat"}]
    session = FakeSession([("FROM mart.sales_mart s", rows)], snapshot=[snap("sales", "delmonte", "2025-12", 1.0)])
    body = get(session, "/dashboard/product-sales?principal=delmonte")
    row = body["rows"][0]
    assert row["estimated"] is True and row["data_kind"] == "filled" and row["source"] == "synthetic_category_split"
    assert row["pieces"] is None, "Del Monte's quantity unit is unconfirmed"
    assert row["pesos_basis"] == "selling price, ex-VAT"
    assert body["estimated_rows"] == 1
    _, params = next((s, p) for s, p in session.calls if "FROM mart.sales_mart s" in s)
    assert params["kinds"] == ["real", "filled"], "generated rows only in preview"


def test_forecast_runs_mark_the_default_backtest():
    from backend.marts import DEFAULT_BACKTEST_LABEL
    runs = [{"run_id": 1, "kind": "stored_run", "label": "forecast_result generated x", "cohort": None,
             "window_start": "2026-03", "window_end": "2026-03", "created_at": None, "source_generated_at": None,
             "rows": 132},
            {"run_id": 2, "kind": "backtest_recreated", "label": DEFAULT_BACKTEST_LABEL, "cohort": "c",
             "window_start": "2023-10", "window_end": "2026-02", "created_at": None, "source_generated_at": None,
             "rows": 3503}]
    body = get(FakeSession([("FROM mart.forecast_run r", runs),
                            ("to_regclass('mart.refresh_log')", [{"present": False}])]), "/dashboard/forecast-runs")
    assert [(r["forecast_source"], r["default"]) for r in body["runs"]] == [("stored_run", False), ("backtest_recreated", True)]
    assert body["marts"]["present"] is False


# ---- class changes ------------------------------------------------------------

def _two_ranges(now_rows, before_rows):
    """PARETO_SQL answers for the range ending 2025-12 and for any earlier one."""
    def answer(params):
        if params["principal"] != "unilever":
            return []
        return _ranked("unilever", now_rows if params["end"] == "2025-12" else before_rows)(params)
    return answer


def test_class_changes_list_who_entered_and_left_class_a():
    now = [(1, 600.0, 0.6, 0.6, "A"), (2, 200.0, 0.2, 0.8, "A"), (3, 150.0, 0.15, 0.95, "B"), (4, 50.0, 0.05, 1.0, "C")]
    before = [(1, 500.0, 0.5, 0.5, "A"), (3, 300.0, 0.3, 0.8, "A"), (5, 100.0, 0.1, 0.9, "B"), (2, 60.0, 0.06, 0.96, "C"),
              (6, 40.0, 0.04, 1.0, "C")]
    session = FakeSession([("WITH rev AS", _two_ranges(now, before))])
    body = get(session, "/dashboard/class-changes?principal=unilever&period=2025-12&start_period=2025-01")
    assert (body["start_period"], body["end_period"]) == ("2025-01", "2025-12")
    assert (body["compare_start_period"], body["compare_end_period"]) == ("2024-01", "2024-12"), "default: a year earlier"
    assert body["compare_label"] == "Jan 2024 – Dec 2024"
    uni = body["principals"][0]
    assert (uni["class_a_count"], uni["compare_class_a_count"], uni["stayed_count"]) == (2, 2, 1)
    assert (uni["entered_count"], uni["left_count"]) == (1, 1)
    entered, left = uni["entered"][0], uni["left"][0]
    assert (entered["sku_id"], entered["class"], entered["compare_class"]) == ("S2", "A", "C")
    assert (entered["revenue"], entered["compare_revenue"], entered["change_pesos"]) == (200.0, 60.0, 140.0)
    assert entered["change_pct"] == pytest.approx(233.3)
    assert (left["sku_id"], left["class"], left["compare_class"], left["change_pesos"]) == ("S3", "B", "A", -150.0)
    assert (uni["entered_revenue"], uni["entered_compare_revenue"]) == (200.0, 60.0)
    assert (uni["left_revenue"], uni["left_compare_revenue"]) == (150.0, 300.0)
    ranked = [s for s, _ in session.calls if "WITH rev AS" in s]
    assert len(ranked) == 2


def test_class_changes_say_why_a_side_has_no_class():
    now = [(1, 900.0, 0.9, 0.9, "A"), (7, 100.0, 0.1, 1.0, "B")]       # 1 is new; 8 and 9 are gone
    before = [(8, 500.0, 0.5, 0.5, "A"), (9, 300.0, 0.3, 0.8, "A"), (7, 200.0, 0.2, 1.0, "C")]
    sums = [{"product_key": 9, "months": 2, "has_blank": False, "compare_months": 12, "compare_has_blank": False}]
    session = FakeSession([("WITH rev AS", _two_ranges(now, before)), ("bool_or(s.pesos IS NULL)", sums)])
    body = get(session, "/dashboard/class-changes?principal=unilever&period=2025-12&start_period=2025-01"
                        "&compare_period=2024-06")
    assert (body["compare_start_period"], body["compare_end_period"]) == ("2023-07", "2024-06"), "same length"
    uni = body["principals"][0]
    new = uni["entered"][0]
    assert (new["compare_class"], new["compare_revenue"], new["compare_class_note"]) == (None, 0.0, "no sales in the range")
    assert new["change_pesos"] == 900.0 and new["change_pct"] is None
    left = {i["product_key"]: i for i in uni["left"]}
    assert left[8]["class_note"] == "no sales in the range"
    assert left[9]["class"] is None and "returns matched or exceeded sales" in left[9]["class_note"]
    _, params = next((s, p) for s, p in session.calls if "bool_or(s.pesos IS NULL)" in s)
    assert params["keys"] == [1, 8, 9]


def test_class_changes_refuse_a_compare_start_without_its_end():
    app.dependency_overrides[get_db] = lambda: FakeSession([])
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(user_token())
    with TestClient(app) as c:
        resp = c.get("/dashboard/class-changes?principal=unilever&period=2025-12&compare_start_period=2024-01",
                     headers={"Authorization": f"Bearer {user_token()}"})
    assert resp.status_code == 422


# ---- accuracy: two labelled headline figures ------------------------------------

def test_accuracy_returns_both_headline_figures_with_plain_labels():
    # One month: product 1 over by 20, product 2 under by 50. Summed first they largely cancel.
    rows = [_acc(1, "2025-12", 120, 100), _acc(2, "2025-12", 50, 100)]
    body = get(FakeSession([("FROM mart.accuracy_mart a", rows)]), "/dashboard/accuracy?principal=unilever")
    company, typical = body["company_total"], body["typical_product_weighted"]
    assert company["value"] == pytest.approx(30 / 200)      # |170 - 200| x price / (200 x price)
    assert typical["value"] == pytest.approx(70 / 200)      # (20 + 50) / 200
    assert company["label"].startswith("Company total:") and "added up first" in company["label"]
    assert typical["label"].startswith("Typical product, weighted by sales:")
    assert "pesos" in company["unit"] and typical["unit"] == "pieces"
    assert "total" not in body, "never a bare total"
    # The old names carry the same two numbers; 'total' is still accepted as the level and read as 'summary'.
    assert (body["total_wape_pesos"], body["wape_pieces"]) == (company["value"], typical["value"])
    assert body["level"] == "summary"
    assert get(FakeSession([("FROM mart.accuracy_mart a", rows)]),
               "/dashboard/accuracy?principal=unilever&level=total")["level"] == "summary"


def test_accuracy_headline_figures_are_null_not_missing_when_nothing_is_scored():
    body = get(FakeSession([("FROM mart.accuracy_mart a", [])]), "/dashboard/accuracy?principal=unilever")
    assert body["company_total"]["value"] is None and body["typical_product_weighted"]["value"] is None
    assert body["company_total"]["label"] and body["typical_product_weighted"]["label"]
