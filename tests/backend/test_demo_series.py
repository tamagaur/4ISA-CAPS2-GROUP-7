"""The labelled demonstration (schema demo) behind DM_DEMO_ENABLED: off by default, labelled per row, the four
origins kept apart, zero-sale months never generated, wired into /forecast and /recommendations."""
import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")
    # Empty, not deleted: a request that runs load_dotenv(override=False) (auth_utils, mfa) would
    # otherwise bring back a laptop .env's DM_DEMO_ENABLED=true and turn the switch on mid-test.
    monkeypatch.setenv("DM_DEMO_ENABLED", "")
    yield
    app.dependency_overrides.clear()


class R:
    def __init__(self, rows): self._r = rows
    def mappings(self): return self
    def all(self): return self._r
    def first(self): return self._r[0] if self._r else None


class FakeSession:
    def __init__(self, runs, unilever=None, dm=None, forecasts=None, params=None, products=None, stock=None, lp=None):
        self.runs, self.unilever, self.dm = runs, unilever or [], dm or []
        self.forecasts, self.params, self.products = forecasts or [], params or [], products or {}
        self.stock, self.lp = stock or [], lp or []

    def execute(self, stmt, params=None):
        sql, params = str(stmt), params or {}
        if "FROM demo.run" in sql:
            return R([r for r in self.runs if r["principal"] == params["p"]][:1])
        if "FROM demo.unilever_sku_sales" in sql and "GROUP BY" in sql:
            out = {}
            for r in self.unilever:
                out[(r["sku"], r["origin"])] = out.get((r["sku"], r["origin"]), 0) + 1
            return R([{"key": k, "origin": o, "n": n} for (k, o), n in out.items()])
        if "FROM demo.unilever_sku_sales" in sql:
            return R([r for r in self.unilever if r["sku"] == params["k"]])
        if "FROM demo.dm_category_sales" in sql and "GROUP BY" in sql:
            out = {}
            for r in self.dm:
                out[(r["cat"], r["origin"])] = out.get((r["cat"], r["origin"]), 0) + 1
            return R([{"key": k, "origin": o, "n": n} for (k, o), n in out.items()])
        if "FROM demo.dm_category_sales" in sql:
            return R([r for r in self.dm if r["cat"] == params["k"]])
        if "FROM demo.dm_category_param" in sql:
            return R(self.params)
        if "FROM demo.dm_forecast" in sql:
            return R(self.forecasts)
        if "FROM demo.dm_category_stock" in sql:
            return R(self.stock)
        if "FROM demo.dm_category_lp" in sql:
            return R(self.lp)
        if "FROM Product_Dimension" in sql:
            row = self.products.get(params.get("sku_id"))
            return R([row] if row else [])
        return R([])  # permission and user lookups

    def close(self): pass


RUNS = [{"principal": "unilever", "run_id": 2, "seed": 20261015, "generator_version": "dm-demo-1", "window_end": "2026-02"},
        {"principal": "delmonte", "run_id": 4, "seed": 20261015, "generator_version": "dm-demo-1", "window_end": "2025-12"}]
UNI = [{"sku": "S1", "period": "2021-01", "quantity": 9.0, "net_amount": 90.0, "origin": "backcast", "anchor_override": False},
       {"sku": "S1", "period": "2023-01", "quantity": 10.0, "net_amount": 100.0, "origin": "real_copy", "anchor_override": False},
       {"sku": "S1", "period": "2023-04", "quantity": 7.0, "net_amount": 70.0, "origin": "real_copy", "anchor_override": False}]


def dm(period, q, origin, over=False):
    return {"cat": "/A", "period": period, "quantity": q, "net_amount": q * 10, "origin": origin, "anchor_override": over}


DM = [dm("2021-01", 5.0, "backcast"), dm("2023-01", 6.0, "real_copy"), dm("2023-02", 7.0, "interpolated"),
      dm("2023-03", 8.0, "real_copy"), dm("2024-03", 6.5, "bridged"),
      {**dm("2021-01", 4.0, "backcast", True), "cat": "BEVERAGE"}, {**dm("2023-06", 4.0, "backcast", True), "cat": "BEVERAGE"},
      {**dm("2025-03", 9.0, "real_copy"), "cat": "BEVERAGE"}]
FORECASTS = [{"category_path": "BEVERAGE", "forecast_period": "2026-01", "forecast_quantity": 3418.82, "method": "ma3",
              "history_months": 10, "interpolated_in_window": 2}]
PARAMS = [{"category_path": "/A", "first_real_period": "2023-01"}, {"category_path": "BEVERAGE", "first_real_period": "2025-03"}]


def client(session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="admin", full_name="A"))
    return TestClient(app)


def get(c, path):
    tok = auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="admin", full_name="A")
    return c.get(path, headers={"Authorization": f"Bearer {tok}"})


def session():
    return FakeSession(RUNS, UNI, DM, FORECASTS, PARAMS)


def test_off_by_default_is_a_plain_404():
    with client(session()) as c:
        assert get(c, "/demo/series?principal=unilever&key=S1").status_code == 404
        assert get(c, "/demo/index?principal=delmonte").status_code == 404


def test_unilever_backcast_apart_and_zero_sale_months_not_generated(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "true")
    with client(session()) as c:
        b = get(c, "/demo/series?principal=unilever&key=S1").json()
    assert b["data_source"] == "synthetic_demonstration" and b["demonstration"] is True and b["demonstration_note"]
    assert b["origin_counts"] == {"real_copy": 2, "interpolated": 0, "bridged": 0, "backcast": 1, "forward_filled": 0}
    pts = {p["period"]: p for p in b["points"]}
    assert pts["2021-01"]["origin"] == "backcast" and pts["2021-01"]["reason"] == "no_data_recorded_before_2023"
    assert (pts["2023-02"]["quantity"], pts["2023-02"]["origin"], pts["2023-02"]["reason"]) == (0.0, None, "no_sale")
    assert pts["2023-01"]["reason"] is None and pts["2023-01"]["origin"] == "real_copy"
    assert all(p["demonstration"] is True and p["demonstration_note"] for p in b["points"])
    assert "January 2023" in b["gap_note"]
    assert not any(k in b for k in ("mape", "mase", "wape", "confidence_lower", "confidence_upper"))


def test_del_monte_four_origins_are_separate_with_their_own_reasons(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "1")
    with client(session()) as c:
        b = get(c, "/demo/series?principal=delmonte&key=/A").json()
    assert b["origin_counts"] == {"real_copy": 2, "interpolated": 1, "bridged": 1, "backcast": 1, "forward_filled": 0}
    reasons = {p["period"]: p["reason"] for p in b["points"]}
    assert reasons["2023-02"] == "interpolated" and reasons["2021-01"] == "no_data_recorded_before_2023"
    assert reasons["2024-03"] == "taxonomy_change_bridge"
    assert not any(p["generated_before_first_observation"] for p in b["points"])


def test_anchor_overridden_backcast_is_flagged_and_gets_its_own_reason(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "1")
    with client(session()) as c:
        b = get(c, "/demo/series?principal=delmonte&key=BEVERAGE").json()
    pts = {p["period"]: p for p in b["points"]}
    assert pts["2021-01"]["origin"] == "backcast" and pts["2021-01"]["generated_before_first_observation"] is True
    assert pts["2021-01"]["reason"] == "no_data_recorded_before_2023"
    assert pts["2023-06"]["reason"] == "no_observation_before_series_start"  # inside SSM's records, before this series
    assert pts["2025-03"]["origin"] == "real_copy" and pts["2025-03"]["generated_before_first_observation"] is False


def test_index_names_each_series_taxonomy_and_warns_against_summing(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "1")
    with client(session()) as c:
        b = get(c, "/demo/index?principal=delmonte").json()
    tax = {s["key"]: s["taxonomy"] for s in b["series"]}
    assert tax == {"/A": "pre_2025", "BEVERAGE": "2025"} and "do not sum" in b["taxonomy_note"]
    assert b["data_source"] == "synthetic_demonstration"


def test_totals_serve_the_one_canonical_series_with_its_origin_split(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "1")
    s = session()
    base = s.execute

    def execute(stmt, params=None):
        if "FROM demo.dm_monthly_total" in str(stmt):
            return R([{"period": "2024-06", "pesos": 100.0, "real_pesos": None, "interpolated_pesos": None,
                       "bridged_pesos": 100.0, "backcast_pesos": None, "series": 77, "series_left_out": 5}])
        return base(stmt, params)
    s.execute = execute
    with client(s) as c:
        b = get(c, "/demo/totals").json()
    m = b["months"][0]
    assert (m["pesos"], m["bridged"], m["series"], m["series_left_out"]) == (100.0, 100.0, 77, 5)
    assert b["data_source"] == "synthetic_demonstration" and "single" not in b["rule"] and "canonical" in b["rule"]


def test_a_left_out_back_cast_point_is_flagged_not_canonical_on_its_own_series(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "1")
    s = session()
    for r in s.dm:
        r["in_canonical_total"] = not (r["origin"] == "backcast" and r["anchor_override"])
    with client(s) as c:
        pts = {p["period"]: p for p in get(c, "/demo/series?principal=delmonte&key=BEVERAGE").json()["points"]}
    assert pts["2021-01"]["in_canonical_total"] is False and pts["2025-03"]["in_canonical_total"] is True


def test_unknown_series_is_404(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "yes")
    with client(session()) as c:
        assert get(c, "/demo/series?principal=unilever&key=NOPE").status_code == 404


# ---- wiring ---------------------------------------------------------------------------------------------------

def test_forecast_for_del_monte_is_blocked_when_the_flag_is_off():
    with client(session()) as c:
        b = get(c, "/forecast/BEVERAGE?principal=delmonte").json()
    assert b["forecast"] == [] and b["blocked_reason"] and "demonstration" not in b


def test_forecast_for_del_monte_serves_the_labelled_demo_series_and_ma3(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "1")
    with client(session()) as c:
        b = get(c, "/forecast/DM?principal=delmonte&category=BEVERAGE").json()
    assert b["data_source"] == "synthetic_demonstration" and b["demonstration"] is True
    assert b["forecast"][0]["forecast_value"] == 3418.82 and b["forecast"][0]["status"] == "ok"
    assert b["forecast"][0]["mape"] is None and b["forecast"][0]["confidence_lower"] is None
    assert b["forecast"][0]["model_params"] == {"method": "ma3", "demonstration": True}
    assert {p["origin"] for p in b["actuals"]} == {"backcast", "real_copy"}
    assert all(p["demonstration"] is True for p in b["actuals"])


def test_recommendations_for_del_monte_add_the_labelled_forecasts_and_still_no_plan(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "1")
    with client(session()) as c:
        b = get(c, "/recommendations?principal=delmonte").json()
    assert b["items"] == [] and b["count"] == 0
    assert b["data_source"] == "synthetic_demonstration" and b["demonstration"] is True
    assert b["demo_forecasts"][0]["category"] == "BEVERAGE" and b["demo_forecasts"][0]["demonstration"] is True
    assert b["demo_stock"] == []
    assert b["order_plan"]["available"] is False and "run_lp" in b["order_plan"]["reason"]


def test_recommendations_for_del_monte_serves_the_order_plan_once_run_lp_has_run(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "1")
    s = session()
    s.stock = [{"category_path": "BEVERAGE", "period": "2025-12", "quantity_on_hand": 500.0, "months_of_cover": 0.7}]
    s.lp = [{"category_path": "BEVERAGE", "period": "2026-01", "forecast_quantity": 3418.82, "stock_on_hand": 500.0,
             "sigma_d": 12.5, "safety_stock": 16.0, "target_stock": 600.0, "order_qty": 100.0}]
    with client(s) as c:
        b = get(c, "/recommendations?principal=delmonte").json()
    assert b["demo_stock"][0]["quantity_on_hand"] == 500.0 and b["demo_stock"][0]["origin"] == "generated_months_of_cover"
    assert b["order_plan"]["available"] is True
    item = b["order_plan"]["items"][0]
    assert (item["category"], item["order_qty"], item["target_stock"]) == ("BEVERAGE", 100.0, 600.0)
    assert "generated demand AND generated stock" in b["order_plan"]["demonstration_note"]
