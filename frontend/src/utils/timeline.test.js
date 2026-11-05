// node --test (npm test).
import test from 'node:test';
import assert from 'node:assert/strict';
import { labelledMonths, monthsBetween, monthsEarlier, showsYear, timelineMonths, yearEarlier } from './timeline.js';

test('months earlier, across a year end', () => {
  assert.equal(monthsEarlier('2026-02', 6), '2025-08');
  assert.equal(monthsEarlier('2026-02', 12), '2025-02');
  assert.equal(monthsEarlier('2026-02', 24), '2024-02');
  assert.equal(monthsEarlier(null, 12), null);
});

test('months between two months, across a year end', () => {
  assert.deepEqual(monthsBetween('2025-11', '2026-02'), ['2025-11', '2025-12', '2026-01', '2026-02']);
  assert.equal(monthsBetween('2025-03', '2026-02').length, 12);
  assert.deepEqual(monthsBetween('2026-02', '2025-03'), []);
  assert.deepEqual(monthsBetween(null, '2025-03'), []);
});

test('the timeline runs from the first to the last month with a figure, gaps kept', () => {
  const points = [
    { period: '2025-03', sales: null },
    { period: '2025-04', sales: 5 },
    { period: '2025-05', sales: null },
    { period: '2025-06', stockOnHand: 9 },
    { period: '2025-07', sales: null },
  ];
  assert.deepEqual(timelineMonths(points, ['sales', 'stockOnHand']), ['2025-04', '2025-05', '2025-06']);
  assert.deepEqual(timelineMonths([{ period: '2025-03', sales: null }], ['sales']), []);
});

test('the same month a year earlier', () => {
  assert.equal(yearEarlier('2026-02'), '2025-02');
  assert.equal(yearEarlier('2025-12'), '2024-12');
  assert.equal(yearEarlier(null), null);
});

test('labels: every month up to 24, then every third month plus each January', () => {
  const twelve = monthsBetween('2025-03', '2026-02');
  assert.equal(labelledMonths(twelve).length, 12);
  const long = monthsBetween('2021-01', '2026-02');
  const shown = labelledMonths(long);
  assert.ok(shown.includes('2021-01') && shown.includes('2022-01') && shown.includes('2026-01'));
  assert.ok(shown.includes('2021-04') && !shown.includes('2021-02'));
  assert.ok(shown.length < long.length / 2);
});

test('the year goes under January and under the first month', () => {
  assert.equal(showsYear('2025-03', '2025-03'), true);
  assert.equal(showsYear('2026-01', '2025-03'), true);
  assert.equal(showsYear('2025-07', '2025-03'), false);
});
