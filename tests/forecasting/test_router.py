"""tests/forecasting/test_router.py - the per-bin router, the global model and
the switching rule (design locked 2026-09-21).

Pure numpy/pandas + xgboost - no DB. Series are synthetic test fixtures built
from 2023-01 onward; "placeholder" in the guard tests means months marked as
is_demo (gm.with_placeholder), not months judged by their date.
"""
from __future__ import annotations

import pathlib
import re

import numpy as np
import pandas as pd
import pytest

import scripts.model_bakeoff as mb
from analytics.forecasting import baseline, global_model as gm, router, switching
from analytics.segmentation import bins

REPO = pathlib.Path(__file__).resolve().parents[2]


def _series(values, start="2023-01-01") -> pd.Series:
    return pd.Series(np.asarray(values, float), index=pd.date_range(start, periods=len(values), freq="MS"))


def _sales(n_sales: int, n_zero: int = 0) -> pd.Series:
    """n_sales months with a sale (varying, so no guard trips by accident), then n_zero zero months."""
    rng = np.random.default_rng(n_sales)
    return _series(list(rng.integers(80, 120, n_sales).astype(float)) + [0.0] * n_zero)


def _pool(n_skus=40, months=30, seed=1) -> dict:
    rng = np.random.default_rng(seed)
    return {k: _series(rng.integers(50, 500, months).astype(float)) for k in range(n_skus)}


def _next(series: pd.Series) -> pd.Timestamp:
    return series.index[-1] + pd.DateOffset(months=1)


# ---- bins -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("n_sales, expected", [(2, "insufficient"), (3, "short"), (11, "short"), (12, "medium"),
                                               (23, "medium"), (24, "long")])
def test_bin_boundaries(n_sales, expected):
    assert router.bin_at(_sales(n_sales)) == (expected, n_sales)


def test_bin_counts_sales_months_not_calendar_span():
    assert router.bin_at(_sales(11, n_zero=20)) == ("short", 11)


def test_thresholds_come_from_segmentation_bins():
    assert (bins.LENGTH_V1_INSUFFICIENT, bins.LENGTH_V1_LONG, bins.LENGTH_V2_SEASONAL) == (3, 12, 24)
    assert "length_v2" in (REPO / "analytics/forecasting/router.py").read_text(encoding="utf-8")


# ---- served value equals the bin's live model ----------------------------------------------------------------------
def test_short_serves_ma3_with_no_backup():
    s = _sales(6)
    r = router.route(s, _next(s))
    assert (r["method"], r["backup_fired"]) == ("ma3", False)
    assert r["value"] == pytest.approx(float(baseline.moving_average_forecast(s, 1)[0]))


def test_medium_serves_tsb():
    s = _sales(15)
    r = router.route(s, _next(s))
    assert r["method"] == "tsb" and not r["backup_fired"]
    assert r["value"] == pytest.approx(float(baseline.tsb_forecast(s, 1)[0]))


def test_long_serves_average_of_xgboost_and_ma3():
    pool = _pool(); s = pool[0]; f = gm.GlobalForecaster(pool)
    r = router.route(s, _next(s), f)
    if not r["backup_fired"]:
        assert r["method"] == "xgb_ma3_avg"
        assert r["value"] == pytest.approx((r["components"]["xgb"] + r["ma3_value"]) / 2)
    assert r["training_rows"] >= gm.MIN_TRAINING_ROWS


def test_insufficient_is_not_routed_but_still_gets_ma3():
    s = _sales(2)
    r = router.route(s, _next(s))
    assert r["method"] is None and r["value"] is None and np.isfinite(r["ma3_value"])


@pytest.mark.parametrize("n_sales", [2, 5, 15, 26])
def test_ma3_value_present_for_every_bin(n_sales):
    s = _sales(n_sales)
    r = router.route(s, _next(s), gm.GlobalForecaster(_pool()))
    assert r["ma3_value"] == pytest.approx(float(s.iloc[-3:].mean()))
    assert r["components"]["ma3"] == r["ma3_value"]


# ---- one MA3 source --------------------------------------------------------------------------------------------------
def test_single_ma3_source(monkeypatch):
    """Router value, challenger benchmark and the evaluator's MA3 column all come from baseline's MA3."""
    monkeypatch.setattr(baseline, "moving_average_forecast", lambda train, horizon, window=3: np.full(horizon, 4242.0))
    for n in (5, 15):
        s = _sales(n)
        assert router.route(s, _next(s))["ma3_value"] == 4242.0
    s = _sales(15)
    scored = router.rolling_one_step(s, list(s.index[-3:]))
    assert (scored["ma3"] == 4242.0).all()


def test_no_second_ma3_implementation_in_the_new_modules():
    """Static: the router has exactly one MA3 call (baseline's) and neither it nor the evaluator averages the
    last three months itself; the evaluator's WAPE is diagnostic_metrics'. (global_model's `mean3` is an input
    feature of the XGBoost model, not an MA3 forecast or benchmark.)"""
    route_src = (REPO / "analytics/forecasting/router.py").read_text(encoding="utf-8")
    switch_src = (REPO / "analytics/forecasting/switching.py").read_text(encoding="utf-8")
    assert route_src.count("baseline.moving_average_forecast(") == 1
    for src in (route_src, switch_src):
        assert "[-3:]" not in src and ".rolling(" not in src
    assert "from analytics.forecasting.diagnostic_metrics import wape" in switch_src


def test_tsb_port_matches_the_bakeoff_implementation():
    rng = np.random.default_rng(3)
    x = rng.integers(0, 300, 30).astype(float); x[rng.integers(0, 30, 8)] = 0.0
    assert float(baseline.tsb_forecast(_series(x), 1)[0]) == pytest.approx(mb.m_tsb(x))
    assert (baseline.TSB_ALPHA_DEMAND, baseline.TSB_ALPHA_PROB) == (0.3, 0.1)


def test_tsb_is_not_an_oracle_or_rule_candidate():
    assert "tsb" not in baseline.build_forecasters(1) and "tsb" not in baseline.TIE_BREAK_ORDER
    import scripts.run_baseline_forecast as runner
    assert "tsb" not in runner.METHODS


# ---- backup triggers, one each -----------------------------------------------------------------------------------------
def test_backup_when_xgboost_has_no_model():
    s = _sales(26)
    r = router.route(s, _next(s), forecaster=None)
    assert r["method"] == "ma3" and r["backup_fired"] and r["backup_reason"].startswith("xgb_unavailable")


def test_backup_when_pool_is_too_small():
    s = _sales(26)
    r = router.route(s, _next(s), gm.GlobalForecaster({0: s}))
    assert r["method"] == "ma3" and "training rows" in r["backup_reason"]


def test_backup_when_recent_level_is_not_positive():
    s = _series(list(_sales(26)) + [0.0] * 6)
    r = router.route(s, _next(s), gm.GlobalForecaster(_pool()))
    assert r["method"] == "ma3" and r["backup_reason"].startswith("xgb_no_forecast")


def test_backup_when_training_fails(monkeypatch):
    s = _sales(26)
    f = gm.GlobalForecaster(_pool())
    monkeypatch.setattr(f, "forecast", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = router.route(s, _next(s), f)
    assert r["method"] == "ma3" and r["backup_reason"].startswith("xgb_failed: RuntimeError")


def test_backup_above_historical_maximum(monkeypatch):
    s = _sales(15)
    monkeypatch.setattr(baseline, "tsb_forecast", lambda train, horizon: np.full(horizon, float(train.max()) + 1))
    r = router.route(s, _next(s))
    assert r["method"] == "ma3" and r["backup_reason"].startswith("above_historical_max")
    assert r["value"] == pytest.approx(r["ma3_value"])


def test_backup_below_zero(monkeypatch):
    s = _sales(15)
    monkeypatch.setattr(baseline, "tsb_forecast", lambda train, horizon: np.full(horizon, -5.0))
    r = router.route(s, _next(s))
    assert r["method"] == "ma3" and r["backup_reason"].startswith("below_zero")


def test_served_ma3_is_floored_at_zero():
    s = _series([50.0, 60, 70, 10, -40, -40, -40])
    r = router.route(s, _next(s))
    assert r["method"] == "ma3" and r["value"] == 0.0 and r["ma3_value"] < 0


# ---- leakage -------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("garbage", ["zeros", "huge", "noise"])
def test_no_future_month_reaches_the_forecast(garbage):
    """Replace every month at or after the target with garbage: the forecast must be arithmetically identical."""
    pool = _pool(); target = pool[0].index[24]
    rng = np.random.default_rng(9)
    fill = {"zeros": lambda n: np.zeros(n), "huge": lambda n: np.full(n, 1e9), "noise": lambda n: rng.normal(0, 1e6, n)}[garbage]
    dirty = {}
    for k, s in pool.items():
        d = s.copy(); d[d.index >= target] = fill(int((d.index >= target).sum())); dirty[k] = d
    for bin_name in ("short", "medium", "long"):
        clean = router.route(pool[0], target, gm.GlobalForecaster(pool), force_bin=bin_name)
        leaky = router.route(dirty[0], target, gm.GlobalForecaster(dirty), force_bin=bin_name)
        assert clean["value"] == leaky["value"] and clean["components"] == leaky["components"]


def test_training_rows_stop_before_the_target_month():
    pool = _pool(n_skus=5, months=20)
    X_early, _ = gm.training_rows(pool, before=pool[0].index[10])
    X_late, _ = gm.training_rows(pool, before=pool[0].index[11])
    assert len(X_late) - len(X_early) == 5          # exactly one more month per SKU
    assert X_early.shape[1] == len(gm.FEATURE_NAMES) == 14


def test_features_are_scaled_by_the_last_six_month_mean():
    a, sa = gm.build_features(np.arange(1.0, 25.0), pd.Timestamp("2025-01-01"))
    b, sb = gm.build_features(np.arange(1.0, 25.0) * 1000, pd.Timestamp("2025-01-01"))
    assert sb == pytest.approx(sa * 1000) and np.allclose(a, b, equal_nan=True)


# ---- determinism ---------------------------------------------------------------------------------------------------------
def test_same_seed_same_output():
    pool = _pool(); t = _next(pool[0])
    v1 = gm.GlobalForecaster(pool).forecast(pool[0], t)[0]
    v2 = gm.GlobalForecaster(pool).forecast(pool[0], t)[0]
    assert v1 == v2 and gm.PARAMS["nthread"] == 1 and gm.PARAMS["objective"] == "reg:absoluteerror"


# ---- real data only -------------------------------------------------------------------------------------------------------
def test_real_rows_before_2023_are_accepted():
    """SSM's real 2021-22 files must replace the placeholder with no code change."""
    s = _series(list(_sales(15)), start="2021-06-01")
    assert router.route(s, _next(s))["value"] is not None
    pool = _pool(); pool[0] = _series(list(pool[0]), start="2021-01-01")
    gm.GlobalForecaster(pool).booster_for(pd.Timestamp("2026-03-01"))
    router.assert_real_rows(pd.DataFrame({"calendar_month": ["2021-12", "2022-12"], "quantity": [1.0, 2.0], "is_demo": [False, False]}))


def _placeholder(series: pd.Series, n: int = 6) -> pd.Series:
    return gm.with_placeholder(series, series.index[:n])


def test_placeholder_rows_are_rejected_by_default():
    s = _placeholder(_series(list(_sales(15)), start="2022-01-01"))
    with pytest.raises(ValueError, match="placeholder"):
        router.route(s, _next(s))
    pool = _pool(); pool[0] = _placeholder(pool[0])
    with pytest.raises(ValueError, match="placeholder"):
        gm.GlobalForecaster(pool).booster_for(pd.Timestamp("2026-03-01"))
    with pytest.raises(ValueError, match="placeholder"):
        router.route(pool[0], _next(pool[0]), gm.GlobalForecaster(_pool()), force_bin="long")
    frame = pd.DataFrame({"calendar_month": ["2024-01", "2024-02"], "quantity": [1.0, 2.0], "is_demo": [False, True]})
    with pytest.raises(ValueError, match="is_demo"):
        router.assert_real_rows(frame)
    with pytest.raises(ValueError, match="is_placeholder"):
        router.assert_real_rows(frame.drop(columns="is_demo").assign(is_placeholder=[True, False]))


def test_placeholder_rows_pass_only_with_the_flag():
    s = _placeholder(_series(list(_sales(15)), start="2022-01-01"))
    assert router.route(s, _next(s), allow_placeholder=True)["value"] is not None
    pool = _pool(); pool[0] = _placeholder(pool[0])
    f = gm.GlobalForecaster(pool, allow_placeholder=True)
    r = router.route(pool[0], _next(pool[0]), f, force_bin="long", allow_placeholder=True)
    assert r["components"]["xgb"] is not None and r["backup_reason"] is None
    router.assert_real_rows(pd.DataFrame({"calendar_month": ["2021-01"], "quantity": [1.0], "is_demo": [True]}), allow_placeholder=True)


def test_placeholder_mark_outside_the_series_does_not_trip():
    s = _series(list(_sales(15)), start="2024-01-01")
    marked = gm.with_placeholder(s, [pd.Timestamp("2021-01-01")])
    assert router.route(marked, _next(marked))["value"] == router.route(s, _next(s))["value"]


def test_router_default_path_is_unchanged():
    """The flag defaults to False everywhere, the live runner never passes it, and only the preview script and the what-if simulation set it."""
    import ast, inspect
    for fn in (router.route, router.rolling_one_step, router.assert_real_rows, gm.assert_real_history,
               gm.training_rows, gm.GlobalForecaster.__init__):
        assert inspect.signature(fn).parameters["allow_placeholder"].default is False
    assert "allow_placeholder" not in (REPO / "scripts/run_baseline_forecast.py").read_text(encoding="utf-8")

    def passes_true(path) -> bool:          # a call site passing allow_placeholder=True (docstrings don't count)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            return False
        return any(isinstance(n, ast.keyword) and n.arg == "allow_placeholder" and isinstance(n.value, ast.Constant)
                   and n.value.value is True for n in ast.walk(tree))
    setters = sorted(p.relative_to(REPO).as_posix() for p in REPO.glob("**/*.py")
                     if not {".venv", "node_modules", "tests"} & set(p.relative_to(REPO).parts) and passes_true(p))
    # The sanctioned placeholder users: the app's preview build, and Kelvin's
    # 2021-22 what-if simulation (exp/fit-and-simulation, 2026-10-02), which
    # reads in a READ ONLY transaction and writes only report files. Neither
    # touches Forecast_Result; the live runner stays off this list.
    assert setters == ["reports/simulation/synthetic_2026-10/run_simulation.py", "scripts/preview_router_synth.py"]
    s = _sales(30); pool = _pool()
    assert router.route(s, _next(s), gm.GlobalForecaster(pool)) == router.route(s, _next(s), gm.GlobalForecaster(pool), allow_placeholder=False)


def test_every_fact_table_read_ends_in_real():
    files = [REPO / "scripts/run_baseline_forecast.py"] + [REPO / "analytics/forecasting" / n
                                                           for n in ("router.py", "switching.py", "global_model.py")]
    for path in files:
        src = path.read_text(encoding="utf-8")
        for table in re.findall(r"(?:FROM|JOIN)\s+([A-Za-z_]*_Fact[A-Za-z_]*)", src, flags=re.I):
            assert table.lower().endswith("_real"), f"{path.name} reads {table}"
    for n in ("router.py", "switching.py", "global_model.py"):
        assert "psycopg2" not in (REPO / "analytics/forecasting" / n).read_text(encoding="utf-8")


# ---- switching rule ---------------------------------------------------------------------------------------------------------
def _scored(chall_err: float, ma3_err: float, n_skus=30, months=6, jitter=0.0):
    rng = np.random.default_rng(5); rows = []
    for k in range(n_skus):
        for m in pd.date_range("2025-09-01", periods=months, freq="MS"):
            j = rng.normal(0, jitter)
            rows.append({"product_key": k, "month": m, "actual": 100.0, "challenger": 100 + chall_err + j, "ma3": 100 + ma3_err - j})
    return pd.DataFrame(rows)


def test_switch_reverts_only_when_ma3_clears_the_bar():
    out = switching.evaluate_switch(_scored(chall_err=40, ma3_err=10, jitter=2), pd.Timestamp("2026-02-01"))
    assert out["revert_to_ma3"] and out["diff_ci"][0] > 0 and out["skus_better_under_ma3"] > out["skus_better_under_challenger"]


def test_switch_keeps_the_challenger_on_a_tie():
    out = switching.evaluate_switch(_scored(chall_err=10, ma3_err=10, jitter=5), pd.Timestamp("2026-02-01"))
    assert not out["revert_to_ma3"] and out["diff_ci"][0] <= 0 <= out["diff_ci"][1]


def test_switch_keeps_the_challenger_when_it_is_better():
    assert not switching.evaluate_switch(_scored(10, 40, jitter=2), pd.Timestamp("2026-02-01"))["revert_to_ma3"]


def test_switch_reads_only_the_six_month_window():
    old = _scored(chall_err=90, ma3_err=0).assign(month=lambda d: d["month"] - pd.DateOffset(months=12))
    out = switching.evaluate_switch(pd.concat([old, _scored(10, 10, jitter=5)]), pd.Timestamp("2026-02-01"))
    assert not out["revert_to_ma3"] and switching.WINDOW_MONTHS == 6 and out["n_skus"] == 30


def test_switch_does_nothing_with_too_few_skus():
    out = switching.evaluate_switch(_scored(40, 10, n_skus=3), pd.Timestamp("2026-02-01"))
    assert not out["revert_to_ma3"] and out["diff_ci"] is None


def test_months_before_the_first_sale_do_not_reach_tsb():
    launched = _sales(15)
    padded = _series([0.0] * 10 + list(launched), start="2023-01-01")
    launched = _series(list(launched), start=str(padded.index[10].date()))
    assert router.route(padded, _next(padded))["value"] == pytest.approx(router.route(launched, _next(launched))["value"])


def test_runner_refuses_a_scratch_search_path_on_the_pooled_url():
    from scripts.run_baseline_forecast import refuse_pooled_scratch
    pooled, direct = "postgresql://u:p@aws-0.pooler.supabase.com:6543/postgres", "postgresql://u:p@db.x.supabase.co:5432/postgres"
    default = '"$user", public, extensions'
    with pytest.raises(RuntimeError, match="ssm_forecast_p3"):
        refuse_pooled_scratch(pooled, "ssm_forecast_p3, public")
    refuse_pooled_scratch(pooled, default)                          # normal start on the pooler
    refuse_pooled_scratch(direct, "ssm_forecast_p3, public")        # scratch rehearsal on the direct URL
    refuse_pooled_scratch(direct, default)
