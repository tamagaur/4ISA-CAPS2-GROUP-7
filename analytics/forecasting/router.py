"""
analytics.forecasting.router - which model serves a SKU's one-month-ahead
forecast, decided from the history known at forecast time.

Design locked 2026-09-21 (LIVE, not shadow):

    bin           sales months   served                        in the background
    insufficient  < 3            (not routed - the runner's existing
                                  provisional trailing average)
    short         3-11           MA3                           -
    medium        12-23          TSB                           MA3
    long          24+            average of global XGBoost     MA3
                                 and MA3

MA3 is computed for every SKU and recorded as `ma3_value`: it is the
benchmark the challengers are scored against and the value served whenever a
challenger cannot be.

What the evidence says, and all it says: on real Tier A data TSB and the
XGBoost+MA3 average TIE with MA3 (half-year block tests: average - no wins,
four ties, one loss; TSB - tied in every testable block). They are served
because they are trained / stateful models that use the SKU's full history.
Nothing in this module may be read as a claim that they are more accurate.
analytics.forecasting.switching holds the rule that sends a bin back to MA3.

One MA3: every MA3 number here comes from baseline.moving_average_forecast,
called through the module so there is exactly one implementation to change.

Pure functions, no DB access.
"""
from __future__ import annotations

import pandas as pd

from analytics.forecasting import baseline
from analytics.forecasting.calendar import calendar_factor
from analytics.forecasting.global_model import GlobalForecaster, assert_real_history, from_first_sale
from analytics.segmentation.bins import length_v2

LIVE_MODEL = {"short": "ma3", "medium": "tsb", "long": "xgb_ma3_avg"}


def assert_real_rows(frame: pd.DataFrame, allow_placeholder: bool = False) -> None:
    """Raise if a demand frame carries any is_demo=true (placeholder) row. The
    _Real views exclude them structurally, so one here means the caller read a
    base table, or that this is the practice copy, whose view admits its own generated
    rows. Months are not judged by date: real 2021-22 rows pass.
    allow_placeholder=True: scripts/preview_router_synth.py and the what-if simulation
    (read-only); the runner passes only what practice_switch.labelled_rows_permitted says."""
    for col in ("is_demo", "is_placeholder"):
        if not allow_placeholder and col in frame.columns and frame[col].fillna(False).astype(bool).any():
            raise ValueError(f"demand frame contains {col}=true rows: forecasting models read the _Real views only")


def bin_at(history: pd.Series) -> tuple[str, int]:
    """(bin, sales months) from the history known at forecast time. The
    thresholds are analytics.segmentation.bins.length_v2's (3 / 12 / 24)."""
    sales_months = int((history.to_numpy(dtype=float) > 0).sum())
    return length_v2(sales_months)[0], sales_months


def ma3_value(history: pd.Series) -> float:
    """The single MA3: baseline.moving_average_forecast, one step ahead, over
    the last 3 OBSERVED months (a missing, blank-quantity month is skipped,
    never read as 0 - global_model.with_missing)."""
    return float(baseline.moving_average_forecast(history.dropna(), 1, baseline.MA_WINDOW)[0])


def route(series: pd.Series, target_month: pd.Timestamp, forecaster: GlobalForecaster | None = None,
          force_bin: str | None = None, allow_placeholder: bool = False,
          calendar_totals: pd.Series | None = None, context=None) -> dict:
    """One-step-ahead forecast for `target_month`, reading only months before
    it. `force_bin` scores a fixed model over past months (holdout error of
    the model served today); leave it None to bin from the history.
    `allow_placeholder` lets placeholder (is_demo) months through for the
    what-if preview, and for the runner when practice_switch permits it: never on live.
    `calendar_totals` (calendar.company_totals) multiplies the final value,
    after the guards, by the calendar factor for `target_month`; None = no
    adjustment. The runner's default, but NOT what is live: the 2026-10-19 Forecast_Result was written with
    the factor on (all 175 'ok' rows): team decision DEC-41; adviser sign-off outstanding (still pending).
    `ma3_value` stays the unadjusted benchmark either way.

    Guard order, first hit wins, fallback is always MA3 with the reason kept:
      1. the challenger produced a number (XGBoost can have none: no positive
         recent level to scale by, pool too small, or training failed);
      2. the final value is above the SKU's own historical maximum;
      3. the final value is below zero.
    A served MA3 is floored at zero, as the runner has always done.

    `context` (treatments.ProductContext): the succession and fading treatments
    (analytics/forecasting/treatments.py, served from 2026-11-10) act on the
    final value, after the calendar factor; `value_before_treatment` and
    `treatment` record it. None = not treated.
    """
    assert_real_history(series, allow_placeholder)
    # A missing (blank-quantity) month is unknown, not zero: every model reads observed months only.
    history = series[series.index < target_month].dropna()
    if len(history) < 1:
        raise ValueError("route() needs at least one month of history before target_month")
    # Months before the first sale are "not launched yet", not zero demand. TSB would
    # read them as a product dying, so every model sees the series from its first sale.
    history = from_first_sale(history) if len(from_first_sale(history)) else history
    bin_name, sales_months = bin_at(history)
    if force_bin is not None:
        bin_name = force_bin
    ma3 = ma3_value(history)
    out = {
        "bin": bin_name, "sales_months": sales_months, "ma3_value": ma3,
        "components": {"ma3": ma3}, "backup_fired": False, "backup_reason": None,
        "training_rows": None,
    }
    if bin_name == "insufficient":
        return {**out, "method": None, "value": None}

    method = LIVE_MODEL[bin_name]
    value: float | None = ma3
    reason = None
    if method == "tsb":
        value = float(baseline.tsb_forecast(history, 1)[0])
        out["components"]["tsb"] = value
    elif method == "xgb_ma3_avg":
        xgb_value, n_rows, reason = (None, None, "xgb_unavailable: no global model supplied") if forecaster is None \
            else _safe_xgb(forecaster, series, target_month)
        out["training_rows"] = n_rows
        out["components"]["xgb"] = xgb_value
        value = None if xgb_value is None else (xgb_value + ma3) / 2.0

    if method != "ma3":
        if value is not None and reason is None:
            hist_max = float(history.to_numpy(dtype=float).max())
            if value > hist_max:
                reason = f"above_historical_max: {value:.3f} > {hist_max:.3f}"
            elif value < 0:
                reason = f"below_zero: {value:.3f}"
        if reason is not None:
            out.update(backup_fired=True, backup_reason=reason)
            method, value = "ma3", ma3

    # Demand cannot be negative: floor every served value, whichever model produced it.
    value = max(0.0, float(value))
    if calendar_totals is not None:
        factor, years = calendar_factor(calendar_totals, target_month)
        out.update(value_before_calendar=value, calendar_factor=factor, calendar_years=years)
        value = max(0.0, value * factor)
    if context is not None:
        from analytics.forecasting.treatments import apply as apply_treatment   # lazy: treatments -> review_flag -> router
        treated, name = apply_treatment(series, target_month, value, context)
        out.update(value_before_treatment=value, treatment=name)
        value = treated
    return {**out, "method": method, "value": value}


def _safe_xgb(forecaster: GlobalForecaster, series: pd.Series, target_month: pd.Timestamp):
    try:
        return forecaster.forecast(series, target_month)
    except ValueError:
        raise                      # synthetic history is a caller bug, never something to fall back from
    except Exception as exc:       # training / prediction failure: serve MA3, keep the reason
        return None, None, f"xgb_failed: {type(exc).__name__}: {exc}"


def rolling_one_step(series: pd.Series, months, forecaster: GlobalForecaster | None = None,
                     force_bin: str | None = None, allow_placeholder: bool = False,
                     calendar_totals: pd.Series | None = None, context=None) -> pd.DataFrame:
    """route() at each of `months`, one step ahead, refit at every origin.
    `calendar_totals` as in route(): the holdout scores what would be served.
    Columns: month, actual, value (as served, guards applied), ma3 (the
    benchmark, floored at zero like a served MA3), method, backup_fired.
    A month whose actual is missing (blank quantity) is not scored: there is
    nothing to score it against, and scoring it as 0 would invent a miss."""
    rows = []
    for month in months:
        if pd.isna(series.loc[month]):
            continue
        r = route(series, month, forecaster, force_bin=force_bin, allow_placeholder=allow_placeholder,
                  calendar_totals=calendar_totals, context=context)
        if r["value"] is None:
            continue
        rows.append({"month": month, "actual": float(series.loc[month]), "value": r["value"],
                     "ma3": max(0.0, r["ma3_value"]), "method": r["method"], "backup_fired": r["backup_fired"]})
    return pd.DataFrame(rows, columns=["month", "actual", "value", "ma3", "method", "backup_fired"])
