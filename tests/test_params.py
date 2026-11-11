"""
tests/test_params.py — pins every value in analytics/params.py.

A change to any parameter has to change this file too, in the same commit,
so it can't happen by accident or without a reviewer seeing the number move.
"""
from __future__ import annotations

import ast
import math
import sys
from pathlib import Path
from statistics import NormalDist

import pytest

from analytics import params

REPO = Path(__file__).resolve().parents[1]

PINNED = {
    "MASE_GATE": 1.0,
    "FIT_REVIEW_NOT_FIT_MASE": 1.1,
    "FIT_REVIEW_BORDERLINE_MASE": 0.9,
    "FIT_REVIEW_HIGH_VOL_CV": 0.4365,
    "HOLDOUT_FRACTION": 0.20,
    "FORECAST_INTERVAL_Z": 1.645,
    "FORECAST_INTERVAL_LEVEL_PCT": 90,
    "MIN_MONTHS_WITH_SALES": 3,
    "DEAD_SKU_MONTHS": 6,
    "POSSIBLY_PARTIAL_COUNTS": ("2025-05",),
    "STOCK_LIMITED_WEEKS": 1.0,
    "STOCK_LIMITED_AVG_MONTHS": 12,
    "STOCK_LIMITED_AVG_MIN_MONTHS": 3,
    "SBC_ADI_CUT": 1.32,
    "SBC_CV2_CUT": 0.49,
    "XYZ_CV_LOW": 0.5,
    "XYZ_CV_HIGH": 1.0,
    "FSN_WINDOW_MONTHS": 12,
    "FSN_MIN_FAST_SALES_MONTHS": 3,
    "TIER_A_BASIS": "t12m_new",
    "TIER_A_BASES": ("single", "t12m_new"),
    "TIER_A_BASIS_WINDOW_MONTHS": 12,
    "TIER_A_NEW_PRODUCT_WINDOW_MONTHS": 3,
    "XGB_NTHREAD": 1,
    "CALENDAR_FACTOR_SHRINK": 0.5,
    "CALENDAR_FACTOR_PRIOR_MONTHS": 3,
    "CALENDAR_FACTOR_SIGNED_OFF": False,
    "REVIEW_COLLAPSE_RATIO": 0.5,
    "REVIEW_COLLAPSE_RECENT_MONTHS": 3,
    "REVIEW_COLLAPSE_BASE_MONTHS": 12,
    "REVIEW_OVER_RUN_MONTHS": 3,
    "REVIEW_LOOKBACK_MONTHS": 6,
    "YEARLY_ACF_MIN_MONTHS": 24,
    "YEARLY_ACF_Z": 1.96,
    "LP_WEIGHTS": {"cost": 0.45, "service_level": 0.35, "storage": 0.20},
    "SERVICE_Z": 1.28,
    "CALENDAR_FACTOR_SHRINK": 0.5,
    "CALENDAR_FACTOR_PRIOR_MONTHS": 3,
    "SERVICE_LEVEL_PCT": 90,
    "DAYS_PER_MONTH": 365.25 / 12,
    "WEEKS_PER_MONTH": 365.25 / 12 / 7,
    "BUSINESS_DAYS_PER_WEEK": 5,
    "POLICY_COVER_WEEKS": 3,
    "COVER_KPI_HISTORY_MONTHS": 12,
    "SKU_COVER_HISTORY_MONTHS": 3,
    "ALLOCATION_LEVELS_PCT": (103, 105, 108),
    "ALLOCATION_DEFAULT_PCT": 103,
    "ALLOCATION_UNITS": ("pieces", "pesos"),
    "COVER_RULES": ("aggregate", "per-sku"),
    "PLACEHOLDERS": {
        "allocation_pct": 103.0,
        "review_days": 5.0,
        "lead_days": 3.0,
        "target_weeks": 3.0,
        "cover_rule": "aggregate",
        "warehouse_capacity": 3_816_842.0,
        "default_procurement_cost_per_unit": 33.48,
        "storage_cost_per_unit": 0.50,
    },
    # Succession + fading, served 2026-11-10 (analytics/forecasting/treatments.py; rules committed at f3ffe47).
    "SERVE_SUCCESSION": True,
    "SERVE_FADING": True,
    "SUCCESSION_DROP": 0.5,
    "SUCCESSION_NEW_CODE_MONTHS": 3,
    "SUCCESSION_CONTENT_TOL": 0.10,
    "LOW_PIECES_6M": 500,
    # Safety stock follows the level for treated products, decided 2026-11-10 (scripts/run_lp.level_factor).
    "SAFETY_STOCK_FOLLOWS_LEVEL": "treated",
}


def _public_names() -> set[str]:
    return {n for n in vars(params) if n.isupper() and not n.startswith("_")}


@pytest.mark.parametrize("name", sorted(PINNED))
def test_value_is_pinned(name):
    assert getattr(params, name) == PINNED[name], name


def test_every_parameter_is_pinned():
    """A new parameter must be added to PINNED; SAFETY_STOCK_ASSUMPTION is
    text built from SERVICE_Z and is checked on its own below."""
    assert _public_names() - {"SAFETY_STOCK_ASSUMPTION"} == set(PINNED)


def test_derived_values_hold_together():
    assert math.isclose(sum(params.LP_WEIGHTS.values()), 1.0)
    assert round(NormalDist().cdf(params.SERVICE_Z) * 100) == params.SERVICE_LEVEL_PCT
    assert round(NormalDist().cdf(params.FORECAST_INTERVAL_Z) * 100) == 95  # one-sided 95 = two-sided 90
    assert params.FIT_REVIEW_BORDERLINE_MASE < params.MASE_GATE < params.FIT_REVIEW_NOT_FIT_MASE
    assert params.XYZ_CV_LOW < params.XYZ_CV_HIGH
    assert params.PLACEHOLDERS["target_weeks"] == params.POLICY_COVER_WEEKS
    assert params.PLACEHOLDERS["cover_rule"] in params.COVER_RULES
    assert f"{params.SERVICE_Z:g} ×" in params.SAFETY_STOCK_ASSUMPTION
    assert "independent" in params.SAFETY_STOCK_ASSUMPTION


def test_standard_library_only():
    """The always-on API imports this module: no pulp, xgboost, pandas."""
    tree = ast.parse((REPO / "analytics" / "params.py").read_text(encoding="utf-8"))
    imported = {
        (node.module or "").split(".")[0] if isinstance(node, ast.ImportFrom) else alias.name.split(".")[0]
        for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported <= {"__future__"} | set(sys.stdlib_module_names)


def test_one_mase_gate_everywhere():
    """Item 2: the LP's candidate pool, the dashboard's reliability count and
    the runner's pass rates share analytics.params.MASE_GATE; none defines
    its own. The fit review's 1.1 is a separate, named review flag."""
    from analytics.forecasting import baseline
    from backend.routers import dashboard
    from scripts import run_lp

    assert run_lp.MASE_GATE is dashboard.MASE_GATE is baseline.MASE_GATE is params.MASE_GATE
    assert not hasattr(dashboard, "MASE_UNRELIABLE_GATE")
    assert params.FIT_REVIEW_NOT_FIT_MASE != params.MASE_GATE


def test_three_volatility_measures_three_names():
    """Item 3: sku_traits.cv's XYZ bands (bins and the segment API share
    them), SBC's CV² of non-zero sizes, and the fit review's CV(last 12) are
    different measures with different names — never one threshold reused."""
    from analytics.forecasting import baseline
    from analytics.segmentation import bins
    from backend.routers import segment

    assert (bins.VOLATILITY_V1_LOW, bins.VOLATILITY_V1_HIGH) == (params.XYZ_CV_LOW, params.XYZ_CV_HIGH)
    assert (segment.CV_BAND_MEDIUM, segment.CV_BAND_HIGH) == (params.XYZ_CV_LOW, params.XYZ_CV_HIGH)
    assert baseline._CV2_CUT == params.SBC_CV2_CUT
    for cv in (0.49, 0.5, 0.99, 1.0, 1.5):
        assert segment.cv_band(cv) == bins.volatility_v1(12, cv)[0]


def test_two_cover_windows_both_end_at_the_stock_snapshot():
    """Item 10: 12 months for the dashboard's weeks-of-cover KPI, 3 for the
    Reorder page's per-SKU days of cover — named apart, and the per-SKU one
    anchored to the stock snapshot month instead of the table's latest months."""
    from backend.routers import dashboard, recommendations

    assert (params.COVER_KPI_HISTORY_MONTHS, params.SKU_COVER_HISTORY_MONTHS) == (12, 3)
    sql = " ".join(recommendations._SELECT_ONE.split())
    assert sql.count("WHERE calendar_month <= :inv_period ORDER BY calendar_month DESC LIMIT 3") == 2
    assert dashboard.POLICY_WEEKS is params.POLICY_COVER_WEEKS
    assert dashboard.AVG_WEEKS_PER_MONTH is params.WEEKS_PER_MONTH
    assert recommendations.AVG_DAYS_PER_MONTH is params.DAYS_PER_MONTH


def _module_level_assignments(path: Path) -> set[str]:
    names = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        names |= {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    return names


def test_no_module_redefines_a_parameter():
    """Item 11: a module may import a parameter, never assign one itself.
    Archived scripts and frozen experiment artifacts are out of scope."""
    offenders = []
    for root in ("analytics", "backend", "scripts", "tools"):
        for path in (REPO / root).rglob("*.py"):
            rel = path.relative_to(REPO).as_posix()
            if "/archive/" in rel or rel == "analytics/params.py":
                continue
            offenders += [f"{rel}: {n}" for n in sorted(_module_level_assignments(path) & _public_names())]
    assert offenders == []


def test_every_alias_is_the_parameter_itself():
    """Item 11: the old local names stay (callers and tests use them) but are
    the params objects, so a retyped literal can't slip back in unnoticed."""
    from analytics.classification import fsn
    from analytics.forecasting import baseline
    from analytics.optimization import lp
    from analytics.segmentation import bins
    from backend import lp_cycle
    from backend.routers import forecast
    from scripts import run_baseline_forecast

    assert lp.Z_SCORE is lp_cycle.LP_SERVICE_Z is params.SERVICE_Z
    assert lp_cycle.LP_SERVICE_LEVEL_PCT is params.SERVICE_LEVEL_PCT
    assert lp_cycle.LP_WEIGHTS is params.LP_WEIGHTS
    assert (lp.W1, lp.W2, lp.W3) == tuple(params.LP_WEIGHTS[k] for k in ("cost", "service_level", "storage"))
    assert run_baseline_forecast.CONFIDENCE_Z is forecast.FORECAST_INTERVAL["z"] is params.FORECAST_INTERVAL_Z
    assert baseline.MIN_MONTHS_WITH_SALES is bins.LENGTH_V1_INSUFFICIENT is params.MIN_MONTHS_WITH_SALES
    assert fsn.FSN_WINDOW_MONTHS is params.FSN_WINDOW_MONTHS
    assert fsn.MIN_FAST_SALES_MONTHS is params.FSN_MIN_FAST_SALES_MONTHS
    assert fsn.NON_MOVING_MONTHS is params.DEAD_SKU_MONTHS


@pytest.mark.parametrize("rel, alias", [
    ("analytics/optimization/lp.py", "Z_SCORE"),
    ("analytics/segmentation/bins.py", "LENGTH_V1_INSUFFICIENT"),
    ("analytics/segmentation/bins.py", "VOLATILITY_V1_LOW"),
    ("analytics/segmentation/bins.py", "VOLATILITY_V1_HIGH"),
    ("analytics/classification/fsn.py", "NON_MOVING_MONTHS"),
    ("analytics/classification/fsn.py", "MIN_FAST_SALES_MONTHS"),
    ("analytics/classification/fsn.py", "FAST_ADI_BELOW"),
    ("backend/routers/segment.py", "CV_BAND_MEDIUM"),
    ("backend/routers/segment.py", "CV_BAND_HIGH"),
    ("backend/routers/recommendations.py", "AVG_DAYS_PER_MONTH"),
    ("scripts/run_baseline_forecast.py", "CONFIDENCE_Z"),
])
def test_alias_is_assigned_from_params_not_a_literal(rel, alias):
    """`is` can't tell a retyped small int from the parameter (CPython caches
    them), so the aliases' own assignments are checked: a name, never a number."""
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == alias for t in node.targets)]
    assert values, f"{alias} not assigned in {rel}"
    assert not any(isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) for v in values for n in ast.walk(v))


def test_the_served_xgboost_is_single_threaded_from_params():
    """Item 14: the served model's nthread is analytics.params.XGB_NTHREAD (1),
    so a rerun is bit-identical."""
    from analytics.forecasting import global_model

    assert global_model.PARAMS["nthread"] is params.XGB_NTHREAD == 1
