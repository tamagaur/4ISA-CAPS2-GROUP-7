import test from 'node:test';
import assert from 'node:assert/strict';
import { calendarYearView } from './calendarYearView.js';

const levels = (annual, monthly) => [
  { pct: 103, annual, monthly },
  { pct: 105, annual: annual == null ? null : annual * 105 / 103, monthly: monthly * 105 / 103 },
  { pct: 108, annual: annual == null ? null : annual * 108 / 103, monthly: monthly * 108 / 103 },
];

test('a complete selected year compares with the previous full year and targets its successor', () => {
  const view = calendarYearView({
    years: [
      { year: 2024, sales: 1000, months: 12, allocation_levels: [] },
      {
        year: 2025, sales: 1200, months: 12, allocation_levels: levels(1236, 103),
        comparison: { sales: 1000, months: 12, label: '2024' },
      },
    ],
  }, { allocation_year: 2026, basis_year: 2025, default_pct: 103, levels: levels(1236, 103) }, 2025);

  assert.equal(view.year, 2025);
  assert.equal(view.targetYear, 2026);
  assert.equal(view.sales, 1200);
  assert.deepEqual(view.yoy, { pct: 20, label: '2024' });
  assert.equal(view.allocation.allocation_year, 2026);
  assert.equal(view.allocation.basis_year, 2025);
});

test('an incomplete latest year compares only matching recorded months', () => {
  const view = calendarYearView({
    years: [
      { year: 2025, sales: 900, months: 12, allocation_levels: [] },
      {
        year: 2026, sales: 230, months: 2, allocation_levels: levels(null, 118.45),
        comparison: { sales: 180, months: 2, label: 'same months in 2025' },
      },
    ],
  }, {
    allocation_year: 2026,
    basis_year: 2025,
    default_pct: 103,
    levels: levels(927, 77.25),
  }, 2026);

  assert.equal(view.targetYear, 2027);
  assert.equal(view.levels[0].annual, null);
  assert.equal(view.levels[0].monthly, 118.45);
  assert.deepEqual(view.yoy, { pct: (50 / 180) * 100, label: 'same months in 2025' });
  assert.equal(view.comparisonNote, null);
});

test('it does not compare incomplete years with mismatched recorded months', () => {
  const view = calendarYearView({
    years: [
      { year: 2023, sales: 100, months: 12, allocation_levels: [] },
      { year: 2024, sales: 50, months: 3, allocation_levels: levels(null, 17.17) },
    ],
  }, { default_pct: 103 }, 2024);

  assert.equal(view.yoy, null);
  assert.match(view.comparisonNote, /same months are not recorded/);
});

test('an unrecorded calendar year has no sales or allocation target', () => {
  const view = calendarYearView({ years: [] }, { default_pct: 103 }, 2026);

  assert.equal(view.sales, null);
  assert.equal(view.levels.length, 0);
  assert.match(view.blockedReason, /No sales are on record/);
});
