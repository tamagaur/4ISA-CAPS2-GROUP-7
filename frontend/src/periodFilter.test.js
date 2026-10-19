// "Today" per principal and the ranges that move with it (2026-10-20): the
// latest month with real data comes from GET /data-mode's coverage, Del
// Monte's view ends at its own latest month, and "Last N months" follows it.
import test from 'node:test';
import assert from 'node:assert/strict';
import { LATEST_BY_PRINCIPAL, LATEST_DATA_PERIOD, latestFor, staleCoverageNotice } from './dataCoverage.js';
import { lastNRange, quickRanges } from './periodFilter.js';

const coverage = {
  first_data_period: '2023-01',
  latest_data_period: '2026-03',
  latest_data_period_by_principal: { unilever: '2026-03', delmonte: '2026-01' },
};

test('latestFor reads each principal from the API, the later of the two for all', () => {
  assert.deepEqual(latestFor(coverage, 'unilever'), { month: 'Mar', year: '2026' });
  assert.deepEqual(latestFor(coverage, 'delmonte'), { month: 'Jan', year: '2026' });
  assert.deepEqual(latestFor(coverage, 'all'), { month: 'Mar', year: '2026' });
});

test('latestFor falls back to the constants until the API answers', () => {
  assert.deepEqual(latestFor(null, 'all'), LATEST_DATA_PERIOD);
  assert.deepEqual(latestFor(null, 'delmonte'), LATEST_BY_PRINCIPAL.delmonte);
  assert.deepEqual(latestFor({ latest_data_period_by_principal: {} }, 'unilever'), LATEST_BY_PRINCIPAL.unilever);
});

test('the default 12 months end at the principal’s own latest month', () => {
  assert.deepEqual(lastNRange(12, { month: 'Feb', year: '2026' }),
    { startMonth: 'Mar', startYear: '2025', endMonth: 'Feb', endYear: '2026' });
  assert.deepEqual(lastNRange(12, { month: 'Dec', year: '2025' }),
    { startMonth: 'Jan', startYear: '2025', endMonth: 'Dec', endYear: '2025' });
  assert.deepEqual(lastNRange(6, { month: 'Feb', year: '2026' }),
    { startMonth: 'Sep', startYear: '2025', endMonth: 'Feb', endYear: '2026' });
});

test('quick ranges follow the latest month passed in, and offer only whole years', () => {
  const unilever = quickRanges(2023, { month: 'Feb', year: '2026' });
  const delmonte = quickRanges(2023, { month: 'Dec', year: '2025' });
  assert.deepEqual(unilever.find((q) => q.key === 'last12').range.endMonth, 'Feb');
  assert.deepEqual(delmonte.find((q) => q.key === 'last12').range,
    { startMonth: 'Jan', startYear: '2025', endMonth: 'Dec', endYear: '2025' });
  assert.deepEqual(unilever.filter((q) => q.key.startsWith('y')).map((q) => q.label), ['2025', '2024', '2023']);
  assert.ok(delmonte.some((q) => q.key === 'y2025'), 'a year whose December has data is offered');
});

test('the stale notice fires only when the payload knows a newer month than the filters end on', () => {
  assert.equal(staleCoverageNotice('2026-02', { month: 'Feb', year: '2026' }), null);
  assert.deepEqual(staleCoverageNotice('2026-03', { month: 'Feb', year: '2026' }), { live: 'Mar 2026', pinned: 'Feb 2026' });
  assert.equal(staleCoverageNotice(null, { month: 'Feb', year: '2026' }), null);
});
