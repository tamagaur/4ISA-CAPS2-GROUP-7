import test from 'node:test';
import assert from 'node:assert/strict';
import { demandHighlights, forecastWhy, labelsThatFit, missStatus, usableQuantity } from './forecastHighlights.js';

const series = [
  { period: '2025-03', actual: 1500 },
  { period: '2025-04', actual: 1700 },
  { period: '2025-05', actual: 600 },
  { period: '2025-06', actual: 900 },
  { period: '2025-07', actual: null, forecast: 1200, confidenceLower: 1050, confidenceUpper: 1380 },
];

test('the highest and lowest month come from actual demand only', () => {
  const h = demandHighlights(series);
  assert.deepEqual(h.peak, { period: '2025-04', value: 1700 });
  assert.deepEqual(h.low, { period: '2025-05', value: 600 });
});

test('the next forecast is the first month with a forecast and no actual, with its range', () => {
  assert.deepEqual(demandHighlights(series).next, { period: '2025-07', value: 1200, low: 1050, high: 1380 });
});

test('the bridge point (an actual month given its own value as forecast) is not the next forecast', () => {
  const bridged = series.map((p) => (p.period === '2025-06' ? { ...p, forecast: p.actual } : p));
  assert.equal(demandHighlights(bridged).next.period, '2025-07');
});

test('no high or low with one month, or a flat line; no range without both bounds', () => {
  assert.equal(demandHighlights([{ period: '2025-01', actual: 5 }]).peak, null);
  const flat = demandHighlights([{ period: '2025-01', actual: 5 }, { period: '2025-02', actual: 5 }]);
  assert.equal(flat.peak, null);
  assert.equal(flat.low, null);
  const noBand = demandHighlights([{ period: '2025-01', actual: 5 }, { period: '2025-02', actual: null, forecast: 7 }]);
  assert.deepEqual(noBand.next, { period: '2025-02', value: 7, low: null, high: null });
  assert.equal(demandHighlights([]).next, null);
});

test('a label that would collide with one already kept is dropped, in priority order', () => {
  const kept = labelsThatFit([{ idx: 10, width: 90 }, { idx: 9, width: 90 }, { idx: 2, width: 90 }], 40);
  assert.deepEqual(kept.map((k) => k.idx), [10, 2]);
  // Wide slots: all three fit.
  assert.equal(labelsThatFit([{ idx: 10, width: 90 }, { idx: 9, width: 90 }, { idx: 2, width: 90 }], 120).length, 3);
});

const why = (extra = {}) => forecastWhy({
  actuals: [
    { period: '2025-02', quantity: 900, reason: null },
    { period: '2025-03', quantity: 1200, reason: null },
    { period: '2025-12', quantity: 800, reason: null },
    { period: '2026-01', quantity: 950, reason: null },
    { period: '2026-02', quantity: 1100, reason: null },
  ],
  forecastPeriod: '2026-03',
  basisPeriod: '2026-02',
  principal: 'unilever',
  ...extra,
});
const byKey = (lines) => Object.fromEntries(lines.map((l) => [l.key, l.text]));

test('why: the last three months and the same months a year earlier, as observations', () => {
  const lines = byKey(why());
  assert.equal(lines.last_three, 'Sales rose in each of the last three months: about 800, 950 and 1,100 pcs (Dec 2025 – Feb 2026).');
  assert.equal(lines.last_year, 'A year earlier, sales rose from about 900 pcs in Feb 2025 to about 1,200 pcs in Mar 2025.');
  assert.equal(lines.calendar, undefined);
  assert.equal(lines.stock_limited, undefined);
});

test('why: falling and mixed months are said as they are', () => {
  const fall = why({ actuals: [
    { period: '2025-12', quantity: 1100 }, { period: '2026-01', quantity: 950 }, { period: '2026-02', quantity: 800 }] });
  assert.match(byKey(fall).last_three, /^Sales fell in each of the last three months/);
  const mixed = why({ actuals: [
    { period: '2025-12', quantity: 800 }, { period: '2026-01', quantity: 1100 }, { period: '2026-02', quantity: 950 }] });
  assert.match(byKey(mixed).last_three, /^Sales went up and down/);
});

test('why: a Unilever no_sale month is a real zero; a Del Monte gap or blank capture is never a value', () => {
  const zero = why({ actuals: [
    { period: '2025-03', quantity: 0, reason: 'no_sale' },
    { period: '2025-12', quantity: 0, reason: 'no_sale' }, { period: '2026-01', quantity: 5 }, { period: '2026-02', quantity: 9 }] });
  assert.equal(byKey(zero).last_year, 'In Mar 2025, the same month last year, it sold nothing.');
  assert.match(byKey(zero).last_three, /about 0, 5 and 9 pcs/);
  // The same zero under Del Monte (no_sale is not a Del Monte code) is left out.
  assert.equal(byKey(why({ principal: 'delmonte', actuals: [{ period: '2025-03', quantity: 0, reason: 'no_sale' }] })).last_year, undefined);
  const gaps = why({ principal: 'delmonte', actuals: [
    { period: '2025-12', quantity: null, reason: 'not_collected' }, { period: '2026-01', quantity: 5 }, { period: '2026-02', quantity: 9 }] });
  assert.equal(byKey(gaps).last_three, undefined);
  const blank = why({ actuals: [
    { period: '2025-12', quantity: null, reason: 'blank_capture' }, { period: '2026-01', quantity: 5 }, { period: '2026-02', quantity: 9 }] });
  assert.equal(byKey(blank).last_three, undefined);
});

test('why: months where returns outweighed sales are said as net sales, never as a rise or fall', () => {
  const net = why({ actuals: [
    { period: '2025-12', quantity: -12 }, { period: '2026-01', quantity: 0, reason: 'no_sale' }, { period: '2026-02', quantity: -33 }] });
  assert.equal(byKey(net).last_three,
    'Net sales over the last three months were about −12, 0 and −33 pcs (Dec 2025 – Feb 2026): returns outweighed sales in 2 of them.');
  const lastYear = why({ actuals: [{ period: '2025-02', quantity: 40 }, { period: '2025-03', quantity: -5 }] });
  assert.equal(byKey(lastYear).last_year,
    'A year earlier, net sales were about 40 pcs in Feb 2025 and −5 pcs in Mar 2025 (returns outweighed sales).');
  const alone = why({ actuals: [{ period: '2025-03', quantity: -5 }] });
  assert.equal(byKey(alone).last_year, 'In Mar 2025, the same month last year, returns outweighed sales (net about −5 pcs).');
});

test('why: a month the API did not send, or a generated month, is never assumed', () => {
  const missing = why({ actuals: [{ period: '2026-01', quantity: 5 }, { period: '2026-02', quantity: 9 }] });
  assert.deepEqual(missing, []);
  const generated = why({ actuals: [
    { period: '2025-03', quantity: 400, reason: 'interpolated' },
    { period: '2025-12', quantity: 4, reason: 'no_data_recorded_before_2023' }, { period: '2026-01', quantity: 5 }, { period: '2026-02', quantity: 9 }] });
  assert.deepEqual(generated, []);
});

test('why: the calendar factor in words, raised, lowered, or none on record', () => {
  assert.equal(byKey(why({ calendar: { factor: 1.0762, years: 2 } })).calendar,
    'For this product, March has on average sold more than the 3 months before it (2 earlier years), so the forecast is raised by about 7.6%.');
  assert.match(byKey(why({ calendar: { factor: 0.95, years: 1 } })).calendar, /sold less .*\(1 earlier year\), so the forecast is lowered by about 5\.0%\.$/);
  assert.equal(byKey(why({ calendar: { factor: 1, years: 0 } })).calendar,
    'No calendar adjustment: there is no earlier March on record to compare with.');
  assert.equal(byKey(why({ calendar: null })).calendar, undefined);
});

test('why: stock-limited months in the last three are named, outside them not', () => {
  assert.equal(byKey(why({ stockLimited: ['2026-02'] })).stock_limited,
    'Feb 2026 is flagged: stock may have run out, so real demand may have been higher than sales.');
  assert.match(byKey(why({ stockLimited: ['2026-01', '2026-02'] })).stock_limited, /^Jan 2026 and Feb 2026 are flagged/);
  assert.equal(byKey(why({ stockLimited: ['2025-06'] })).stock_limited, undefined);
});

test('why: lines come in a fixed order and nothing without periods', () => {
  const keys = why({ stockLimited: ['2026-02'], calendar: { factor: 1.0762, years: 2 } }).map((l) => l.key);
  assert.deepEqual(keys, ['last_three', 'stock_limited', 'last_year', 'calendar']);
  assert.deepEqual(forecastWhy(), []);
  assert.equal(usableQuantity({ quantity: 3, reason: 'no_sale' }, 'unilever'), 3);
  assert.equal(usableQuantity({ quantity: 3, reason: 'category_absent' }, 'delmonte'), null);
});

test('why: figures are rounded like the headline, the exact one kept on its part (2026-10-26)', () => {
  const big = why({ actuals: [
    { period: '2025-12', quantity: 65576 }, { period: '2026-01', quantity: 174230 }, { period: '2026-02', quantity: 107739 }] });
  const line = big.find((l) => l.key === 'last_three');
  assert.equal(line.text, 'Sales went up and down over the last three months: about 66,000, 174,000 and 108,000 pcs (Dec 2025 – Feb 2026).');
  assert.deepEqual(line.parts.filter((p) => typeof p !== 'string').map((p) => p.value), [65576, 174230, 107739]);
  // The parts join back to the text.
  assert.equal(line.parts.map((p) => (typeof p === 'string' ? p : p.text)).join(''), line.text);
  // 1,000-9,999 to the nearest 100.
  assert.match(byKey(why({ actuals: [{ period: '2025-03', quantity: 1234 }] })).last_year, /about 1,200 pcs/);
});

test('why: a rise next month against a longer-run fall gets one bridging line, only when both are known', () => {
  const bridge = byKey(why({ longTermTrend: 'down', changePct: 24, calendar: { factor: 1.0762, years: 2 } })).trend_bridge;
  assert.equal(bridge, 'Over the longer run (since its first sale), sales of this product have been going down. '
    + "Next month's higher figure is a comparison with Feb 2026 only; what changed around it is the last three months, "
    + 'the same month last year and the calendar adjustment, above.');
  assert.match(byKey(why({ longTermTrend: 'up', changePct: -10 })).trend_bridge, /going up\. Next month's lower figure/);
  // Same direction, no direction, no change, or about the same: no line.
  assert.equal(byKey(why({ longTermTrend: 'up', changePct: 24 })).trend_bridge, undefined);
  assert.equal(byKey(why({ longTermTrend: 'none', changePct: 24 })).trend_bridge, undefined);
  assert.equal(byKey(why({ longTermTrend: null, changePct: 24 })).trend_bridge, undefined);
  assert.equal(byKey(why({ longTermTrend: 'down', changePct: null })).trend_bridge, undefined);
  assert.equal(byKey(why({ longTermTrend: 'down', changePct: 0.3 })).trend_bridge, undefined);
  // Nothing above to point at: no line.
  assert.deepEqual(why({ actuals: [], longTermTrend: 'down', changePct: 24 }), []);
  assert.equal(why({ longTermTrend: 'down', changePct: 24 }).at(-1).key, 'trend_bridge');
});

test('a month is too high above zero, too low below, a match at exactly zero', () => {
  assert.equal(missStatus(1), 'high');
  assert.equal(missStatus(-0.5), 'low');
  assert.equal(missStatus(0), 'exact');
  assert.equal(missStatus(null), null);
});
