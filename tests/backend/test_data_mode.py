"""
tests/backend/test_data_mode.py — PREVIEW mode (backend/data_mode.py).

Three promises, each pinned here:
  1. Real mode is the app as it was: the header is optional, and the demand
     relation is the _Real view's own name, so real-mode SQL is unchanged.
  2. Preview only ever adds placeholder months BEFORE the first real month,
     and writes nothing.
  3. The on-request ABC tiers and SKU traits are the pipeline's own: run on
     REAL months they reproduce the stored ABC_Classification and sku_traits.
     That is what makes the placeholder months' figures trustworthy as "what
     our formulas say about this data".

The live tests read the database (read-only) and skip when SUPABASE_DB_URL
is unset, like tests/test_abc_schema_contract.py.
"""
from __future__ import annotations

import ast
import inspect
import math
import os
import re

import pandas as pd
import pytest
from dotenv import load_dotenv
from fastapi import HTTPException
from fastapi.testclient import TestClient

from analytics.classification.abc import classify_abc
from backend import data_mode as dm
from backend.auth_utils import TokenPayload
from backend.deps import get_current_user
from backend.main import app

load_dotenv()
LIVE = pytest.mark.skipif(not os.environ.get("SUPABASE_DB_URL"), reason="live DB not configured (SUPABASE_DB_URL unset)")


# ---- 1. the switch -------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "", "real", "REAL", " real "])
def test_absent_or_real_header_is_real_mode(value):
    assert dm.get_data_mode(value) == dm.REAL


@pytest.mark.parametrize("value", ["preview", "Preview", " PREVIEW "])
def test_preview_header_is_preview_mode(value):
    assert dm.get_data_mode(value) == dm.PREVIEW


def test_unknown_mode_is_a_400_not_a_silent_real_page():
    with pytest.raises(HTTPException) as exc:
        dm.get_data_mode("synthetic")
    assert exc.value.status_code == 400


def test_real_mode_reads_the_real_view_by_its_own_name():
    """The routers' FakeSession tests match SQL text on this exact name, and
    the real-mode snapshot diff (2026-09-23) relies on it being verbatim."""
    assert dm.unilever_demand(dm.REAL) == "Unilever_SKU_Demand_Fact_Real"


def test_preview_adds_only_placeholder_rows_before_the_first_real_month():
    sql = dm.unilever_demand(dm.PREVIEW)
    assert "is_demo = false" in sql
    assert "is_demo = true AND calendar_month < (SELECT MIN(calendar_month) FROM Unilever_SKU_Demand_Fact_Real)" in sql
    # No other way in for a placeholder row: exactly one is_demo = true term.
    assert sql.count("is_demo = true") == 1


def test_data_mode_module_never_writes():
    """Every string in the module's code (its SQL), docstrings aside, is
    free of a write verb."""
    tree = ast.parse(inspect.getsource(dm))
    docstrings = {
        id(node.body[0].value) for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef)) and node.body
        and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }
    code_strings = " ".join(
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    )
    assert "SELECT" in code_strings  # the scan is actually reading the SQL
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|CREATE|DROP|ALTER)\b", code_strings, re.I)


def test_placeholder_months_honours_the_window_and_the_bound():
    window = {"start": "2021-01", "end": "2022-12"}
    assert len(dm.placeholder_months(window)) == 24
    assert dm.placeholder_months(window, through="2021-03") == ["2021-01", "2021-02", "2021-03"]
    assert dm.placeholder_months(window, through="2020-12") == []
    assert dm.placeholder_months(None) == []
    assert dm.is_placeholder_period("2022-12", window) and not dm.is_placeholder_period("2023-01", window)


# ---- 2. ABC steps, offline --------------------------------------------------------

class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeDemand:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, clause, params=None):
        return _Rows([r for r in self.rows if r["period"] in params["months"]])


def test_abc_single_excludes_null_negative_and_zero_then_classifies():
    rows = [
        {"product_key": 1, "period": "2022-01", "net_amount": 700.0},
        {"product_key": 2, "period": "2022-01", "net_amount": 200.0},
        {"product_key": 3, "period": "2022-01", "net_amount": 100.0},
        {"product_key": 4, "period": "2022-01", "net_amount": None},   # NULL: excluded, not zeroed
        {"product_key": 5, "period": "2022-01", "net_amount": -50.0},  # negative: clamped then excluded
        {"product_key": 6, "period": "2022-01", "net_amount": 0.0},    # zero: inactive, no tier
        {"product_key": 7, "period": "2022-02", "net_amount": 10.0},   # another month
    ]
    out = dm.abc_single(_FakeDemand(rows), ["2022-01"], dm.PREVIEW)
    assert list(out["product_key"]) == [1, 2, 3]
    expected = classify_abc(pd.DataFrame({"sku_id": [1, 2, 3], "total_revenue": [700.0, 200.0, 100.0]}))
    assert list(out["tier"]) == list(expected["tier"]) == ["A", "B", "C"]
    assert list(out["revenue_share"]) == pytest.approx([0.7, 0.2, 0.1])
    assert set(out["classification_period"]) == {"2022-01"}
    assert set(out["method"]) == {"single"} and set(out["principal"]) == {"unilever"}


def test_abc_single_month_with_no_positive_revenue_yields_nothing():
    rows = [{"product_key": 1, "period": "2022-01", "net_amount": -5.0}]
    assert dm.abc_single(_FakeDemand(rows), ["2022-01"], dm.PREVIEW).empty


def test_latest_per_product_keeps_each_products_newest_month():
    df = pd.DataFrame({"product_key": [1, 1, 2], "classification_period": ["2021-01", "2022-05", "2021-07"],
                       "tier": ["C", "A", "B"]})
    out = dm.latest_per_product(df).set_index("product_key")
    assert out.loc[1, "classification_period"] == "2022-05" and out.loc[1, "tier"] == "A"
    assert out.loc[2, "classification_period"] == "2021-07"


# ---- 3. live: the pipeline's own outputs, reproduced --------------------------------

@pytest.fixture(scope="module")
def live_db():
    from sqlalchemy.orm import Session

    from backend.deps import _get_engine
    session = Session(_get_engine())
    yield session
    session.rollback()
    session.close()


@LIVE
def test_on_request_abc_reproduces_every_stored_unilever_run(live_db):
    from sqlalchemy import text
    stored = pd.DataFrame(live_db.execute(text("""
        SELECT product_key, classification_period, tier, revenue_share::float8 AS rs,
               cumulative_share::float8 AS cs, boundary_flag
        FROM ABC_Classification WHERE method = 'single' AND principal = 'unilever'
    """)).mappings().all())
    months = sorted(stored["classification_period"].unique())
    computed = dm.abc_single(live_db, months, dm.REAL)
    m = stored.merge(computed, on=["product_key", "classification_period"], how="outer", indicator=True)
    assert (m["_merge"] == "both").all(), "a product ranked in one and not the other"
    assert (m["tier_x"] == m["tier_y"]).all()
    assert (m["boundary_flag_x"] == m["boundary_flag_y"]).all()
    # Stored shares are NUMERIC(7,4); the computed ones are unrounded floats.
    assert (m["rs"] - m["revenue_share"].astype(float)).abs().max() <= 0.00005
    assert (m["cs"] - m["cumulative_share"].astype(float)).abs().max() <= 0.00005


@LIVE
def test_on_request_traits_reproduce_the_stored_segmentation_run(live_db):
    from sqlalchemy import text
    stored = live_db.execute(text("""
        SELECT product_key, history_months, first_sale_period, longest_run, trend, restart_flag,
               cv::float8 AS cv, adi::float8 AS adi
        FROM sku_traits WHERE cohort_period = '2026-02' AND abc_method = 'single'
    """)).mappings().all()
    matrices, periods = dm.demand_matrix(live_db, [r["product_key"] for r in stored], "2023-01", "2026-02", dm.REAL)
    for r in stored:
        got = dm.series_traits(matrices[r["product_key"]], periods)
        for col in ("history_months", "first_sale_period", "longest_run", "trend", "restart_flag"):
            assert got[col] == r[col], (r["product_key"], col)
        for col in ("cv", "adi"):
            if r[col] is None:
                assert got[col] is None
            else:
                assert math.isclose(got[col], r[col], rel_tol=1e-9), (r["product_key"], col)


@LIVE
def test_placeholder_window_ends_before_the_first_real_month(live_db):
    window = dm.placeholder_window(live_db)
    if window is None:
        pytest.skip("no placeholder rows before the real data — real history already covers them")
    assert window["end"] < window["first_real_month"]


@LIVE
def test_category_trends_preview_lengthens_history_without_moving_a_projection():
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(
        user_id=1, email="t@local", role="staff", full_name="T")
    try:
        client = TestClient(app)
        real = client.get("/category-trends?principal=unilever").json()
        preview = client.get("/category-trends?principal=unilever", headers={dm.DATA_MODE_HEADER: "preview"}).json()
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert "data_mode" not in real
    assert preview["data_mode"]["mode"] == "preview"
    r, p = real["principals"][0], preview["principals"][0]
    assert len(p["observed_months"]) > len(r["observed_months"])
    strip = lambda c: {k: v for k, v in c.items() if k != "history"}  # noqa: E731
    assert {c["category"]: strip(c) for c in p["categories"]} == {c["category"]: strip(c) for c in r["categories"]}


# ---- 4. file-backed forecasts and LP (scripts/build_preview_outputs.py) ------------

def test_sources_pass_the_real_name_through_in_real_mode():
    assert dm.forecast_source(dm.REAL, "forecast_result") == ("forecast_result", {})
    assert dm.lp_source(dm.REAL, "lp_recommendation") == ("lp_recommendation", {})
    assert dm.predictive_preview(dm.REAL) is False


def test_preview_without_built_files_falls_back_to_the_real_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "PREVIEW_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(dm, "_outputs_cache", {"stamp": None, "value": None})
    assert dm.preview_outputs() is None
    assert dm.predictive_preview(dm.PREVIEW) is False
    assert dm.forecast_source(dm.PREVIEW) == ("Forecast_Result", {})
    assert dm.lp_source(dm.PREVIEW) == ("LP_Recommendation", {})


def test_preview_files_become_typed_relations_with_every_column(tmp_path, monkeypatch):
    (tmp_path / "app_forecast.csv").write_text(
        "product_key,forecast_date,forecast_value,confidence_lower,confidence_upper,mape,mase,status,model_params\n"
        '1,2026-03-01,10.5,8.0,13.0,12.5,0.7,ok,"{""method"": ""ma3""}"\n'
        "2,2026-03-01,3.0,,,,,insufficient_data,{}\n", encoding="utf-8")
    (tmp_path / "app_lp.csv").write_text(
        "product_key,planning_cycle_date,q_i,rop_i,ss_i\n1,2026-03-01,12.0,12.0,1.5\n", encoding="utf-8")
    (tmp_path / "app_meta.json").write_text('{"built_at": "2026-09-24T00:00:00+00:00"}', encoding="utf-8")
    monkeypatch.setattr(dm, "PREVIEW_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(dm, "_outputs_cache", {"stamp": None, "value": None})
    assert dm.predictive_preview(dm.PREVIEW) is True
    fc, fc_params = dm.forecast_source(dm.PREVIEW)
    for col in ("forecast_key", "product_key", "forecast_date", "forecast_value", "confidence_lower",
                "confidence_upper", "mape", "model_params", "generated_at", "mase", "status"):
        assert col in fc
    assert fc_params["pv_fc_keys"] == [1, 2] and fc_params["pv_fc_lower"] == [8.0, None]
    assert fc_params["pv_fc_status"] == ["ok", "insufficient_data"]
    lp, lp_params = dm.lp_source(dm.PREVIEW)
    assert "-u.product_key AS recommendation_key" in lp and "'pending'::text AS status" in lp
    assert lp_params["pv_lp_ss"] == [1.5] and lp_params["pv_generated_at"] == "2026-09-24T00:00:00+00:00"


def test_outputs_stale_compares_the_build_fingerprint_with_the_live_placeholder():
    """The what-if files were built 2026-09-23 on the v1 placeholder; the
    2026-09-28 cutover replaced it and nothing said so."""
    from backend.data_mode import _outputs_stale

    built = {"meta": {"placeholder_window": {"rows": 1954, "quantity_total": 1000.0}}}
    assert _outputs_stale(built, {"rows": 8444, "quantity_total": 5000.0}) is True
    assert _outputs_stale(built, {"rows": 1954, "quantity_total": 1000.0}) is False
    assert _outputs_stale(built, {"rows": 1954, "quantity_total": 1234.0}) is True
    # Files built before the fingerprint existed, or no files at all: unknown.
    assert _outputs_stale({"meta": {}}, {"rows": 8444, "quantity_total": 1.0}) is None
    assert _outputs_stale(None, {"rows": 8444, "quantity_total": 1.0}) is None
