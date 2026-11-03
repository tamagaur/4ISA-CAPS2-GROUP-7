// The month-by-month timeline of the dashboard's Sales vs Inventory Value
// card (Charts.jsx, SalesVsStockWidget; 2026-10-19, replacing the Jan–Dec
// year overlay). Periods are 'YYYY-MM' strings; nothing here touches a
// figure. Tested by timeline.test.js (`npm test`).

const ord = (period) => Number(period.slice(0, 4)) * 12 + Number(period.slice(5, 7)) - 1;
const fromOrd = (n) => `${Math.floor(n / 12)}-${String((n % 12) + 1).padStart(2, '0')}`;

// Every month from `first` to `last`, both included, in order.
export function monthsBetween(first, last) {
  if (!first || !last || ord(first) > ord(last)) return [];
  return Array.from({ length: ord(last) - ord(first) + 1 }, (_, i) => fromOrd(ord(first) + i));
}

// The timeline's months: from the first to the last month in `points` that
// has any of `fields`, with every month between (a month with no figure
// stays on the axis, so a gap shows as a gap). [] when nothing has a figure.
export function timelineMonths(points, fields) {
  const filled = (points || [])
    .filter((pt) => fields.some((f) => pt[f] != null))
    .map((pt) => pt.period)
    .sort();
  return filled.length ? monthsBetween(filled[0], filled[filled.length - 1]) : [];
}

// The same month a year earlier: '2026-02' -> '2025-02'.
export function yearEarlier(period) {
  return period ? `${Number(period.slice(0, 4)) - 1}${period.slice(4)}` : null;
}

// `n` months before a month: ('2026-02', 6) -> '2025-08'.
export function monthsEarlier(period, n) {
  return period ? fromOrd(ord(period) - n) : null;
}

// The months whose tick gets a label: every month up to `every` months
// long; past that, every third month from the first, plus every January
// (and the first month, so the start is dated).
export function labelledMonths(months, max = 24) {
  if (months.length <= max) return months;
  return months.filter((p, i) => i === 0 || i % 3 === 0 || p.slice(5, 7) === '01');
}

// Whether a tick carries its year on a second line: every January, and the
// first month on the axis.
export function showsYear(period, first) {
  return period === first || period.slice(5, 7) === '01';
}
