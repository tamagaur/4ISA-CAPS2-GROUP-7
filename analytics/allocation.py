"""
analytics.allocation — SSM's supplier-allocation rule: the ONE definition
the dashboard's allocation card and the LP's allocation ceiling both use.

Sir Abe (client meeting, Sep 2026): the principal sets the year's allocation
from the previous year's sales — x103% minimum, x105% mid, x108% maximum
(analytics.params.ALLOCATION_LEVELS_PCT) — revised in Q4 on how the market
went.

Open SSM questions, held as placeholders (Yuan, 2026-09-30):
  basis year  the calendar year before the PLANNING month, the month being
              ordered for (basis_year). A January plan uses the whole of
              last year even when last December is the latest data month.
  unit        what the basis is counted in is the CALLER's argument: the LP
              needs pieces; the dashboard card uses pesos, since Del Monte's
              sell-out has no pieces. The number carries its unit.
  level       analytics.params.ALLOCATION_DEFAULT_PCT (103, the guaranteed
              minimum) until SSM says which level applies.

Standard library only: the always-on API imports this module.
"""
from __future__ import annotations

import datetime

from analytics.params import ALLOCATION_DEFAULT_PCT, ALLOCATION_LEVELS_PCT, ALLOCATION_UNITS

__all__ = [
    "ALLOCATION_DEFAULT_PCT", "ALLOCATION_LEVELS_PCT", "ALLOCATION_UNITS",
    "allocation_levels", "basis_year", "monthly_allocation", "planning_month_after",
]


def planning_month_after(latest_month: str) -> str:
    """'YYYY-MM' of the month after `latest_month` ('YYYY-MM'): the month a
    plan made on data through `latest_month` orders for."""
    year, month = int(latest_month[:4]), int(latest_month[5:7])
    return f"{year + month // 12:04d}-{month % 12 + 1:02d}"


def basis_year(planning_month: str | datetime.date) -> int:
    """The calendar year whose sales set the allocation for `planning_month`
    ('YYYY-MM' or a date): the year before it."""
    year = planning_month.year if isinstance(planning_month, datetime.date) else int(str(planning_month)[:4])
    return year - 1


def _check_unit(unit: str) -> None:
    if unit not in ALLOCATION_UNITS:
        raise ValueError(f"allocation unit must be one of {ALLOCATION_UNITS}, got {unit!r}")


def monthly_allocation(basis_total: float, pct: float, unit: str) -> float:
    """The basis year's total × pct% ÷ 12: one month's allocation, in `unit`
    (the unit the basis was counted in)."""
    _check_unit(unit)
    return basis_total * pct / 100.0 / 12.0


def allocation_levels(basis_total: float, unit: str, levels=ALLOCATION_LEVELS_PCT) -> list[dict]:
    """[{pct, annual, monthly, unit}] for each level, rounded to 2 dp."""
    _check_unit(unit)
    return [
        {
            "pct": pct,
            "annual": round(basis_total * pct / 100.0, 2),
            "monthly": round(monthly_allocation(basis_total, pct, unit), 2),
            "unit": unit,
        }
        for pct in levels
    ]
