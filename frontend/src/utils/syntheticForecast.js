// How the forecast page names its forecast series. GET /forecast answers `demonstration: true` only when the
// request passed BOTH gates (the Topbar's X-Data-Mode: preview and the server's DM_DEMO_ENABLED), and the forecast is
// then demo.unilever_sku_forecast, a generated figure (CLAUDE.md rule 2). Everything on the chart that names the
// forecast reads from here, so the real and the synthetic series can never share a label.
export const REAL_FORECAST_LABELS = Object.freeze({
  isDemo: false,
  name: 'Forecast',
  legend: 'Forecast',
  endLabel: 'Forecast',
  statLabel: 'Forecast',
  watermark: null,
});

export const SYNTHETIC_FORECAST_LABELS = Object.freeze({
  isDemo: true,
  name: 'Synthetic forecast',
  legend: 'Synthetic forecast (demonstration, not SSM’s)',
  endLabel: 'SYNTHETIC forecast',
  statLabel: 'Synthetic forecast',
  watermark: 'SYNTHETIC DEMONSTRATION',
});

export const forecastLabels = (result) => (result?.demonstration === true ? SYNTHETIC_FORECAST_LABELS : REAL_FORECAST_LABELS);
