"""
tests/test_error_decomposition.py — the stored forecast-error decomposition (migration 0063,
mart.refresh_error_decomposition, GET /dashboard/error-decomposition).

Static checks (no database): the migration writes only its own two tables, reads the as-served runs the
script stores, and its defaults are the values analytics.params gives; the refresh rides on every full
refresh and cannot undo it; the endpoint turns summed components into shares. The live test (skipped
without SUPABASE_DB_URL, read only) checks the stored tables add up and that the same figures come out of
an independent recomputation of the as-served rows.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from analytics import marts as amarts
from analytics.params import PLACEHOLDERS, SERVICE_Z, abc_method
from backend import auth_utils, marts
from backend.deps import get_current_user, get_db
from backend.main import app
from scripts.accuracy_as_served import AS_SERVED_RUNS

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "analytics" / "db" / "migrations" / "0063_error_decomposition.sql"
# the function as last defined (0064 replaces 0063's body)
LATEST = REPO / "analytics" / "db" / "migrations" / "0064_error_decomposition_counterfactual_and_orphans.sql"


def _sql() -> str:
    return "\n".join(l for l in MIGRATION.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))


def _latest() -> str:
    return "\n".join(l for l in LATEST.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))


def test_the_migration_writes_only_its_own_tables():
    sql = _sql()
    written = set(re.findall(r"\b(?:INSERT INTO|DELETE FROM|UPDATE|TRUNCATE(?: TABLE)?)\s+([\w.]+)", sql))
    assert written == {"mart.error_decomposition", "mart.error_decomposition_row"}
    assert not re.search(r"\bDROP\b", sql)
    # the only ALTERs are row-level security on those two tables, like every mart
    assert set(re.findall(r"ALTER TABLE ([\w.]+) ENABLE ROW LEVEL SECURITY", sql)) == written
    assert len(re.findall(r"\bALTER\b", sql)) == 2


def test_it_reads_only_what_already_exists_and_never_the_planning_outputs_it_could_feed():
    sql = _sql()
    reads = set(re.findall(r"\b(?:FROM|JOIN)\s+((?:mart\.|public\.)?[a-z_]+)", sql))
    assert {"mart.sales_mart", "mart.forecast_run", "mart.forecast_run_value", "abc_classification",
            "lp_recommendation"} <= reads
    # nothing it reads back is something planning reads from it
    assert "forecast_result" not in sql and "lp_run" not in sql


def test_defaults_are_the_values_the_code_passes_and_the_signature_matches():
    sql = _sql()
    assert f"p_service_z numeric DEFAULT {SERVICE_Z:g}" in sql
    assert f"p_protect_days integer DEFAULT {int(PLACEHOLDERS['review_days'] + PLACEHOLDERS['lead_days'])}" in sql
    assert f"p_tier_a_basis text DEFAULT '{abc_method('unilever')}'" in sql
    assert amarts.decomposition_params("t") == {
        "trigger": "t", "service_z": SERVICE_Z,
        "protect_days": 8, "tier_a_basis": abc_method("unilever")}
    assert amarts.DECOMPOSITION_SIGNATURE.count(",") == sql.split("FUNCTION mart.refresh_error_decomposition(")[1].split(") RETURNS")[0].count("DEFAULT") - 1


def test_the_forecast_source_pattern_matches_every_as_served_calendar_label_and_no_other():
    pattern = re.search(r"r\.label ~ '([^']+)'", _latest()).group(1)
    for name, (label, _cohort) in AS_SERVED_RUNS.items():
        assert bool(re.search(pattern, label)) == name.startswith("as_served_calendar"), name
    # the three tiers each have one such run
    assert {n for n in AS_SERVED_RUNS if n.startswith("as_served_calendar")} == {
        "as_served_calendar", "as_served_calendar_B", "as_served_calendar_C"}


def test_safety_stock_prefers_the_stored_plan_and_records_which_method_was_used():
    sql = _latest()
    assert "COALESCE(s.ss_stored, s.ss_rebuilt) AS ss" in sql
    assert "WHEN ss_stored IS NOT NULL THEN 'stored_lp' WHEN ss_rebuilt IS NOT NULL THEN 'rebuilt' ELSE 'none'" in sql
    assert "lp.ss_i AS ss_stored" in sql


# ---- the refresh hook ----------------------------------------------------------

class _Cursor:
    def __init__(self, present=True, fail=False):
        self.present, self.fail, self.calls, self._last = present, fail, [], None

    def execute(self, sql, params=None):
        self.calls.append(sql)
        if "to_regprocedure" in sql:
            self._last = (self.present,)
        elif "refresh_error_decomposition(" in sql:
            if self.fail:
                raise RuntimeError("boom")
            self._last = ({"error_decomposition": 7},)
        elif "refresh_planning(" in sql:
            self._last = ({"planning_mart": 3},)
        elif "mart.refresh(" in sql:
            self._last = ({"sales_mart": 1},)

    def fetchone(self):
        return self._last


def test_every_full_refresh_also_refreshes_the_decomposition_after_the_planning_mart():
    cur = _Cursor()
    assert amarts.refresh_marts_cursor(cur, "load") == {"sales_mart": 1, "planning_mart": 3, "error_decomposition": 7}
    refreshes = [c for c in cur.calls if "to_regprocedure" not in c and "SAVEPOINT" not in c]
    assert "mart.refresh(" in refreshes[0] and "refresh_planning(" in refreshes[1] and "refresh_error_decomposition(" in refreshes[2]
    assert "error_decomposition" in amarts.MART_TABLES and "error_decomposition_row" in amarts.MART_TABLES


def test_a_failed_decomposition_rolls_back_to_its_savepoint_and_keeps_the_other_marts(capsys):
    cur = _Cursor(fail=True)
    assert amarts.refresh_marts_cursor(cur, "load") == {"sales_mart": 1, "planning_mart": 3}
    assert "ROLLBACK TO SAVEPOINT error_decomposition" in cur.calls
    assert "FAILED" in capsys.readouterr().out


def test_the_decomposition_refresh_is_skipped_for_a_scratch_target_or_without_0063(capsys):
    class NoQueries:
        def execute(self, *a, **k):
            raise AssertionError("a skipped refresh must not touch the database")

    assert amarts.refresh_error_decomposition_cursor(NoQueries(), "load", schema="ssm_scratch") is None
    assert amarts.refresh_error_decomposition_cursor(_Cursor(present=False), "x") is None
    assert "migration 0063" in capsys.readouterr().out


# ---- the shares ---------------------------------------------------------------

def _sums(**over):
    base = {"product_months": 10, "product_months_with_ss": 10, "ss_stored_rows": 0, "ss_rebuilt_rows": 10,
            "exceed_product_months": 2, "priced_product_months": 10, "actual_pieces": 1000.0, "over_pieces": 60.0,
            "absorbed_pieces": 25.0, "beyond_pieces": 15.0, "under_no_ss_pieces": 0.0, "actual_pesos": 5000.0,
            "over_pesos": 300.0, "absorbed_pesos": 100.0, "beyond_pesos": 100.0, "under_no_ss_pesos": 0.0}
    return {**base, **over}


def test_shares_are_of_total_error_and_of_total_actual_and_sum_to_one_over_the_error():
    f = marts._decomposition_figure(_sums())
    assert f["error_pieces"] == 100.0
    assert (f["over_share_of_error_pieces"], f["absorbed_share_of_error_pieces"], f["beyond_share_of_error_pieces"]) == (0.6, 0.25, 0.15)
    assert f["beyond_share_of_actual_pieces"] == pytest.approx(0.015)
    assert f["exceed_share_of_product_months"] == 0.2
    assert f["ss_method"] == "rebuilt"
    assert marts._decomposition_figure(_sums(ss_stored_rows=3, ss_rebuilt_rows=7))["ss_method"] == "mixed"
    assert marts._decomposition_figure(_sums(ss_stored_rows=10, ss_rebuilt_rows=0))["ss_method"] == "stored_lp"


def test_an_unclassified_under_forecast_stays_in_the_error_not_silently_dropped():
    f = marts._decomposition_figure(_sums(under_no_ss_pieces=100.0))
    assert f["error_pieces"] == 200.0 and f["over_share_of_error_pieces"] == 0.3


# ---- the endpoint ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")
    yield
    app.dependency_overrides.clear()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows


class _Session:
    def __init__(self, tiers, monthly, products, available=True):
        self.tiers, self.monthly, self.products, self.available, self.calls = tiers, monthly, products, available, []
        self.info: dict = {}

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append(sql)
        if "to_regclass('mart.error_decomposition')" in sql:
            return _Result(self.available)
        if "'sales' AS src" in sql:
            return _Result([{"src": "sales", "principal": "unilever", "period": "2026-02", "data_kind": "real",
                             "source_tag": None, "flow": None, "pesos": 1.0, "pieces": None, "recorded_with_tax": False,
                             "placeholder": False, "first_date": None, "last_date": None, "negative_rows": None, "products": None}])
        if "FROM mart.error_decomposition_row" in sql:
            return _Result(self.products)
        if "AND tier = 'all'" in sql:
            return _Result(self.monthly)
        if "FROM mart.error_decomposition" in sql:
            return _Result(self.tiers)
        raise AssertionError(sql)

    def close(self):
        pass


def _get(session, path):
    app.dependency_overrides[get_db] = lambda: session
    token = auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="staff", full_name="Staff")
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(token)
    with TestClient(app) as c:
        resp = c.get(path, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _product(key, beyond, tier="A"):
    return {"product_key": key, "sku_code": f"S{key}", "product_name": f"P{key}", "category_path": "C", "tier_first": tier,
            "tier_last": tier, "beyond_pieces": beyond, "beyond_pesos": beyond * 10, "exposure_months": 2, "product_months": 5,
            "absorbed_pieces": 1.0, "over_pieces": 2.0, "ss_stored_rows": 0, "ss_rebuilt_rows": 5}


def test_endpoint_returns_totals_tiers_and_the_products_ranked_by_exposure_with_concentration():
    tiers = [{"tier": t, "first_period": "2025-01", "last_period": "2026-02", **_sums()} for t in ("A", "all")]
    products = [_product(1, 50.0), _product(2, 30.0), _product(3, 10.0), _product(4, 10.0)]
    body = _get(_Session(tiers, [{"period": "2026-02", **_sums()}], products),
                "/dashboard/error-decomposition?principal=unilever&start_period=2025-01&period=2026-02&top=2")
    assert body["available"] and body["totals"]["beyond_share_of_error_pieces"] == 0.15
    assert [t["tier"] for t in body["by_tier"]] == ["A"] and body["monthly"][0]["period"] == "2026-02"
    top = body["top_products_by_stockout_exposure"]
    assert [p["product_key"] for p in top] == [1, 2] and top[0]["cumulative_share_of_beyond_pieces"] == 0.5
    c = body["stockout_exposure_concentration"]
    assert (c["products_with_exposure"], c["products_for_50_percent"], c["products_for_80_percent"]) == (4, 1, 2)
    assert "accuracy_as_served" in body["scoring_rule"] and "stored_lp" in body["safety_stock_note"]


def test_endpoint_is_blocked_for_del_monte_and_says_when_the_mart_is_missing():
    body = _get(_Session([], [], []), "/dashboard/error-decomposition?principal=delmonte")
    assert body["available"] is False and "category grain" in body["blocked_reason"]
    body = _get(_Session([], [], [], available=False), "/dashboard/error-decomposition?principal=unilever")
    assert body["available"] is False and "0063" in body["blocked_reason"]


def test_endpoint_uses_the_same_permission_as_the_accuracy_card():
    from backend.routers import dashboard_range as dr
    perms = {}
    for route in dr.router.routes:
        if route.path in ("/dashboard/accuracy", "/dashboard/error-decomposition"):
            perms[route.path] = [d.call.__qualname__ for d in route.dependant.dependencies if "permission" in d.call.__qualname__.lower()]
    assert perms["/dashboard/accuracy"] == perms["/dashboard/error-decomposition"] != []
    src = Path(dr.__file__).read_text(encoding="utf-8")
    assert src.count('require_permission("dashboard.view")') >= 2


# ---- live, read only ---------------------------------------------------------------

live = pytest.mark.skipif(not os.environ.get("SUPABASE_DB_URL"), reason="live DB not configured (SUPABASE_DB_URL unset)")


@live
def test_live_stored_tables_add_up():
    psycopg2 = pytest.importorskip("psycopg2")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        c = conn.cursor()
        c.execute("SET TRANSACTION READ ONLY")
        c.execute("SELECT to_regclass('mart.error_decomposition_row') IS NOT NULL")
        if not c.fetchone()[0]:
            pytest.skip("migration 0063 not applied")
        # the per-tier monthly rows are the sum of their product-months, the 'all' rows the sum of the tiers
        c.execute("""SELECT count(*) FROM (
                       SELECT d.tier, d.period FROM mart.error_decomposition d
                       JOIN (SELECT tier, month, count(*) n, sum(over_pieces) o, sum(beyond_pieces) b
                             FROM mart.error_decomposition_row GROUP BY tier, month) r
                         ON r.tier = d.tier AND r.month = d.period
                       WHERE d.tier <> 'all' AND (d.product_months <> r.n OR abs(d.over_pieces - r.o) > 0.001
                             OR abs(d.beyond_pieces - coalesce(r.b, 0)) > 0.001)) x""")
        assert c.fetchone()[0] == 0
        c.execute("""SELECT count(*) FROM mart.error_decomposition a
                     JOIN (SELECT period, sum(product_months) n, sum(beyond_pieces) b FROM mart.error_decomposition
                           WHERE tier <> 'all' GROUP BY period) t ON t.period = a.period
                     WHERE a.tier = 'all' AND (a.product_months <> t.n OR abs(a.beyond_pieces - t.b) > 0.001)""")
        assert c.fetchone()[0] == 0
        # absorbed + beyond = under, wherever a safety stock exists; the three parts never exceed the error
        c.execute("""SELECT count(*) FROM mart.error_decomposition_row
                     WHERE safety_stock_pieces IS NOT NULL AND abs(absorbed_pieces + beyond_pieces - under_pieces) > 0.001""")
        assert c.fetchone()[0] == 0
        c.execute("SELECT count(*) FROM mart.error_decomposition_row WHERE ss_method = 'none' AND safety_stock_pieces IS NOT NULL")
        assert c.fetchone()[0] == 0
    finally:
        conn.rollback()
        conn.close()


# ---- 0064: counterfactual runs and orphan safety stock ---------------------------------

def test_a_stored_safety_stock_must_belong_to_an_actual_lp_run():
    sql = _latest()
    assert "FROM lp_recommendation l JOIN lp_run lr ON lr.run_key = l.lp_run_key" in sql
    assert "LEFT JOIN lp_recommendation lp" not in sql


def test_tier_b_and_c_runs_are_labelled_counterfactual_in_the_script_and_the_migration():
    for name in ("as_served_calendar_B", "as_served_calendar_C"):
        label, cohort = AS_SERVED_RUNS[name]
        assert label.startswith("COUNTERFACTUAL (never served") and cohort.startswith("COUNTERFACTUAL, NOT SERVED")
    assert not AS_SERVED_RUNS["as_served_calendar"][0].startswith("COUNTERFACTUAL")
    sql = _latest()
    assert "'counterfactual', true" in sql and "Tier [BC]" in sql and "Tier A" not in sql.split("WHERE kind")[1].split(";")[0]


def test_the_accuracy_card_flags_a_counterfactual_run_and_the_decomposition_marks_tiers_b_and_c():
    from backend.routers.dashboard_range import _flag_counterfactual
    assert _flag_counterfactual({"run_labels": ["COUNTERFACTUAL (never served: x) - as-served backtest"]})["counterfactual"] is True
    served = _flag_counterfactual({"run_labels": [marts.DEFAULT_BACKTEST_LABEL]})
    assert served["counterfactual"] is False and served["counterfactual_warning"] is None
    tiers = [{"tier": t, "first_period": "2025-01", "last_period": "2026-02", **_sums()} for t in ("A", "B", "all")]
    body = _get(_Session(tiers, [], []), "/dashboard/error-decomposition?principal=unilever")
    assert {t["tier"]: t["counterfactual"] for t in body["by_tier"]} == {"A": False, "B": True}
    assert body["served_tier"] == "A" and "never served" in body["counterfactual_note"]
