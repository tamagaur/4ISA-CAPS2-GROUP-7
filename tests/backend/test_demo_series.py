"""GET /demo/series: off by default, labelled per row, origins kept apart, zero-sale months never generated."""
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
    monkeypatch.delenv("DM_DEMO_ENABLED", raising=False)
    yield
    app.dependency_overrides.clear()


class R:
    def __init__(self, rows): self._r = rows
    def mappings(self): return self
    def all(self): return self._r
    def first(self): return self._r[0] if self._r else None


class FakeSession:
    def __init__(self, runs, unilever=None, dm=None):
        self.runs, self.unilever, self.dm = runs, unilever or [], dm or []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "FROM demo.run" in sql:
            return R([r for r in self.runs if r["principal"] == params["p"]][:1])
        if "FROM demo.unilever_sku_sales" in sql:
            return R([r for r in self.unilever if r["sku"] == params["k"]])
        if "FROM demo.dm_category_sales" in sql:
            return R([r for r in self.dm if r["cat"] == params["k"]])
        if "user_permission" in sql.lower() or "role" in sql.lower():
            return R([])
        raise AssertionError(sql)

    def close(self): pass


RUNS = [{"principal": "unilever", "run_id": 2, "seed": 20261015, "generator_version": "dm-demo-1", "window_end": "2026-02"},
        {"principal": "delmonte", "run_id": 1, "seed": 20261015, "generator_version": "dm-demo-1", "window_end": "2025-12"}]
UNI = [{"sku": "S1", "period": "2021-01", "quantity": 9.0, "net_amount": 90.0, "origin": "backcast"},
       {"sku": "S1", "period": "2023-01", "quantity": 10.0, "net_amount": 100.0, "origin": "real_copy"},
       {"sku": "S1", "period": "2023-04", "quantity": 7.0, "net_amount": 70.0, "origin": "real_copy"}]
DM = [{"cat": "/A", "period": "2022-12", "quantity": 5.0, "net_amount": 50.0, "origin": "backcast"},
      {"cat": "/A", "period": "2023-01", "quantity": 6.0, "net_amount": 60.0, "origin": "real_copy"},
      {"cat": "/A", "period": "2023-02", "quantity": 7.0, "net_amount": 70.0, "origin": "interpolated"},
      {"cat": "/A", "period": "2023-03", "quantity": 8.0, "net_amount": 80.0, "origin": "real_copy"}]


def client(session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="admin", full_name="A"))
    return TestClient(app)


def get(c, path):
    tok = auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="admin", full_name="A")
    return c.get(path, headers={"Authorization": f"Bearer {tok}"})


def test_off_by_default_is_a_plain_404():
    with client(FakeSession(RUNS, UNI, DM)) as c:
        assert get(c, "/demo/series?principal=unilever&key=S1").status_code == 404


def test_unilever_series_backcast_apart_and_zero_sale_months_not_generated(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "true")
    with client(FakeSession(RUNS, UNI, DM)) as c:
        r = get(c, "/demo/series?principal=unilever&key=S1")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["data_source"] == "synthetic_demonstration" and b["demonstration"] is True and b["demonstration_note"]
    assert b["origin_counts"] == {"real_copy": 2, "interpolated": 0, "bridged": 0, "backcast": 1}
    pts = {p["period"]: p for p in b["points"]}
    assert pts["2021-01"]["origin"] == "backcast" and pts["2021-01"]["reason"] == "no_data_recorded_before_2023"
    assert (pts["2023-02"]["quantity"], pts["2023-02"]["origin"], pts["2023-02"]["reason"]) == (0.0, None, "no_sale")
    assert pts["2023-01"]["reason"] is None and pts["2023-01"]["origin"] == "real_copy"
    assert all(p["demonstration"] is True and p["demonstration_note"] for p in b["points"])
    assert "January 2023" in b["gap_note"]
    assert not any(k in b for k in ("mape", "mase", "wape", "confidence_lower", "confidence_upper"))


def test_del_monte_keeps_interpolated_and_backcast_separate(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "1")
    with client(FakeSession(RUNS, UNI, DM)) as c:
        b = get(c, "/demo/series?principal=delmonte&key=/A").json()
    assert b["origin_counts"] == {"real_copy": 2, "interpolated": 1, "bridged": 0, "backcast": 1}
    reasons = {p["period"]: p["reason"] for p in b["points"]}
    assert reasons["2023-02"] == "interpolated" and reasons["2022-12"] == "no_data_recorded_before_2023"


def test_unknown_series_is_404(monkeypatch):
    monkeypatch.setenv("DM_DEMO_ENABLED", "yes")
    with client(FakeSession(RUNS, UNI, DM)) as c:
        assert get(c, "/demo/series?principal=unilever&key=NOPE").status_code == 404
