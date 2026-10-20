"""
analytics.forecasting.review_flag - "review before ordering": which products'
forecast for a planning cycle is likely to miss by a lot.

A product is flagged for cycle month M when either rule trips, reading only
what was known before M (analytics.params holds the thresholds and where they
come from):

  collapse   the mean of its last 3 months is below 0.5 x the mean of its
             last 12 months (months up to M-1, counted from the first sale, a
             month with no sales = 0; needs 12+ months since the first sale)
  over-run   it is in a run of 3+ over-forecast months ending at M-1: the
             model that serves it today, scored one step ahead on each of
             those months (force_bin, the holdout protocol of
             scripts/run_baseline_forecast.served_forecasts), forecast more
             than it sold

This is option D of the surplus-bias experiment (kelvin/surplus-bias-
experiment 3226cc4). There, flagged product-months carried 1.3x to 1.7x their
share of sales pesos in surplus pesos but were NOT more often over-forecast
(52.7% vs 51.5% over 2023-10..2026-02), so the flag means "a large miss is
likely, check it before ordering", never "cut the order". It changes no
forecast and no order.

None means "could not be assessed" (too little history, or no served model),
which is kept apart from False.

Pure functions, no DB access.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.forecasting.global_model import GlobalForecaster
from analytics.forecasting.router import rolling_one_step
from analytics.params import (
    REVIEW_COLLAPSE_BASE_MONTHS,
    REVIEW_COLLAPSE_RATIO,
    REVIEW_COLLAPSE_RECENT_MONTHS,
    REVIEW_LOOKBACK_MONTHS,
    REVIEW_OVER_RUN_MONTHS,
)

REASON_COLLAPSE = "collapse"
REASON_OVER_RUN = "over_forecast_run"


def _prev_month(month: pd.Timestamp, n: int = 1) -> pd.Timestamp:
    return pd.Timestamp(month) - pd.offsets.MonthBegin(n)


def history_before(series: pd.Series, cycle: pd.Timestamp) -> pd.Series:
    """The series up to M-1, zero-filled through M-1: a month with no sales
    row is a month with no sales, including months after the last sale."""
    last = _prev_month(cycle)
    s = series[series.index <= last]
    if s.empty:
        return s
    idx = pd.date_range(s.index.min(), last, freq="MS")
    return s.reindex(idx, fill_value=0.0)


def collapse_ratio(series: pd.Series, cycle: pd.Timestamp) -> float | None:
    """mean(last 3 months) / mean(last 12 months) before `cycle`, or None
    when there are fewer than 12 months since the first sale or the 12-month
    mean is not positive."""
    h = history_before(series, cycle)
    sold = np.flatnonzero(h.to_numpy(dtype=float) > 0)
    if not sold.size:
        return None
    h = h.iloc[int(sold[0]):]
    if len(h) < REVIEW_COLLAPSE_BASE_MONTHS:
        return None
    base = float(h.tail(REVIEW_COLLAPSE_BASE_MONTHS).mean())
    if base <= 0:
        return None
    return float(h.tail(REVIEW_COLLAPSE_RECENT_MONTHS).mean()) / base


def over_forecast_run(series: pd.Series, cycle: pd.Timestamp, served_bin: str | None,
                      forecaster: GlobalForecaster | None, calendar_totals: pd.Series | None = None) -> int | None:
    """Over-forecast months in a row ending at M-1, counted back at most
    REVIEW_LOOKBACK_MONTHS. None when the product has no served bin, or the
    served model has no forecast for M-1 (too little history then).
    `calendar_totals`: score the calendar-adjusted values when that is what is served."""
    if served_bin is None or served_bin == "insufficient":
        return None
    h = history_before(series, cycle)
    months = [m for m in (_prev_month(cycle, n) for n in range(REVIEW_LOOKBACK_MONTHS, 0, -1))
              if m in h.index and m > h.index[0]]
    scored = rolling_one_step(h, months, forecaster, force_bin=served_bin,
                            calendar_totals=calendar_totals).set_index("month")
    run, m = 0, _prev_month(cycle)
    if m not in scored.index:
        return None
    while m in scored.index and scored.at[m, "value"] > scored.at[m, "actual"]:
        run, m = run + 1, _prev_month(m)
    return run


def review_flag(series: pd.Series, cycle: pd.Timestamp, served_bin: str | None,
                forecaster: GlobalForecaster | None, calendar_totals: pd.Series | None = None) -> dict:
    """{needs_review, reasons, collapse, collapse_ratio, over_run_months} for
    one product and cycle month. needs_review is True when either rule trips,
    False when at least one rule was assessed and none tripped, and None when
    neither could be assessed."""
    ratio = collapse_ratio(series, cycle)
    run = over_forecast_run(series, cycle, served_bin, forecaster, calendar_totals)
    collapse = None if ratio is None else ratio < REVIEW_COLLAPSE_RATIO
    over_run = None if run is None else run >= REVIEW_OVER_RUN_MONTHS
    reasons = [r for r, hit in ((REASON_COLLAPSE, collapse), (REASON_OVER_RUN, over_run)) if hit]
    needs = True if reasons else (None if collapse is None and over_run is None else False)
    return {"needs_review": needs, "reasons": reasons, "collapse": collapse,
            "collapse_ratio": ratio, "over_run_months": run}
