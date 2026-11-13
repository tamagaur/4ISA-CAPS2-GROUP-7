// The shared filters' logic in one place: the comparison every page makes,
// the quick ranges, and reading/writing periods in the address.
//
// Technical Adviser, 2 Oct 2026: "the story is in the changes", and a
// comparison must never change meaning silently (a month against the month
// before, shown as if it were the range). So there is one comparison for the
// whole app, named on screen wherever it is used:
//   year     — the same months a year earlier (default: FMCG sales are
//              seasonal, so this is the like-for-like one; it is also his
//              own question, "2025 vs 2024?")
//   previous — the same number of months just before the range
//   none     — no comparison
import { FIRST_DATA_YEAR } from './dataCoverage.js';

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export const COMPARE_MODES = { YEAR: 'year', PREVIOUS: 'previous', NONE: 'none' };
export const COMPARE_STORAGE_KEY = 'san2_compare_v1';
export const COMPARE_OPTIONS = [
  { value: COMPARE_MODES.YEAR, label: 'Same months last year' },
  { value: COMPARE_MODES.PREVIOUS, label: 'Previous period' },
  { value: COMPARE_MODES.NONE, label: 'No comparison' },
];
export const isValidCompare = (value) => Object.values(COMPARE_MODES).includes(value);

const ordinal = (month, year) => Number(year) * 12 + MONTHS.indexOf(month);
const fromOrdinal = (n) => ({ month: MONTHS[((n % 12) + 12) % 12], year: String(Math.floor(n / 12)) });

// 'Mar', '2025' -> '2025-03'
export const periodToParam = (month, year) => {
  const i = MONTHS.indexOf(month);
  return i >= 0 && /^\d{4}$/.test(String(year)) ? `${year}-${String(i + 1).padStart(2, '0')}` : null;
};

// '2025-03' -> { month: 'Mar', year: '2025' }; null for anything else.
export const periodFromParam = (value) => {
  const m = /^(\d{4})-(\d{2})$/.exec(value || '');
  if (!m) return null;
  const i = Number(m[2]) - 1;
  return i >= 0 && i < 12 ? { month: MONTHS[i], year: m[1] } : null;
};

export const monthCount = (range) =>
  ordinal(range.endMonth, range.endYear) - ordinal(range.startMonth, range.startYear) + 1;

export const rangeText = (range) => (range
  ? `${range.startMonth} ${range.startYear} – ${range.endMonth} ${range.endYear}`
  : '');

// The range every comparison on the page is against, or null for 'none'.
// `floor` is the first month any data exists ({ month, year }); a comparison
// that would start before it is returned with `beforeData` set, so the page
// says there is nothing to compare with instead of comparing with gaps.
export function comparisonRange(range, compare, floor = { month: 'Jan', year: String(FIRST_DATA_YEAR) }) {
  if (!range || compare === COMPARE_MODES.NONE || !isValidCompare(compare)) return null;
  const shift = compare === COMPARE_MODES.YEAR ? 12 : monthCount(range);
  const start = fromOrdinal(ordinal(range.startMonth, range.startYear) - shift);
  const end = fromOrdinal(ordinal(range.endMonth, range.endYear) - shift);
  const out = { startMonth: start.month, startYear: start.year, endMonth: end.month, endYear: end.year };
  return {
    ...out,
    shift,
    startPeriod: periodToParam(out.startMonth, out.startYear),
    endPeriod: periodToParam(out.endMonth, out.endYear),
    label: rangeText(out),
    beforeData: ordinal(out.startMonth, out.startYear) < ordinal(floor.month, floor.year),
  };
}

// The months of a comparison at or after `floor` (the first month any data
// exists), for a chart that can show part of one: { startPeriod, endPeriod },
// or null when all of it is before the data. The summary cards don't use this:
// they compare whole periods, so a part of one would mislead them.
export function comparisonAvailable(versus, floor = { month: 'Jan', year: String(FIRST_DATA_YEAR) }) {
  if (!versus) return null;
  const first = ordinal(floor.month, floor.year);
  if (ordinal(versus.endMonth, versus.endYear) < first) return null;
  if (ordinal(versus.startMonth, versus.startYear) >= first) {
    return { startPeriod: versus.startPeriod, endPeriod: versus.endPeriod };
  }
  return { startPeriod: periodToParam(floor.month, floor.year), endPeriod: versus.endPeriod };
}

// The last `n` months ending at `latest` ({ month, year }): the quick ranges
// that move with the data. The default view is lastNRange(12, latest).
export const RELATIVE_RANGES = { last6: 6, last12: 12, last24: 24 };
export function lastNRange(n, latest) {
  const end = ordinal(latest.month, latest.year);
  const start = fromOrdinal(end - n + 1);
  return { startMonth: start.month, startYear: start.year, endMonth: latest.month, endYear: String(latest.year) };
}

// The quick ranges. Each is at least six months, the picker's own minimum,
// and inside the data (Jan 2023 to the latest month). A whole calendar year
// is offered only once all twelve of its months are in the data.
// `firstYear`: the earliest whole year offered (synthetic mode reaches back
// to 2021; real data starts in FIRST_DATA_YEAR). `latest`: the latest month
// with data for the page's principal (dataCoverage.latestFor), so "Last 12
// months" for Del Monte ends at its own latest month, not Unilever's.
export function quickRanges(firstYear = FIRST_DATA_YEAR, latest) {
  if (!latest) return [];
  const last = ordinal(latest.month, latest.year);
  const ranges = Object.entries(RELATIVE_RANGES).map(([key, n]) => ({
    key, label: `Last ${n} months`, range: lastNRange(n, latest),
  }));
  for (let y = Number(latest.year); y >= firstYear; y -= 1) {
    if (ordinal('Dec', y) <= last) {
      ranges.push({ key: `y${y}`, label: String(y), range: { startMonth: 'Jan', startYear: String(y), endMonth: 'Dec', endYear: String(y) } });
    }
  }
  return ranges;
}

export const sameRange = (a, b) => Boolean(a && b)
  && a.startMonth === b.startMonth && String(a.startYear) === String(b.startYear)
  && a.endMonth === b.endMonth && String(a.endYear) === String(b.endYear);
