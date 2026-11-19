// "Today" per principal and the ranges that move with it (2026-10-20): the
// latest month with real data comes from GET /data-mode's coverage, Del
// Monte's view ends at its own latest month, and "Last N months" follows it.
import test from 'node:test';
import assert from 'node:assert/strict';
import { LATEST_BY_PRINCIPAL, LATEST_DATA_PERIOD, latestFor, staleCoverageNotice } from './dataCoverage.js';
import { calendarYearRange, lastNRange, quickRanges } from './periodFilter.js';

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

test('rolling ranges end at the principal’s own latest month', () => {
  assert.deepEqual(lastNRange(12, { month: 'Feb', year: '2026' }),
    { startMonth: 'Mar', startYear: '2025', endMonth: 'Feb', endYear: '2026' });
  assert.deepEqual(lastNRange(12, { month: 'Dec', year: '2025' }),
    { startMonth: 'Jan', startYear: '2025', endMonth: 'Dec', endYear: '2025' });
  assert.deepEqual(lastNRange(6, { month: 'Feb', year: '2026' }),
    { startMonth: 'Sep', startYear: '2025', endMonth: 'Feb', endYear: '2026' });
});

test('calendar-year ranges lead and include the latest year even when it is incomplete', () => {
  const unilever = quickRanges(2023, { month: 'Feb', year: '2026' });
  const delmonte = quickRanges(2023, { month: 'Dec', year: '2025' });
  assert.deepEqual(unilever.slice(0, 4).map((q) => q.label), ['2026', '2025', '2024', '2023']);
  assert.deepEqual(unilever[0].range, calendarYearRange(2026));
  assert.equal(unilever[0].subtitle, 'Jan–Dec · overall data through Feb');
  assert.equal(unilever[1].subtitle, 'Jan–Dec');
  assert.deepEqual(unilever.slice(4).map((q) => q.key), ['last6', 'last12', 'last24']);
  assert.deepEqual(unilever.find((q) => q.key === 'last12').range.endMonth, 'Feb');
  assert.deepEqual(delmonte.find((q) => q.key === 'last12').range,
    { startMonth: 'Jan', startYear: '2025', endMonth: 'Dec', endYear: '2025' });
  assert.deepEqual(delmonte.filter((q) => q.key.startsWith('y')).map((q) => q.label), ['2025', '2024', '2023']);
});

test('calendar years use overall coverage while rolling ranges stay principal-specific', () => {
  const ranges = quickRanges(2023, { month: 'Dec', year: '2025' }, { month: 'Feb', year: '2026' });
  assert.deepEqual(ranges.filter((q) => q.key.startsWith('y')).map((q) => q.label), ['2026', '2025', '2024', '2023']);
  assert.equal(ranges[0].subtitle, 'Jan–Dec · overall data through Feb');
  assert.deepEqual(ranges.find((q) => q.key === 'last12').range,
    { startMonth: 'Jan', startYear: '2025', endMonth: 'Dec', endYear: '2025' });
});

test('the stale notice fires only when the payload knows a newer month than the filters end on', () => {
  assert.equal(staleCoverageNotice('2026-02', { month: 'Feb', year: '2026' }), null);
  assert.deepEqual(staleCoverageNotice('2026-03', { month: 'Feb', year: '2026' }), { live: 'Mar 2026', pinned: 'Feb 2026' });
  assert.equal(staleCoverageNotice(null, { month: 'Feb', year: '2026' }), null);
});
