// node --test (npm test).
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  comparedMonthsMissing, comparisonRows, longMonth, monthRuns, monthWindows, oppositeMovement, periodChange, periodsLabel, stripScale, yearGroupsOf,
} from './periodComparison.js';
import { monthsBetween } from './timeline.js';

const figures = (period, sales, stockOnHand) => ({ period, sales, stockOnHand });
const byPeriod = (rows, period) => rows.find((row) => row.period === period);

test('a period is named the way the date bar names it, closed up for the legend', () => {
  assert.equal(periodsLabel('2025-03', '2026-02'), 'Mar 2025 – Feb 2026');
  assert.equal(periodsLabel('2025-03', '2026-02', { compact: true }), 'Mar 2025–Feb 2026');
  assert.equal(periodsLabel('2023-01', '2023-01'), 'Jan 2023');
  assert.equal(periodsLabel(null, '2023-01'), '');
});

test('missing months are named as runs', () => {
  assert.equal(monthRuns(['2022-02', '2022-01', '2022-03']), 'Jan 2022 – Mar 2022');
  assert.equal(monthRuns(['2022-01', '2022-02', '2023-03']), 'Jan 2022 – Feb 2022, Mar 2023');
  assert.equal(monthRuns(['2024-12', '2025-01']), 'Dec 2024 – Jan 2025');
  assert.equal(monthRuns([]), '');
});

test('change is selected minus compared, as a percent of the compared figure', () => {
  assert.deepEqual(periodChange(110, 100), { amount: 10, pct: 10 });
  assert.deepEqual(periodChange(90, 100), { amount: -10, pct: -10 });
  // A compared figure of 0 or below has no percent to give.
  assert.deepEqual(periodChange(50, 0), { amount: 50, pct: null });
  assert.deepEqual(periodChange(50, -10), { amount: 60, pct: null });
  assert.equal(periodChange(null, 100), null);
  assert.equal(periodChange(100, null), null);
  // A recorded 0 is a figure.
  assert.deepEqual(periodChange(0, 100), { amount: -100, pct: -100 });
});

test('12 months against same months last year: each month with the same month a year earlier', () => {
  const months = monthsBetween('2025-03', '2026-02');
  const rows = comparisonRows({
    months,
    points: [figures('2025-09', 120, 40), figures('2026-02', 90, 50)],
    comparePoints: [figures('2024-09', 100, 30), figures('2025-02', 100, 25)],
    shift: 12,
  });
  assert.equal(rows.length, 12);
  assert.deepEqual(rows.map((r) => r.period), months);
  const sep = byPeriod(rows, '2025-09');
  assert.equal(sep.comparePeriod, '2024-09');
  assert.equal(sep.salesC, 100);
  assert.equal(sep.stockC, 30);
  assert.deepEqual(sep.change.sales, { amount: 20, pct: 20 });
  assert.equal(byPeriod(rows, '2026-02').comparePeriod, '2025-02');
});

test('6 months against the previous period: month N with month N, not the same calendar month', () => {
  const rows = comparisonRows({
    months: monthsBetween('2025-09', '2026-02'),
    points: [figures('2025-09', 120, 40)],
    comparePoints: [figures('2025-03', 100, 30)],
    shift: 6,
  });
  assert.deepEqual(rows.map((r) => r.comparePeriod), ['2025-03', '2025-04', '2025-05', '2025-06', '2025-07', '2025-08']);
  assert.equal(rows[0].salesC, 100);
});

test('24 months against a year earlier: every month kept, and overlapping months read correctly', () => {
  const months = monthsBetween('2024-03', '2026-02');
  const points = months.map((period, i) => figures(period, 100 + i, 50 + i));
  const comparePoints = monthsBetween('2023-03', '2025-02').map((period, i) => figures(period, 1 + i, 2 + i));
  const rows = comparisonRows({ months, points, comparePoints, shift: 12 });
  assert.equal(rows.length, 24);
  assert.equal(new Set(rows.map((r) => r.period)).size, 24);
  // Compared with a month outside the range: its own answer.
  assert.equal(byPeriod(rows, '2024-03').comparePeriod, '2023-03');
  assert.equal(byPeriod(rows, '2024-03').salesC, 1);
  // Compared with a month inside the range: that month's figure, not duplicated or lost.
  assert.equal(byPeriod(rows, '2025-03').comparePeriod, '2024-03');
  assert.equal(byPeriod(rows, '2025-03').salesC, 100);
  assert.equal(byPeriod(rows, '2024-03').sales, 100);
});

test('before the data starts: no earlier data, and never a 0', () => {
  const rows = comparisonRows({
    months: monthsBetween('2023-01', '2024-02'),
    points: monthsBetween('2023-01', '2024-02').map((period) => figures(period, 100, 50)),
    shift: 12,
    floor: '2023-01',
  });
  const jan2023 = byPeriod(rows, '2023-01');
  assert.equal(jan2023.comparePeriod, '2022-01');
  assert.equal(jan2023.noEarlier, true);
  assert.equal(jan2023.salesC, null);
  assert.equal(jan2023.stockC, null);
  assert.equal(jan2023.change.sales, null);
  // Jan 2024 is compared with Jan 2023, which is on the page.
  const jan2024 = byPeriod(rows, '2024-01');
  assert.equal(jan2024.noEarlier, false);
  assert.equal(jan2024.salesC, 100);
  assert.deepEqual(comparedMonthsMissing(rows, ['salesC', 'stockC']).slice(0, 2), ['2022-01', '2022-02']);
  assert.equal(comparedMonthsMissing(rows, ['salesC', 'stockC']).length, 12);
});

test('a gap inside the records is not "no earlier data"', () => {
  const rows = comparisonRows({
    months: ['2025-03'],
    points: [figures('2025-03', 100, 50)],
    comparePoints: [],
    shift: 12,
    floor: '2023-01',
  });
  assert.equal(rows[0].noEarlier, false);
  assert.equal(rows[0].salesC, null);
});

test('no comparison: nothing compared, even when the earlier month is on the page', () => {
  const months = monthsBetween('2024-03', '2026-02');
  const rows = comparisonRows({ months, points: months.map((period) => figures(period, 100, 50)) });
  const row = byPeriod(rows, '2025-03');
  assert.equal(row.comparePeriod, null);
  assert.equal(row.salesC, null);
  assert.equal(row.stockC, null);
  assert.deepEqual(row.change, {});
  assert.deepEqual(comparedMonthsMissing(rows, ['salesC']), []);
});

test('a missing figure stays null, a recorded 0 stays 0, and one metric missing leaves the other', () => {
  const rows = comparisonRows({
    months: ['2025-06', '2025-07', '2025-08'],
    points: [figures('2025-06', null, 50), figures('2025-07', 0, null)],
    comparePoints: [figures('2024-06', 40, 30), figures('2024-07', null, 0)],
    shift: 12,
  });
  assert.equal(rows[0].sales, null);
  assert.equal(rows[0].stock, 50);
  assert.equal(rows[1].sales, 0);
  assert.equal(rows[1].stock, null);
  assert.equal(rows[1].salesC, null);
  assert.equal(rows[1].stockC, 0);
  // A selected month with no row at all stays on the axis as a gap.
  assert.equal(rows[2].period, '2025-08');
  assert.equal(rows[2].sales, null);
});

test('synthetic months are kept apart, on both sides, and never produce a change', () => {
  const isReal = (pt) => !pt.salesSynthetic;
  const rows = comparisonRows({
    months: ['2025-03', '2025-04', '2025-05'],
    points: [
      figures('2025-03', 100, 50),
      { ...figures('2025-04', 70, 50), salesSynthetic: true },
      figures('2025-05', 110, 50),
    ],
    comparePoints: [
      { ...figures('2024-03', 90, 40), salesSynthetic: true },
      figures('2024-04', 80, 40),
      figures('2024-05', 100, 40),
    ],
    shift: 12,
    isReal,
  });
  assert.equal(rows[0].salesC, null);
  assert.equal(rows[0].salesestC, 90);
  assert.equal(rows[0].change.sales, null);
  assert.equal(rows[1].sales, null);
  assert.equal(rows[1].salesest, 70);
  assert.equal(rows[1].change.sales, null);
  assert.deepEqual(rows[2].change.sales, { amount: 10, pct: 10 });
  // The dotted line joins the solid one on each side of the synthetic month.
  assert.equal(rows[0].salesestLine, 100);
  assert.equal(rows[1].salesestLine, 70);
  assert.equal(rows[2].salesestLine, 110);
});

test('a flagged count stays visible and is flagged with or without a recorded reason', () => {
  const rows = comparisonRows({
    months: ['2026-01', '2026-02'],
    points: [
      { ...figures('2026-01', 10, 20), stockFlagged: true, stockUnusual: null },
      { ...figures('2026-02', 10, 46), stockFlagged: true, stockUnusual: 'About twice the count before' },
    ],
    comparePoints: [{ ...figures('2025-01', 10, 20), stockFlagged: true, stockUnusual: 'Earlier reason' }],
    shift: 12,
  });
  assert.equal(rows[0].flagged, true);
  assert.equal(rows[0].stock, 20);
  assert.equal(rows[0].flaggedC, true);
  assert.equal(rows[0].stockC, 20);
  assert.equal(rows[1].flagged, true);
  assert.equal(rows[1].flaggedC, false);
});

test('purchases: same definitions on both sides, flagged by this count or the one before', () => {
  const rows = comparisonRows({
    months: ['2026-01', '2026-02'],
    points: [
      { period: '2026-01', sales: 10, receivedEstimated: -5 },
      { period: '2026-02', sales: 10, receivedEstimated: 30, stockFlagged: true },
    ],
    comparePoints: [
      { period: '2024-12', stockFlagged: true },
      { period: '2025-01', sales: 10, receivedEstimated: 20 },
      { period: '2025-02', sales: 10, receivedEstimated: 25 },
    ],
    shift: 12,
  });
  // A negative estimate is drawn at 0, and keeps its own figure for the note.
  assert.equal(rows[0].bought, 0);
  assert.equal(rows[0].purch, -5);
  assert.equal(rows[0].boughtC, 20);
  assert.equal(rows[0].purchFlagC, true);
  assert.equal(rows[1].purchFlag, true);
  assert.equal(rows[1].boughtC, 25);
  assert.equal(rows[1].purchFlagC, false);
  assert.equal(rows[1].net, 20);
});

test('weeks of stock uses the caller\'s calculation on real months only', () => {
  const weeksOf = (stock, sales) => (stock != null && sales > 0 ? stock / sales : null);
  const rows = comparisonRows({
    months: ['2026-02'],
    points: [figures('2026-02', 10, 30)],
    comparePoints: [{ ...figures('2025-02', 10, 20), salesSynthetic: true }],
    shift: 12,
    isReal: (pt) => !pt.salesSynthetic,
    weeksOf,
  });
  assert.equal(rows[0].weeks, 3);
  assert.equal(rows[0].weeksC, null);
  assert.equal(rows[0].change.weeks, null);
});

test('the hover names a month in full', () => {
  assert.equal(longMonth('2025-09'), 'September 2025');
  assert.equal(longMonth('2024-01'), 'January 2024');
  assert.equal(longMonth(null), '');
});

test('windows: 24 months in two of 12, from the first month', () => {
  const windows = monthWindows(monthsBetween('2024-03', '2026-02'), 12);
  assert.equal(windows.length, 2);
  assert.deepEqual([windows[0][0], windows[0][11]], ['2024-03', '2025-02']);
  assert.deepEqual([windows[1][0], windows[1][11]], ['2025-03', '2026-02']);
});

test('windows: a selection that fits is one window, and a remainder is a shorter last one', () => {
  assert.equal(monthWindows(monthsBetween('2025-03', '2026-02'), 12).length, 1);
  assert.equal(monthWindows(monthsBetween('2025-09', '2026-02'), 12).length, 1);
  const eighteen = monthWindows(monthsBetween('2024-09', '2026-02'), 12);
  assert.deepEqual(eighteen.map((w) => w.length), [12, 6]);
  assert.equal(eighteen[1][0], '2025-09');
  // A phone: 12 months at 6 a time.
  assert.deepEqual(monthWindows(monthsBetween('2025-03', '2026-02'), 6).map((w) => w.length), [6, 6]);
});

test('windows lose and repeat nothing', () => {
  const months = monthsBetween('2023-01', '2026-02');
  const windows = monthWindows(months, 12);
  assert.deepEqual(windows.flat(), months);
  assert.deepEqual(monthWindows([], 12), []);
});

test('strip scale: changes of a similar size all fit, with nothing cut', () => {
  const scale = stripScale([1.1, 7.8, 17.4, 3.6, -0.2, 1.9, 7.1, 4.9, -10.2, -20.6, -0.4, -7.2]);
  assert.deepEqual(scale, { limit: 25, clipped: false });
});

test('strip scale: one extreme month is cut rather than flattening the others', () => {
  const scale = stripScale([29, -27.5, 13.6, 234.8, 23, 43.5, 29.7, 35.9, 14.1, 5.5, 18, 105.2]);
  assert.equal(scale.limit, 50);
  assert.equal(scale.clipped, true);
});

test('strip scale: gaps are ignored, and nothing to show gives no scale', () => {
  assert.equal(stripScale([null, undefined]), null);
  assert.equal(stripScale([]), null);
  assert.deepEqual(stripScale([null, 8, null]), { limit: 10, clipped: false });
  // Only zeros still has a scale, so a 0% mark can be drawn.
  assert.deepEqual(stripScale([0, 0]), { limit: 5, clipped: false });
});

test('strip scale: past the largest listed limit it still covers the figure', () => {
  assert.deepEqual(stripScale([25000]), { limit: 30000, clipped: false });
});

test('the year band groups the months on show by calendar year', () => {
  assert.deepEqual(yearGroupsOf(['2025-09', '2025-10', '2025-11', '2025-12', '2026-01', '2026-02']), [
    { year: '2025', months: 4 },
    { year: '2026', months: 2 },
  ]);
  assert.deepEqual(yearGroupsOf(['2025-01', '2025-02']), [{ year: '2025', months: 2 }]);
  assert.deepEqual(yearGroupsOf([]), []);
});

test('opposite movement: only when both moved, the opposite way, by at least 1%', () => {
  const change = (sales, stock) => ({
    sales: sales == null ? null : { amount: sales, pct: sales },
    stock: stock == null ? null : { amount: stock, pct: stock },
  });
  assert.equal(oppositeMovement(change(-7.2, 105.2)), 'stockUp');
  assert.equal(oppositeMovement(change(10, -27.5)), 'stockDown');
  // The same direction is nothing to point out.
  assert.equal(oppositeMovement(change(5, 20)), null);
  assert.equal(oppositeMovement(change(-5, -20)), null);
  // Too small to call a decline.
  assert.equal(oppositeMovement(change(-0.2, 26.2)), null);
  assert.equal(oppositeMovement(change(5, -0.5)), null);
  assert.equal(oppositeMovement(change(0, 26.2)), null);
  // A missing figure, a synthetic month or a zero comparison gives no percent, so no message.
  assert.equal(oppositeMovement(change(null, 26.2)), null);
  assert.equal(oppositeMovement(change(-5, null)), null);
  assert.equal(oppositeMovement({ sales: { amount: -5, pct: null }, stock: { amount: 9, pct: 9 } }), null);
  assert.equal(oppositeMovement({}), null);
  assert.equal(oppositeMovement(undefined), null);
});

