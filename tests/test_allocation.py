"""tests/test_allocation.py — item 7: SSM's allocation rule, one definition
(analytics/allocation.py) for the dashboard card and the LP ceiling."""
from __future__ import annotations

import datetime

import pytest

from analytics import params
from analytics.allocation import allocation_levels, basis_year, monthly_allocation, planning_month_after
from scripts.run_lp import allocation_ceilings, build_parser
from tests.optimization.test_run_lp_script import _product


@pytest.mark.parametrize("latest, planning", [("2026-02", "2026-03"), ("2025-12", "2026-01"), ("2025-01", "2025-02")])
def test_planning_month_is_the_month_after_the_latest_data(latest, planning):
    assert planning_month_after(latest) == planning


def test_basis_is_the_year_before_the_planning_month_string_or_date():
    assert basis_year("2026-01") == 2025
    assert basis_year("2026-03") == 2025
    assert basis_year(datetime.date(2026, 1, 1)) == 2025


def test_the_unit_is_the_callers_and_travels_with_the_number():
    assert monthly_allocation(1200.0, 103, unit="pieces") == pytest.approx(103.0)
    assert allocation_levels(1200.0, unit="pesos")[0] == {"pct": 103, "annual": 1236.0, "monthly": 103.0, "unit": "pesos"}
    with pytest.raises(ValueError):
        monthly_allocation(1200.0, 103, unit="cases")


def test_default_level_is_the_guaranteed_minimum():
    assert params.ALLOCATION_DEFAULT_PCT == params.ALLOCATION_LEVELS_PCT[0] == 103
    assert build_parser().parse_args([]).allocation_pct == 103.0


def test_the_lp_ceiling_is_the_same_rule_in_pieces():
    products = [_product(1, prior_year_pieces=12_000.0), _product(2, prior_year_pieces=6_000.0)]
    ceilings = allocation_ceilings(products, 103.0)
    principal = products[0].principal
    assert ceilings == {principal: pytest.approx(monthly_allocation(18_000.0, 103.0, unit="pieces"))}
