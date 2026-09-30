"""
analytics.forecasting.sarima — Per-SKU SARIMA demand forecasting.

Phase 4 (CLAUDE.md Steps 12–16):
  Step 12: Time-series decomposition — trend, seasonal, residual; ADF stationarity test.
  Step 13: Parameter selection — AIC/BIC grid search per SKU; log (p,d,q)(P,D,Q,s).
  Step 14: Training — 80/20 time-based split (strictly temporal, NO random sampling).
           First 80% = training; last 20% = holdout. Validate split boundaries.
  Step 15: Evaluation — MAE, MAPE, RMSE, MASE on holdout.
           MAPE ≥ 20%: flag the SKU to the dashboard. NEVER silently drop or proceed.
  Step 16: Forecast — one-month-ahead Ŷ_(t+1,i) per Category A SKU.
           Store forecast outputs for LP input (Phase 5).

Constants:
  SARIMA_SEASONAL_PERIOD = 12   (monthly seasonality assumed; confirm with data)
  MAPE_GATE = 0.20              (20% ceiling — gate, not a soft warning)

Constants:
  SARIMA_SEASONAL_PERIOD = 12   (monthly seasonality assumed; confirm with data)
  MAPE_GATE = 0.20              (20% ceiling — gate, not a soft warning)

Implements:
  decompose_series(series) -> DecompositionResult   (Step 12)
  train_holdout_split(series) -> (train, holdout)    (Step 14)
  grid_search_sarima(train, sku_id) -> SARIMAResult  (Step 13)
  fit_sarima(series, sku_id) -> SARIMAResult         (Step 13/14, ties the two together)
  evaluate_sarima(result, holdout) -> dict[str, float]  (Step 15)
  passes_mape_gate(mape) -> bool                     (Step 15 gate, never a silent drop)
  forecast_one_step(result) -> float                 (Step 16)

Every SARIMA fit inside grid_search_sarima is recorded in SARIMAResult.param_log
(order, seasonal_order, aic, bic, converged, error) — Step 13's "must be logged
and reproducible" requirement — even the combinations that failed to converge,
so the search is auditable, not just the winner.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from itertools import product

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import seasonal_decompose
from statsmodels.tsa.stattools import adfuller
from statsmodels.tsa.statespace.sarimax import SARIMAX

# The split and its fraction moved out of this retired module (2026-09-30);
# re-exported so its own evaluate path and tests are unchanged.
from analytics.forecasting.split import train_holdout_split  # noqa: F401
from analytics.params import HOLDOUT_FRACTION

SARIMA_SEASONAL_PERIOD = 12
MAPE_GATE = 0.20

# Deliberately small default grid — this is a batch job run per-SKU across
# every Category A SKU, not a one-off fit, so the search space is kept
# modest rather than exhaustive. Override via `param_grid` for a wider
# search on a specific SKU if needed.
DEFAULT_PARAM_GRID: dict[str, tuple[int, ...]] = {
    "p": (0, 1, 2),
    "d": (0, 1),
    "q": (0, 1, 2),
    "P": (0, 1),
    "D": (0, 1),
    "Q": (0, 1),
}


@dataclass
class DecompositionResult:
    trend: pd.Series
    seasonal: pd.Series
    resid: pd.Series
    adf_statistic: float
    adf_pvalue: float
    is_stationary: bool  # ADF p-value < 0.05


@dataclass
class ParamLogEntry:
    order: tuple[int, int, int]
    seasonal_order: tuple[int, int, int, int]
    aic: float | None
    bic: float | None
    converged: bool
    error: str | None = None


@dataclass
class SARIMAResult:
    sku_id: str
    order: tuple[int, int, int]
    seasonal_order: tuple[int, int, int, int]
    aic: float
    bic: float
    fitted_model: object  # statsmodels SARIMAXResultsWrapper
    train_series: pd.Series
    param_log: list[ParamLogEntry] = field(default_factory=list)


def decompose_series(series: pd.Series, period: int = SARIMA_SEASONAL_PERIOD) -> DecompositionResult:
    """Step 12: classical trend/seasonal/residual decomposition plus an
    ADF stationarity test. Informational only — this does not alter the
    series fed to SARIMAX (SARIMAX takes the (d, D) differencing terms
    itself); it exists so the differencing order chosen in Step 13 can be
    sanity-checked against what the data actually shows.

    Requires at least 2 full seasonal cycles (2 * period observations),
    the minimum statsmodels' seasonal_decompose needs for a real result.
    """
    if len(series) < 2 * period:
        raise ValueError(
            f"decompose_series needs at least {2 * period} observations "
            f"(2 full seasonal cycles at period={period}); got {len(series)}."
        )

    decomposition = seasonal_decompose(series, model="additive", period=period)
    adf_stat, adf_pvalue = adfuller(series.dropna())[:2]

    return DecompositionResult(
        trend=decomposition.trend,
        seasonal=decomposition.seasonal,
        resid=decomposition.resid,
        adf_statistic=float(adf_stat),
        adf_pvalue=float(adf_pvalue),
        is_stationary=bool(adf_pvalue < 0.05),
    )


def grid_search_sarima(
    train: pd.Series,
    sku_id: str,
    seasonal_period: int = SARIMA_SEASONAL_PERIOD,
    param_grid: dict[str, tuple[int, ...]] = DEFAULT_PARAM_GRID,
) -> SARIMAResult:
    """Step 13: AIC/BIC grid search over (p,d,q)(P,D,Q,s). Selects the
    combination with the lowest AIC (BIC logged alongside for reference).
    Every combination attempted is recorded in param_log — including ones
    that fail to converge or raise — so the search is reproducible and
    auditable, never a silent "it just picked something" default.
    """
    combos = list(product(
        param_grid["p"], param_grid["d"], param_grid["q"],
        param_grid["P"], param_grid["D"], param_grid["Q"],
    ))

    param_log: list[ParamLogEntry] = []
    best: SARIMAResult | None = None

    for p, d, q, P, D, Q in combos:
        order = (p, d, q)
        seasonal_order = (P, D, Q, seasonal_period)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = SARIMAX(
                    train,
                    order=order,
                    seasonal_order=seasonal_order,
                )
                fitted = model.fit(disp=False)

            param_log.append(ParamLogEntry(
                order=order, seasonal_order=seasonal_order,
                aic=float(fitted.aic), bic=float(fitted.bic), converged=True,
            ))

            if best is None or fitted.aic < best.aic:
                best = SARIMAResult(
                    sku_id=sku_id, order=order, seasonal_order=seasonal_order,
                    aic=float(fitted.aic), bic=float(fitted.bic),
                    fitted_model=fitted, train_series=train, param_log=[],
                )
        except Exception as exc:  # noqa: BLE001 — a failed grid cell is expected, not fatal
            param_log.append(ParamLogEntry(
                order=order, seasonal_order=seasonal_order,
                aic=None, bic=None, converged=False, error=str(exc),
            ))

    if best is None:
        raise RuntimeError(
            f"grid_search_sarima: every ({len(combos)}) parameter combination "
            f"failed to converge for sku_id={sku_id!r}. See param_log entries "
            f"for individual errors — do not fall back to a silent default order."
        )

    best.param_log = param_log
    return best


def fit_sarima(
    series: pd.Series,
    sku_id: str,
    seasonal_period: int = SARIMA_SEASONAL_PERIOD,
    param_grid: dict[str, tuple[int, ...]] = DEFAULT_PARAM_GRID,
    holdout_fraction: float = HOLDOUT_FRACTION,
) -> SARIMAResult:
    """Ties Steps 13-14 together: temporally splits `series`, then runs
    the grid search on the training portion only (the holdout must never
    be seen during model/parameter selection, or evaluation in Step 15
    is meaningless). Returns the best-fit SARIMAResult fit on train only
    — pass its holdout counterpart to evaluate_sarima() next.
    """
    train, _holdout = train_holdout_split(series, holdout_fraction=holdout_fraction)
    return grid_search_sarima(train, sku_id, seasonal_period=seasonal_period, param_grid=param_grid)


def evaluate_sarima(result: SARIMAResult, holdout: pd.Series) -> dict[str, float]:
    """Step 15: MAE, MAPE, RMSE, MASE on the holdout set, plus whether the
    SKU passes the MAPE gate.

    Deviation flagged (not silently made), matching this repo's own
    convention (see seed_date_dim.py): the original TODO signature was
    evaluate_sarima(result, holdout) -> dict[str, float] with no `train`
    parameter. MASE is defined relative to a naive seasonal forecast on
    the *training* series (Hyndman & Koehler 2006) — computing it without
    train would mean silently substituting a different, non-standard
    denominator. result.train_series (already carried on SARIMAResult
    from fit_sarima/grid_search_sarima) is used for exactly that, so the
    public signature doesn't need to change.

    Returns a dict (not a dataclass) to match the documented TODO return
    type exactly: mae, mape, rmse, mase, mape_gate_passed (1.0/0.0 — kept
    as float so every value in the dict shares one type).
    """
    forecast = result.fitted_model.get_forecast(steps=len(holdout))
    predicted = pd.Series(forecast.predicted_mean.values, index=holdout.index)

    errors = holdout - predicted
    abs_errors = errors.abs()

    mae = float(abs_errors.mean())
    rmse = float(np.sqrt((errors ** 2).mean()))

    # MAPE: rows where actual demand is 0 are excluded (division by zero
    # would either crash or, worse, get "fixed" by fabricating a fake
    # denominator — neither is honest). If every holdout value is 0,
    # MAPE is undefined and reported as NaN, not silently as 0%.
    nonzero = holdout != 0
    mape = float((abs_errors[nonzero] / holdout[nonzero].abs()).mean()) if nonzero.any() else float("nan")

    # MASE denominator: mean absolute seasonal difference in training data
    # (Hyndman & Koehler 2006). Falls back to the non-seasonal one-step
    # naive difference if the training series is shorter than one full
    # seasonal cycle, and records nothing silently either way — mase is
    # NaN if neither denominator is computable (a constant training
    # series, for instance), rather than divide-by-near-zero noise.
    train = result.train_series
    period = result.seasonal_order[3]
    if len(train) > period:
        naive_diffs = (train - train.shift(period)).abs().dropna()
    else:
        naive_diffs = train.diff().abs().dropna()
    scale = float(naive_diffs.mean()) if not naive_diffs.empty else 0.0
    mase = float(mae / scale) if scale > 0 else float("nan")

    mape_gate_passed = mape < MAPE_GATE if not np.isnan(mape) else False

    return {
        "mae": mae,
        "mape": mape,
        "rmse": rmse,
        "mase": mase,
        "mape_gate_passed": float(mape_gate_passed),
    }


def passes_mape_gate(mape: float, gate: float = MAPE_GATE) -> bool:
    """Step 15's gate check as a standalone predicate: MAPE >= 20% means
    the SKU is FLAGGED to the dashboard, never silently dropped or passed
    through as if it met the bar. Callers must branch on this return
    value and route flagged SKUs to a visible warning, not skip storing
    them."""
    if np.isnan(mape):
        return False
    return mape < gate


def forecast_one_step(result: SARIMAResult) -> float:
    """Step 16: one-step-ahead point forecast Ŷ_(t+1,i), the period
    immediately after whatever series `result.fitted_model` was fit on.

    Caller's responsibility: if you want the forecast for the period
    after the FULL known history (not just after the 80% training split),
    refit on train+holdout combined first (e.g. via grid_search_sarima
    using result.order/result.seasonal_order on the full series) and pass
    that result here — this function always forecasts one step past
    whatever data the model actually saw, it does not guess which series
    you intended.
    """
    forecast = result.fitted_model.get_forecast(steps=1)
    return float(forecast.predicted_mean.iloc[0])
