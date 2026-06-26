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

TODO: Implement fit_sarima(series: pd.Series, sku_id: str) -> SARIMAResult.
      Implement evaluate_sarima(result, holdout: pd.Series) -> dict[str, float].
      Implement forecast_one_step(result) -> float.
      All parameter selections must be logged and reproducible (no silent defaults).
"""
