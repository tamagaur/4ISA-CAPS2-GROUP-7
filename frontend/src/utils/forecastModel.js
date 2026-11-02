// Which model produced a SKU's stored forecast, in words a planner can read.
// The backend serves one model per history-length bin (LIVE_MODEL in
// analytics/forecasting/router.py), and scripts/run_baseline_forecast.py
// records it in Forecast_Result.model_params, which GET /forecast/{sku}
// returns as forecast[].model_params:
//
//   sales months   model_params.method                label
//   under 3        trailing_average (provisional)     Provisional average
//   3-11           ma3                                3-month moving average
//   12-23          tsb                                Method for products that sell irregularly (TSB)
//   24 or more     xgb_ma3_avg                        Average of a trained model and the 3-month average (XGBoost + MA3)
//
// Two more cases the runner can write: zero_no_order (no sale in the last 6
// months, so the plan orders nothing), and a fallback, where a TSB/XGBoost
// guard fired and MA3 was served instead. A fallback keeps method 'ma3' with
// backup_fired true, and its bin still names the medium/long bin.
//
// Labels name the model and nothing more. On real data the challengers TIE
// with MA3, so no label here may say or imply that one is more accurate.

// Plain words first, the method's short name in brackets (Technical
// Adviser, 2 Oct 2026: no unexplained jargon; 2026-10-22).
const METHOD_LABELS = {
  ma3: '3-month moving average',
  tsb: 'Method for products that sell irregularly (TSB)',
  xgb_ma3_avg: 'Average of a trained model and the 3-month average (XGBoost + MA3)',
};

// What each model does, for a reader who doesn't know its name (the
// Technical Adviser, 2 Oct 2026). `short` goes under the forecast number,
// `long` beside the model's name in "How this forecast was made". Each says
// what the model computes and nothing about how accurate it is.
//
// `season` answers the Technical Adviser's "the product is seasonal: does
// the forecast use it?" (2 Oct 2026). The trained model takes the calendar
// month as an input (FEATURE_NAMES' month_of_year, analytics/forecasting/
// global_model.py); the 3-month average and TSB have no such term.
const METHOD_PLAIN = {
  ma3: {
    short: 'average of the last 3 months',
    long: 'the average of the last 3 months\u2019 sales',
    season: 'Not used: an average of the last 3 months does not look at the same month a year earlier',
  },
  tsb: {
    short: 'average for on-and-off sales',
    long: 'an average that tracks both how often the product sells and how much when it does',
    season: 'Not used: it follows how often and how much the product sells, not the time of year',
  },
  xgb_ma3_avg: {
    short: 'average of two methods',
    long: 'a model trained on every product\u2019s sales history (XGBoost), averaged with the last 3 months\u2019 average (MA3)',
    season: 'Used by half of it: the trained model takes the calendar month as an input; the 3-month average does not',
  },
};

// kind:          'forecast' — a real model forecast (MA3, TSB, the XGBoost +
//                MA3 average, or MA3 as a fallback); 'provisional' — under 3
//                sales months, a trailing average kept as a placeholder, NOT
//                a forecast; 'no_order' — a deliberate 0 for a SKU with no
//                recent sales.
// label:         the display name, or null for a method this file doesn't
//                know. Never guessed as MA3: before 2026-09-21 every forecast
//                was MA3, and a guess would bring that falsehood back.
// plain:         { short, long } from METHOD_PLAIN, or null where the label
//                is already plain words (provisional, no order) or unknown.
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
    return { kind: 'provisional', label: 'Provisional average', plain: null, recomputable: false, fallback: false };
  }
  if (status === 'dead_sku' || method === 'zero_no_order') {
    return { kind: 'no_order', label: 'No order (no recent sales)', plain: null, recomputable: false, fallback: false };
  }
  if (method === 'ma3' && params.backup_fired === true) {
    return {
      kind: 'forecast',
      label: `${METHOD_LABELS.ma3} (fallback)`,
      plain: { ...METHOD_PLAIN.ma3, short: `${METHOD_PLAIN.ma3.short} (fallback)` },
      recomputable: false,
      fallback: true,
    };
  }
  return withCalendar({
    kind: 'forecast',
    label: METHOD_LABELS[method] ?? null,
    plain: METHOD_PLAIN[method] ?? null,
    recomputable: method === 'ma3',
    fallback: false,
  }, params);
}

// A served forecast multiplied by the company calendar factor (model_params
// .calendar_factor, run_baseline_forecast.py --calendar-factor, 2026-10-19)
// does know the time of year, whatever its model: `season` says so first,
// then what the model does on its own; `short` says the number is adjusted.
// The number is no longer the model's own, so it can't be recomputed in the
// browser either (`recomputable`).
function withCalendar(served, params) {
  if (params.calendar_factor == null || !served.plain) return served;
  const factor = Number(params.calendar_factor);
  const years = params.calendar_years;
  const pct = (factor - 1) * 100;
  const adjust = `×${factor.toFixed(4)} (${pct >= 0 ? '+' : '−'}${Math.abs(pct).toFixed(1)}%)`;
  const own = served.plain.season
    ? served.plain.season.charAt(0).toLowerCase() + served.plain.season.slice(1).replace(': ', ' — ')
    : null;
  return {
    ...served,
    recomputable: false,
    calendar: { factor, years: years ?? null, before: params.value_before_calendar ?? null },
    plain: {
      ...served.plain,
      short: `${served.plain.short}, adjusted for the month`,
      season: `Yes, through the calendar adjustment: ${adjust}, how this month has sold against the 3 months before `
        + `it${years != null ? ` in ${years} earlier ${years === 1 ? 'year' : 'years'}` : ''} (company total).`
        + `${own ? ` The model on its own: ${own}.` : ''}`,
    },
  };
}

// A fallback's model_params.backup_reason in plain words. The router writes
// one of five codes (route() and _safe_xgb() in router.py, and
// GlobalForecaster.forecast() in global_model.py); each is restated here
// without adding anything it didn't say. An unknown code is returned as
// stored, never guessed at — callers keep the raw string in a tooltip.
const wholeUnits = (value) => Math.round(Number(value)).toLocaleString();
const FALLBACK_REASONS = [
  [/^above_historical_max: (\S+) > (\S+)$/, (value, max) => `the model's value (${wholeUnits(value)}) was above this product's highest month (${wholeUnits(max)})`],
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
