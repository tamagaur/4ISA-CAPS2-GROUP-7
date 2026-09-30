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
    "SBC_ADI_CUT": 1.32,
    "SBC_CV2_CUT": 0.49,
    "XYZ_CV_LOW": 0.5,
    "XYZ_CV_HIGH": 1.0,
    "FSN_WINDOW_MONTHS": 12,
    "FSN_MIN_FAST_SALES_MONTHS": 3,
    "XGB_NTHREAD": 1,
    "LP_WEIGHTS": {"cost": 0.45, "service_level": 0.35, "storage": 0.20},
    "SERVICE_Z": 1.28,
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
        "warehouse_capacity": 3_800_000.0,
        "default_procurement_cost_per_unit": 25.0,
        "storage_cost_per_unit": 0.50,
    },
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
