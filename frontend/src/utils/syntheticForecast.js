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
  name: 'Sample-data forecast',
  legend: 'Sample-data forecast (demonstration, not SSM’s)',
  endLabel: 'SAMPLE-DATA forecast',
  statLabel: 'Sample-data forecast',
  watermark: 'SAMPLE DATA DEMONSTRATION',
});

export const forecastLabels = (result) => (result?.demonstration === true ? SYNTHETIC_FORECAST_LABELS : REAL_FORECAST_LABELS);
