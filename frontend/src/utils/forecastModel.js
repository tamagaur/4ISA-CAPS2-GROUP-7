// Which model produced a SKU's stored forecast, in words a planner can read.
// The backend serves one model per history-length bin (LIVE_MODEL in
// analytics/forecasting/router.py), and scripts/run_baseline_forecast.py
// records it in Forecast_Result.model_params, which GET /forecast/{sku}
// returns as forecast[].model_params:
//
//   sales months   model_params.method                label
//   under 3        trailing_average (provisional)     Provisional average
//   3-11           ma3                                3-month moving average
//   12-23          tsb                                TSB
//   24 or more     xgb_ma3_avg                        XGBoost + MA3 average
//
// Two more cases the runner can write: zero_no_order (no sale in the last 6
// months, so the plan orders nothing), and a fallback, where a TSB/XGBoost
// guard fired and MA3 was served instead. A fallback keeps method 'ma3' with
// backup_fired true, and its bin still names the medium/long bin.
//
// Labels name the model and nothing more. On real data the challengers TIE
// with MA3, so no label here may say or imply that one is more accurate.

const METHOD_LABELS = {
  ma3: '3-month moving average',
  tsb: 'TSB',
  xgb_ma3_avg: 'XGBoost + MA3 average',
};

// kind:          'forecast' — a real model forecast (MA3, TSB, the XGBoost +
//                MA3 average, or MA3 as a fallback); 'provisional' — under 3
//                sales months, a trailing average kept as a placeholder, NOT
//                a forecast; 'no_order' — a deliberate 0 for a SKU with no
//                recent sales.
// label:         the display name, or null for a method this file doesn't
//                know. Never guessed as MA3: before 2026-09-21 every forecast
//                was MA3, and a guess would bring that falsehood back.
// recomputable:  the browser can reproduce the model for an earlier cutoff.
//                Only a served MA3: TSB and XGBoost run in the pipeline only,
//                and whether a fallback's guard would fire at an earlier
//                cutoff can't be checked here.
// fallback:      MA3 served because a TSB/XGBoost guard fired.
//
// `status` is the row's Forecast_Result.status ('ok' | 'insufficient_data'
// | 'dead_sku'), returned by GET /forecast since task E1. It is checked
// first; model_params' provisional flag and method still decide on their
// own for a response without it.
export function describeServedModel(modelParams, status) {
  const params = modelParams || {};
  const { method } = params;

  if (status === 'insufficient_data' || params.provisional === true || method === 'trailing_average') {
    return { kind: 'provisional', label: 'Provisional average', recomputable: false, fallback: false };
  }
  if (status === 'dead_sku' || method === 'zero_no_order') {
    return { kind: 'no_order', label: 'No order (no recent sales)', recomputable: false, fallback: false };
  }
  if (method === 'ma3' && params.backup_fired === true) {
    return { kind: 'forecast', label: `${METHOD_LABELS.ma3} (fallback)`, recomputable: false, fallback: true };
  }
  return {
    kind: 'forecast',
    label: METHOD_LABELS[method] ?? null,
    recomputable: method === 'ma3',
    fallback: false,
  };
}

// A fallback's model_params.backup_reason in plain words. The router writes
// one of five codes (route() and _safe_xgb() in router.py, and
// GlobalForecaster.forecast() in global_model.py); each is restated here
// without adding anything it didn't say. An unknown code is returned as
// stored, never guessed at — callers keep the raw string in a tooltip.
const wholeUnits = (value) => Math.round(Number(value)).toLocaleString();
const FALLBACK_REASONS = [
  [/^above_historical_max: (\S+) > (\S+)$/, (value, max) => `the model's value (${wholeUnits(value)}) was above this SKU's highest month (${wholeUnits(max)})`],
  [/^below_zero: (\S+)$/, (value) => `the model's value (${wholeUnits(value)}) was below zero`],
  [/^xgb_unavailable: (.+)$/, (detail) => `XGBoost wasn't available (${detail})`],
  [/^xgb_no_forecast: (.+)$/, (detail) => `XGBoost produced no forecast (${detail})`],
  [/^xgb_failed: (.+)$/, (detail) => `XGBoost failed (${detail})`],
];

export function describeFallbackReason(reason) {
  if (!reason) return 'no reason recorded';
  for (const [pattern, describe] of FALLBACK_REASONS) {
    const match = String(reason).match(pattern);
    if (match) return describe(...match.slice(1));
  }
  return String(reason);
}
