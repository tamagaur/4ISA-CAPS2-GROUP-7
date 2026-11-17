// components/RangeCards.jsx ForecastErrorSummaryCard, rendered to HTML (react-dom/server through Vite's SSR loader, so the
// .jsx and its CSS imports load as the app loads them). Run: npm test
//
// Why: after a month of generated sales is loaded, GET /dashboard/accuracy on a range ending before that month keeps the
// range's figures but withholds the MASE entry test (backend/practice_copy._range_stands): mase_passed, mase_scored and
// median_mase come back null, with accuracy_withheld carrying the reason. Until 2026-11-17 the card called
// entry.median_mase.toFixed on that null and the SKU Forecast page fell to its error boundary. Every figure on the card's
// two lines is rendered here against a full answer, a withheld one and one whose blocks are empty.
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const root = fileURLToPath(new URL('../..', import.meta.url));
let server;
let render;

// React, the renderer and the card are imported by ONE module that Vite loads, so all three resolve to the same React (a
// native import beside it resolved react by a different path spelling on Windows and gave a second copy: invalid hook call).
const ENTRY = 'virtual:forecast-error-card-render';
const ENTRY_SOURCE = [
  "import React from 'react';",
  "import { renderToStaticMarkup } from 'react-dom/server';",
  "import { ForecastErrorSummaryCard } from '/src/components/RangeCards.jsx';",
  'export const render = (props) => renderToStaticMarkup(React.createElement(ForecastErrorSummaryCard, props));',
].join(String.fromCharCode(10));
const entryPlugin = {
  name: 'forecast-error-card-render',
  resolveId: (id) => (id === ENTRY ? ENTRY : null),
  load: (id) => (id === ENTRY ? ENTRY_SOURCE : null),
};

before(async () => {
  server = await createServer({
    root, configFile: false, logLevel: 'silent', appType: 'custom', plugins: [entryPlugin],
    server: { middlewareMode: true, hmr: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
  });
  ({ render } = await server.ssrLoadModule(ENTRY));
});
after(async () => { await server?.close(); });

const REASON = 'Forecast error withheld: sales for March 2026 is generated, and an error computed on them is not presented. '
  + 'A date range ending before March 2026 shows the real months’ error.';

const month = (period, actual, miss) => ({ period, actual_pesos: actual, net_miss_pesos: miss });

// The shape GET /dashboard/accuracy?level=product returns (backend/marts.accuracy_summary + dashboard_range), figures as read
// from live on 2026-11-17 for Mar 2025 - Feb 2026 (docs/DEPLOY_AND_TEST_2026-11-13.md row 6); only the fields the card reads.
const fullAnswer = () => ({
  label: 'Mar 2025 – Feb 2026', start_period: '2025-03', end_period: '2026-02',
  products: 233, product_months: 2052, forecast_source: 'backtest_recreated', run_labels: ['as served'],
  coverage: ['unilever'], calendar_adjusted: 'no', compare_run: null,
  company_total: { value: 0.085, label: 'Company total.', unit: 'pesos' },
  typical_product_weighted: { value: 0.319523, label: 'Typical product.', unit: 'pieces' },
  actual_pesos: 384_000_000, surplus_pesos: 20_000_000, shortage_pesos: 18_000_000, possibly_stock_limited: 12,
  by_month: [month('2025-03', 30_000_000, 1_000_000), month('2026-02', 28_000_000, -900_000)],
  over_forecast_runs: {},
  mape: {
    value: 0.324, mean: 0.41, label: 'Typical product MAPE.', products: 179,
    under_20_pct: 40, at_or_above_50_pct: 30, at_or_above_100_pct: 5, rule_ordered_products: 2, rule_ordered_product_months: 6,
    stock_limited_variant: { value: 0.318, label: 'Leaving out stock-limited months.', months_set_apart: 40, products: 179, under_20_pct: 41, at_or_above_100_pct: 4 },
    all_products: { value: 0.387, mean: 0.5, products: 218 },
    // near-zero MAE and RMSE on the WAPE's basis (a net-negative month = 0 sold) since 2026-11-17: live 4,241 / 10,676 over 368 months
    near_zero_flag: { products: 39, product_months: 368, label: 'Near zero.', mae_pieces: 4241.1, rmse_pieces: 10676.3 },
    planned_products: {
      value: 0.272, products: 100, plan_products: 115, planning_cycle_date: '2026-03-01', lp_run_key: 10,
      near_zero_products: 14, no_percentage_products: 0, not_scored_products: 1,
      label: 'Planned products.', caveat: 'Backtest errors on past months, not the plan’s quantities.',
    },
  },
  entry_test: {
    forecast_date: '2026-03-01', mase_scored: 175, mase_passed: 115, mase_gate: 1, median_mase: 0.76, measure: 'MASE measure.',
  },
});

// The same range after March is loaded (backend/practice_copy._range_stands): the range's figures stand, the entry test (the
// newest forecast's) is withheld in place, and the order-plan line names the April plan.
const withheldAnswer = () => {
  const body = fullAnswer();
  body.entry_test = {
    forecast_date: '2026-04-01', mase_scored: null, mase_passed: null, mase_gate: 1, median_mase: null,
    measure: 'MASE measure.', accuracy_withheld: REASON, rests_on_generated_sales: true,
  };
  Object.assign(body.mape.planned_products, {
    value: 0.287, products: 105, plan_products: 131, planning_cycle_date: '2026-04-01', lp_run_key: 11,
    near_zero_products: 14, not_scored_products: 12,
  });
  return body;
};

const text = (html) => html.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&#x27;/g, "'");
const EMPTY_AS_TEXT = /\bnull\b|\bundefined\b|\bNaN\b/;

test('a full answer: every figure on both lines', () => {
  const out = text(render({ accuracy: fullAnswer() }));
  for (const s of ['8.5%', '32.0%', '32.4%', '31.8%', '38.7%', '4,241', '10,676', '115 of 175', '(median 0.76)', '27.2%',
    'LP run 10', 'those 39 only', 'near-zero ones included', 'forecast products with a MASE']) {
    assert.ok(out.includes(s), `missing ${s}`);
  }
});

test('a withheld entry test renders, says it is withheld and why, and keeps the range and order-plan figures', () => {
  const out = text(render({ accuracy: withheldAnswer() }));
  assert.ok(out.includes('MASE, plan entry test on the latest forecast'), 'the MASE item is still named');
  assert.ok(out.includes(REASON), 'it gives the reason the answer carries');
  assert.ok(!EMPTY_AS_TEXT.test(out), 'no empty value printed as text');
  for (const s of ['8.5%', '32.0%', '32.4%', '38.7%', '28.7%', 'LP run 11', '131', '12 have no scored month']) {
    assert.ok(out.includes(s), `missing ${s}`);
  }
});

test('an answer whose blocks are empty renders without an empty value printed', () => {
  const body = fullAnswer();
  body.entry_test = { forecast_date: null, mase_scored: null, mase_passed: null, mase_gate: 1, median_mase: null, measure: null };
  body.mape = {
    value: 0.324, products: 179, label: 'MAPE.', under_20_pct: null, at_or_above_50_pct: null, at_or_above_100_pct: null,
    stock_limited_variant: { value: 0.318, months_set_apart: null, products: null, under_20_pct: null, at_or_above_100_pct: null },
    all_products: { value: 0.387, products: null },
    near_zero_flag: { products: 39, product_months: null, mae_pieces: null, rmse_pieces: null },
    planned_products: { value: 0.272, products: null, plan_products: null, planning_cycle_date: '2026-03-01', lp_run_key: null,
      near_zero_products: null, no_percentage_products: null, not_scored_products: null },
  };
  body.product_months = null;
  body.possibly_stock_limited = null;
  const out = text(render({ accuracy: body }));
  assert.ok(!EMPTY_AS_TEXT.test(out), 'no empty value printed as text');
  assert.ok(out.includes('32.4%'));
});

test('a blocked or empty answer renders the blocked card', () => {
  assert.match(text(render({ accuracy: { blocked_reason: REASON, accuracy_withheld: true, products: 0 } })), /Forecast error withheld/);
  assert.match(text(render({ accuracy: { products: 0 } })), /No forecasts were checked/);
  assert.equal(render({ accuracy: null }), '');
});
