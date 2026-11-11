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
# 0064's run relabelling (its UPDATE), and the function as last defined: the newest migration that (re)creates it
M0064 = REPO / "analytics" / "db" / "migrations" / "0064_error_decomposition_counterfactual_and_orphans.sql"
LATEST = max(p for p in (REPO / "analytics" / "db" / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")
             if "FUNCTION mart.refresh_error_decomposition(" in p.read_text(encoding="utf-8"))


def _sql() -> str:
    return "\n".join(l for l in MIGRATION.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))


def _latest() -> str:
    return "\n".join(l for l in LATEST.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))


def _m0064() -> str:
    return "\n".join(l for l in M0064.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))


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
    counts = amarts.refresh_marts_cursor(cur, "load")
    # the other marts' counts stand, and the failure is in the result, not only on stdout (2026-11-11)
    assert {k: v for k, v in counts.items() if k != "error_decomposition_failed"} == {"sales_mart": 1, "planning_mart": 3}
    assert counts["error_decomposition_failed"]
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
        self.stamps = {"decomposition_refreshed_at": None, "marts_refreshed_at": None}

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append(sql)
        if "to_regclass('mart.error_decomposition')" in sql:
            return _Result(self.available)
        if "decomposition_refreshed_at" in sql:
            return _Result([self.stamps])
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


def test_error_decomposition_routes_need_lp_view_and_dashboard_view_unlike_the_accuracy_card():
    """The accuracy card is dashboard.view alone. The four error-decomposition routes read the stored LP safety stock
    (ss_i), so each carries TWO permission dependencies, dashboard.view AND lp.view, and require_permission passes any
    one of the keys it is given, so two single-key dependencies are what makes it AND. Removing either one fails here."""
    from backend.routers import dashboard_range as dr

    def keys(route):
        return sorted(k for d in route.dependant.dependencies if hasattr(d.call, "permission_keys") for k in d.call.permission_keys)

    by_path = {route.path: keys(route) for route in dr.router.routes if hasattr(route, "dependant")}
    assert by_path["/dashboard/accuracy"] == ["dashboard.view"]
    decomposition = {p: k for p, k in by_path.items() if p.startswith("/dashboard/error-decomposition")}
    assert len(decomposition) == 4
    for path, got in decomposition.items():
        assert got == ["dashboard.view", "lp.view"], f"{path} carries {got}"


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
    sql = _m0064()
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


# ---- 0077: the rebuilt safety stock follows the level, as the plan's does ------------------------------------------

def test_the_latest_body_is_0077_and_scales_rebuilt_safety_stock_for_zero_and_treated_forecasts():
    assert LATEST.name.startswith("0077_")
    sql = _latest()
    # the same set as scripts/run_lp.TREATMENT_QUERY: a zero forecast, or succession / fading
    assert "fc.forecast_pieces = 0 OR fc.treatment IN ('succession', 'fading')" in sql
    # run_lp.level_factor: min(1, forecast / mean), never below 0, 1 when the history has no positive mean
    assert "LEAST(1::numeric, GREATEST(0::numeric, fc.forecast_pieces / rb.level_mean))" in sql
    assert "CASE WHEN n >= 1 AND s1 > 0 THEN s1 / n END AS level_mean" in sql
    assert "rb.ss * COALESCE(lv.factor, 1) AS ss_rebuilt" in sql
    # a stored plan figure already carries the plan's scaling: the factor is recorded only on rebuilt rows
    assert "CASE WHEN ss_stored IS NULL THEN level_factor END" in sql
    # same signature: every caller and DECOMPOSITION_SIGNATURE unchanged
    assert "p_trigger text DEFAULT 'manual'" in sql and amarts.DECOMPOSITION_SIGNATURE == "refresh_error_decomposition(text,numeric,integer,text)"


def test_the_decomposition_rule_is_held_to_the_plan_setting():
    """0077 hard-codes the 'treated' rule: a different analytics.params.SAFETY_STOCK_FOLLOWS_LEVEL needs a migration."""
    from analytics.params import SAFETY_STOCK_FOLLOWS_LEVEL
    from scripts.run_lp import TREATMENT_QUERY
    assert SAFETY_STOCK_FOLLOWS_LEVEL == "treated"
    assert "IN ('succession', 'fading') OR forecast_value = 0" in TREATMENT_QUERY


def test_the_sql_level_mean_is_run_lp_level_factor():
    """The SQL's mean (positive quantity over the observed months strictly before the month) against the Python one."""
    import pandas as pd
    from scripts.run_lp import level_factor
    hist = {"2025-01": 900.0, "2025-02": None, "2025-04": -50.0, "2025-05": 300.0}   # 2025-03 has no row (= 0), 02 blank
    df = pd.DataFrame({"period": list(hist), "total_quantity": [float("nan") if v is None else v for v in hist.values()]})
    q = [900.0, 0.0, 0.0, 300.0]          # the grid: blank out, no row = 0, net-negative = 0
    mean = sum(q) / len(q)
    for forecast in (0.0, 120.0, 5000.0):
        assert level_factor(df, forecast, "2025-05") == max(0.0, min(1.0, forecast / mean))


def test_new_runs_record_the_treatment_and_the_backfill_checks_against_the_untreated_twin():
    src = (REPO / "scripts" / "accuracy_as_served.py").read_text(encoding="utf-8")
    assert "ma3_pieces, backup_fired, treatment) VALUES %s" in src
    assert '"treatment": r.get("treatment")' in src
    assert "label.replace(TREATED, \"\")" in src and "differs_unflagged" in src and "not_fixed_point" in src


def test_treatment_flags_are_the_names_apply_gives_and_a_treated_value_is_a_fixed_point():
    import pandas as pd
    from analytics.forecasting.treatments import ProductContext
    from scripts.accuracy_as_served import treatment_flags
    idx = pd.date_range("2024-01-01", periods=14, freq="MS")
    s = pd.Series([1000.0] * 11 + [100.0, 80.0, 60.0], index=idx)      # collapsed: fading fires for 2025-03
    ctx = ProductContext(promo_name=False, successor_first_sales=())
    rows = pd.DataFrame({"product_key": [1], "month": ["2025-03"], "forecast_pieces": [80.0], "status": ["ok"]})
    out = treatment_flags(rows, {1: s}, {1: ctx})
    assert out.treatment.iloc[0] == "fading" and out.reapplied.iloc[0] == 80.0   # min(80, mean of the last 3 = 80)
    assert treatment_flags(rows, {1: s}, {}).treatment.iloc[0] is None          # no context: never treated


# ---- a failed refresh is visible in every answer -------------------------------------------------------------------

def test_a_split_older_than_the_last_full_refresh_is_served_as_stale():
    import datetime as dt
    tiers = [{"tier": t, "first_period": "2025-01", "last_period": "2026-02", **_sums()} for t in ("A", "all")]
    s = _Session(tiers, [], [])
    old, new = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc), dt.datetime(2026, 11, 11, tzinfo=dt.timezone.utc)
    s.stamps = {"decomposition_refreshed_at": old, "marts_refreshed_at": new}
    body = _get(s, "/dashboard/error-decomposition?principal=unilever")
    assert body["freshness"]["stale"] is True and "did not rebuild this split" in body["freshness"]["stale_reason"]
    s.stamps = {"decomposition_refreshed_at": new, "marts_refreshed_at": new}
    body = _get(s, "/dashboard/error-decomposition?principal=unilever&period=2026-01")
    assert body["freshness"]["stale"] is False and body["freshness"]["stale_reason"] is None
