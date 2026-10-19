"""
analytics.forecasting.calendar - the company calendar factor: how a calendar
month usually sells against the three months before it.

Why (2026-10-19, read-only diagnosis on real Tier A as of 2026-02): the
biggest one-step misses repeat by calendar month - December falls, January
rebounds, July dips - and every served model, XGBoost included (it has
month_of_year but still improves), forecasts those months from a trailing
level that cannot see them coming.

The factor for target month t (calendar month m), read ONLY from months
before t:

    for every earlier year y with month m and its 3 prior months on record:
        ratio_y = company total in (y, m) / mean(company total, 3 months before)
    factor = geometric mean of ratio_y, shrunk toward 1 by CALENDAR_FACTOR_SHRINK

No earlier year on record -> factor 1 (no adjustment). The company total is
every real Unilever SKU row, summed in pieces; a blank quantity is skipped,
never read as 0.

Backtest, 2025-01..2026-02, served router, 180 products: median WAPE
0.315 -> 0.299, 95% interval [-0.023, -0.000], 107 better / 73 worse; the
gain is in Dec/Jan/Jul, other months tie. December is the weak part: it rose
in 2023 and fell in 2024 and 2025, and only 1-2 earlier years exist.

Pure functions, no DB access.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.params import CALENDAR_FACTOR_PRIOR_MONTHS, CALENDAR_FACTOR_SHRINK


def company_totals(demand: pd.DataFrame) -> pd.Series:
    """Monthly company total in pieces, indexed by month start. `demand` is
    run_baseline_forecast.fetch_demand's frame (calendar_month 'YYYY-MM',
    quantity NaN for a blank capture). A month whose every row is blank is
    left out, not read as 0."""
    tot = demand.groupby("calendar_month")["quantity"].sum(min_count=1).dropna()
    tot.index = pd.to_datetime(tot.index + "-01")
    return tot.sort_index().astype(float)


def calendar_factor(totals: pd.Series, target_month: pd.Timestamp,
                    shrink: float = CALENDAR_FACTOR_SHRINK) -> tuple[float, int]:
    """(factor, earlier years used) for `target_month`. Only months before it
    are read, so a backtest at any origin sees what was known then."""
    target_month = pd.Timestamp(target_month)
    known = totals[totals.index < target_month]
    ratios = []
    for year in range(target_month.year - 1, known.index.min().year - 1 if len(known) else target_month.year, -1):
        month = pd.Timestamp(year=year, month=target_month.month, day=1)
        prior = [month - pd.DateOffset(months=i) for i in range(1, CALENDAR_FACTOR_PRIOR_MONTHS + 1)]
        if month in known.index and all(p in known.index for p in prior):
            base = float(np.mean([known[p] for p in prior]))
            if base > 0 and known[month] > 0:
                ratios.append(float(known[month]) / base)
    if not ratios:
        return 1.0, 0
    full = float(np.exp(np.mean(np.log(ratios))))
    return 1.0 + (full - 1.0) * shrink, len(ratios)
