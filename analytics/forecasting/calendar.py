"""
analytics.forecasting.calendar - the calendar factor: how a calendar month usually
sells against the three months before it. Computed per product since 2026-11-13
(GRAIN below); the company-total version is kept for the run-7 recreation only.

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

STATUS (2026-10-20, superseded 2026-11-13 by GRAIN): the company factor was applied to the live Forecast_Result (March 2026
factor 1.0762, all 175 'ok' rows),
adopted by the team as DEC-41 (2026-11-02); Sir Catubag has not signed it off. Sensitivity of the LP: 424,127 pieces with it, 354,975 without, a 16.3%
difference across 70 changed rows (reports/diagnostics/calc_audit_2026-10-20/blast_radius.py).

GRAIN (2026-11-12, Kelvin's brief "compute the calendar adjustment at the grain it is applied at"): the company ratio above is
a volume-weighted total, but the factor multiplies EACH product's forecast. In 4 of 35 month-years the company ratio and the
typical product moved in opposite directions (March 2024: company 1.136, product median 0.906, 61% of products fell) and in 8
more by over 10%: a few large products move the total. ProductCalendar computes the factor per product instead
(analytics.params.CALENDAR_GRAIN = "product"):

    per month-year: median over eligible products (sold > 0 in the month and each of the 3 months before; blank = not
                    eligible) of month / mean(3 prior)                                   -> med(y)
    per product:    log f = w * mean_y log(own ratio) + (1 - w) * mean_y log med(y),  w = n / (n + CALENDAR_OWN_YEARS_PRIOR),
                    n = the product's own eligible years (none -> the median alone); then halfway to 1 (CALENDAR_FACTOR_SHRINK)
    December rule:  a December target takes the most recent earlier December's product median in full when it was below 1
                    (analytics.params.DECEMBER_DIP_RULE; at product grain December 2023 was 0.950, so the rule acts in
                    December 2024 and 2025 and can be scored in both backtest windows)

Chosen by criteria fixed before the results (scratchpad CRITERIA_GRAIN_2026-11-12.md, recorded in STATE.md): three product-grain
estimators all passed the both-windows bar against the company factor; this one had the lowest mean pooled WAPE; the December
rule then passed against it. Only months before the target month are read.

Pure functions, no DB access.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import params
from analytics.params import CALENDAR_FACTOR_PRIOR_MONTHS, CALENDAR_FACTOR_SHRINK


def company_totals(demand: pd.DataFrame) -> pd.Series:
    """Monthly company total in pieces, indexed by month start. `demand` is
    run_baseline_forecast.fetch_demand's frame (calendar_month 'YYYY-MM',
    quantity NaN for a blank capture). A month whose every row is blank is
    left out, not read as 0."""
    tot = demand.groupby("calendar_month")["quantity"].sum(min_count=1).dropna()
    tot.index = pd.to_datetime(tot.index + "-01")
    return tot.sort_index().astype(float)


def calendar_factor(totals, target_month: pd.Timestamp,
                    shrink: float = CALENDAR_FACTOR_SHRINK) -> tuple[float, int]:
    """(factor, earlier years used) for `target_month`. Only months before it
    are read, so a backtest at any origin sees what was known then.
    `totals` is company_totals' series (the company factor), or one product's ProductCalendar view (for_product), whose own
    factor is returned."""
    if hasattr(totals, "factor"):
        return totals.factor(target_month)
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


class ProductCalendar:
    """The calendar factor at product grain (module docstring, GRAIN). Built once from fetch_demand's frame; for_product()
    hands route() one product's view of it."""

    def __init__(self, demand: pd.DataFrame):
        d = demand.dropna(subset=["quantity"])
        t = pd.to_datetime(d["calendar_month"] + "-01")
        w = d.assign(t=t).pivot_table(index="product_key", columns="t", values="quantity", aggfunc="sum")
        self.median: dict[pd.Timestamp, float] = {}
        self.own: dict[int, dict[pd.Timestamp, float]] = {}
        for month in sorted(w.columns):
            prior = [month - pd.DateOffset(months=i) for i in range(1, CALENDAR_FACTOR_PRIOR_MONTHS + 1)]
            if not all(p in w.columns for p in prior):
                continue
            sub = w[[month] + prior].dropna()
            sub = sub[(sub > 0).all(axis=1)]
            if not len(sub):
                continue
            ratio = sub[month] / sub[prior].mean(axis=1)
            self.median[month] = float(ratio.median())
            for pk, v in ratio.items():
                self.own.setdefault(int(pk), {})[month] = float(v)

    def factor(self, product_key: int, target_month: pd.Timestamp) -> tuple[float, int]:
        t = pd.Timestamp(target_month)
        earlier = [m for m in (pd.Timestamp(year=y, month=t.month, day=1) for y in range(t.year - 1, 1999, -1))
                   if m in self.median and m < t]
        if not earlier:
            return 1.0, 0
        if params.DECEMBER_DIP_RULE and t.month == 12 and self.median.get(earlier[0]) is not None                 and earlier[0].year == t.year - 1 and self.median[earlier[0]] < 1.0:
            return float(self.median[earlier[0]]), 1
        own = [np.log(self.own[int(product_key)][m]) for m in earlier if m in self.own.get(int(product_key), {})]
        weight = len(own) / (len(own) + params.CALENDAR_OWN_YEARS_PRIOR)
        log_f = weight * (float(np.mean(own)) if own else 0.0) + (1 - weight) * float(np.mean([np.log(self.median[m]) for m in earlier]))
        return 1.0 + (float(np.exp(log_f)) - 1.0) * CALENDAR_FACTOR_SHRINK, len(earlier)

    def view(self, product_key: int) -> "ProductCalendarView":
        return ProductCalendarView(self, int(product_key))


class ProductCalendarView:
    def __init__(self, calendar: ProductCalendar, product_key: int):
        self.calendar, self.product_key = calendar, product_key

    def factor(self, target_month: pd.Timestamp) -> tuple[float, int]:
        return self.calendar.factor(self.product_key, target_month)


def calendar_basis(demand: pd.DataFrame):
    """What the runner, the backtests and the review flags pass as calendar_totals: the product calendar
    (analytics.params.CALENDAR_GRAIN = "product") or, for "company", company_totals as before."""
    return ProductCalendar(demand) if params.CALENDAR_GRAIN == "product" else company_totals(demand)


def for_product(basis, product_key: int):
    """One product's calendar for route(): its view of a ProductCalendar; company totals and None pass through."""
    return basis.view(product_key) if isinstance(basis, ProductCalendar) else basis
