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
import { LATEST_DATA_PERIOD, FIRST_DATA_YEAR } from './dataCoverage';

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
    startPeriod: periodToParam(out.startMonth, out.startYear),
    endPeriod: periodToParam(out.endMonth, out.endYear),
    label: rangeText(out),
    beforeData: ordinal(out.startMonth, out.startYear) < ordinal(floor.month, floor.year),
  };
}

// The quick ranges. Each is at least six months, the picker's own minimum,
// and inside the data (Jan 2023 to the latest month). A whole calendar year
// is offered only once all twelve of its months are in the data.
export function quickRanges() {
  const latest = ordinal(LATEST_DATA_PERIOD.month, LATEST_DATA_PERIOD.year);
  const lastN = (n) => {
    const start = fromOrdinal(latest - n + 1);
    return { startMonth: start.month, startYear: start.year, endMonth: LATEST_DATA_PERIOD.month, endYear: LATEST_DATA_PERIOD.year };
  };
  const ranges = [
    { key: 'last6', label: 'Last 6 months', range: lastN(6) },
    { key: 'last12', label: 'Last 12 months', range: lastN(12) },
    { key: 'last24', label: 'Last 24 months', range: lastN(24) },
  ];
  for (let y = Number(LATEST_DATA_PERIOD.year); y >= FIRST_DATA_YEAR; y -= 1) {
    if (ordinal('Dec', y) <= latest) {
      ranges.push({ key: `y${y}`, label: String(y), range: { startMonth: 'Jan', startYear: String(y), endMonth: 'Dec', endYear: String(y) } });
    }
  }
  return ranges;
}

export const sameRange = (a, b) => Boolean(a && b)
  && a.startMonth === b.startMonth && String(a.startYear) === String(b.startYear)
  && a.endMonth === b.endMonth && String(a.endYear) === String(b.endYear);
