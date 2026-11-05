// The Sales vs Inventory Value card's rows (2026-11-03): each selected month
// beside the one month it is compared with, shared by the chart, its hover and
// its table, so the three can never disagree. Technical Adviser, 2 Oct 2026:
// "2025 vs 2024?", "no time story: no year-over-year, no period comparison",
// and a comparison must never silently change meaning.
//
// `shift` is how many months earlier the compared month is: 12 for "Same
// months last year", the range's own length for "Previous period" (so month N
// pairs with month N of the period before it), null for "No comparison".
// Nothing here makes up a figure: a month with no figure stays null (a gap,
// never a 0), and a recorded 0 stays 0. Tested by periodComparison.test.js.
import { MONTHS } from '../periodFilter.js';
import { monthsEarlier } from './timeline.js';

const monthLabel = (period) => `${MONTHS[Number(period.slice(5, 7)) - 1]} ${period.slice(0, 4)}`;

// "Mar 2025 – Feb 2026" as the date bar says it; `compact` closes the dash up
// for the legend ("Mar 2025–Feb 2026"). One month is just that month.
export const periodsLabel = (first, last, { compact = false } = {}) => {
  if (!first || !last) return '';
  if (first === last) return monthLabel(first);
  return `${monthLabel(first)}${compact ? '–' : ' – '}${monthLabel(last)}`;
};

// Months named as runs, so a long list stays short: "Jan 2022 – Dec 2022, Mar 2023".
export const monthRuns = (periods) => {
  const sorted = [...new Set(periods.filter(Boolean))].sort();
  const runs = [];
  sorted.forEach((period) => {
    const last = runs[runs.length - 1];
    if (last && monthsEarlier(period, 1) === last[1]) last[1] = period;
    else runs.push([period, period]);
  });
  return runs.map(([first, end]) => periodsLabel(first, end)).join(', ');
};

const LONG_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

// "September 2025", as the hover names a month.
export const longMonth = (period) => (
  period ? `${LONG_MONTHS[Number(period.slice(5, 7)) - 1]} ${period.slice(0, 4)}` : ''
);

// The months on show grouped by calendar year, for the band under the axis.
export function yearGroupsOf(periods) {
  const groups = [];
  periods.forEach((period) => {
    const year = period.slice(0, 4);
    const last = groups[groups.length - 1];
    if (last && last.year === year) last.months += 1;
    else groups.push({ year, months: 1 });
  });
  return groups;
}

// Whether sales and inventory went opposite ways against the comparison, for a
// suggestion to look at the month, nothing more. Each must have moved by at least
// `minPct` percent, so −0.2% doesn't read as sales having declined. The 1% is a
// display choice (Audrey's brief, 2026-11-03, asks to omit it where the data
// doesn't support it), not a figure from SSM. Null without both changes, so a
// synthetic month or a zero comparison never produces one.
export function oppositeMovement(change, minPct = 1) {
  const sales = change?.sales?.pct;
  const stock = change?.stock?.pct;
  if (sales == null || stock == null || Math.abs(sales) < minPct || Math.abs(stock) < minPct) return null;
  if (stock > 0 && sales < 0) return 'stockUp';
  if (stock < 0 && sales > 0) return 'stockDown';
  return null;
}

// The selected months cut into windows of `size`, from the first month, so the
// last window holds whatever is left. Every month is in exactly one window; the
// selection itself is never changed.
export function monthWindows(items, size) {
  const step = Math.max(1, Math.floor(size) || 1);
  const windows = [];
  for (let i = 0; i < items.length; i += step) windows.push(items.slice(i, i + step));
  return windows;
}

// A change strip's scale: the same reach up and down, so a rise and a fall of the
// same size look the same. It is set by the typical large change (most months
// fall inside it) rather than the very largest, because one month at +235% would
// otherwise flatten all the others. The full figure of a bar past the limit is
// printed beside it. If the largest change is close to the typical one, the
// limit simply covers it and nothing is cut. Null with nothing to show.
const STRIP_LIMITS = [5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 300, 500, 1000, 2000, 5000, 10000];
const niceLimit = (value) => STRIP_LIMITS.find((limit) => limit >= value) ?? Math.ceil(value / 10000) * 10000;
export function stripScale(values) {
  const sizes = values.filter((v) => v != null && Number.isFinite(v)).map(Math.abs).sort((a, b) => a - b);
  if (!sizes.length) return null;
  const largest = sizes[sizes.length - 1];
  const typical = sizes[Math.floor((sizes.length - 1) * 0.85)];
  const whole = niceLimit(largest);
  const limit = whole <= 3 * niceLimit(typical) ? whole : niceLimit(typical);
  return { limit, clipped: largest > limit };
}

// The change from the compared figure to the selected one: selected minus
// compared, and as a percent of the compared figure. Null without both
// figures; `pct` is null when the compared figure can't divide (0 or below).
export function periodChange(selected, compared) {
  if (selected == null || compared == null) return null;
  return {
    amount: selected - compared,
    pct: compared > 0 ? ((selected - compared) / compared) * 100 : null,
  };
}

const NO_FIGURES = {
  sales: null, salesest: null, stock: null, stockest: null, returns: null, retest: null, weeks: null, purch: null, bought: null, flagged: false,
};

// One month's figures. A month whose sales aren't SSM's own (`isReal` false: a
// synthetic or placeholder month) has them moved to the estimate, so `sales`
// is only ever SSM's figure; weeks of stock and "bought" are worked out on real
// months only. `recorded` picks purchase records or the estimate for the whole
// page, so the two are never mixed. A negative estimate is drawn at 0.
const monthFigures = (pt, { isReal, weeksOf, recorded }) => {
  if (!pt) return NO_FIGURES;
  const real = isReal(pt);
  const synthetic = pt.sales != null && !real;
  const purch = (recorded ? pt.received : pt.receivedEstimated) ?? null;
  return {
    sales: synthetic ? null : pt.sales ?? null,
    salesest: synthetic ? pt.sales : pt.salesEstimated ?? null,
    stock: pt.stockOnHand ?? null,
    stockest: pt.stockEstimated ?? null,
    returns: pt.returns ?? null,
    retest: pt.returnsEstimated ?? null,
    weeks: real ? weeksOf(pt.stockOnHand, pt.sales) : null,
    purch,
    bought: purch != null && real ? Math.max(0, purch) : null,
    flagged: Boolean(pt.stockFlagged ?? pt.stockUnusual),
  };
};

// One row per selected month, in order.
//   months         the selected range's months, every one kept on the axis
//   points         the selected range's rows
//   comparePoints  the comparison period's rows. A compared month can also be
//                  a selected one (24 months against a year earlier): one month
//                  has one set of figures, read from wherever it is on the page
//   floor          the first month any data exists: a compared month before it
//                  is `noEarlier`, which is not the same as a gap in the records
export function comparisonRows({
  months, points = [], comparePoints = [], shift = null, floor = null, isReal = () => true, weeksOf = () => null,
}) {
  const selected = new Map(points.map((pt) => [pt.period, pt]));
  const onPage = new Map([...comparePoints, ...points].map((pt) => [pt.period, pt]));
  const recorded = points.some((pt) => pt.received != null);
  const options = { isReal, weeksOf, recorded };

  const rows = months.map((period) => {
    const pt = selected.get(period) || { period };
    const own = monthFigures(pt, options);
    const row = {
      period,
      pt,
      ...own,
      net: own.bought != null && own.sales != null ? own.bought - own.sales : null,
      comparePeriod: null,
      cpt: null,
      noEarlier: false,
      salesC: null,
      salesestC: null,
      stockC: null,
      stockestC: null,
      returnsC: null,
      retestC: null,
      weeksC: null,
      purchC: null,
      boughtC: null,
      flaggedC: false,
      purchFlagC: false,
      change: {},
    };
    if (!shift) return row;

    const comparePeriod = monthsEarlier(period, shift);
    const cpt = onPage.get(comparePeriod) ?? null;
    const c = monthFigures(cpt, options);
    const previous = monthFigures(onPage.get(monthsEarlier(comparePeriod, 1)) ?? null, options);
    return {
      ...row,
      comparePeriod,
      cpt,
      noEarlier: Boolean(floor) && comparePeriod < floor,
      salesC: c.sales,
      salesestC: c.salesest,
      stockC: c.stock,
      stockestC: c.stockest,
      returnsC: c.returns,
      retestC: c.retest,
      weeksC: c.weeks,
      purchC: c.purch,
      boughtC: c.bought,
      flaggedC: c.flagged,
      // An estimate is the closing count − the opening count + sales, so it
      // rests on this month's count and the one before.
      purchFlagC: !recorded && c.bought != null && (c.flagged || previous.flagged),
      // Real figures only: `sales` and `salesC` never hold a synthetic month,
      // so a generated figure never produces a change.
      change: {
        sales: periodChange(own.sales, c.sales),
        stock: periodChange(own.stock, c.stock),
        returns: periodChange(own.returns, c.returns),
        weeks: periodChange(own.weeks, c.weeks),
        bought: periodChange(own.bought, c.bought),
      },
    };
  });

  // The selected "bought" outline, and each estimate line joining the real
  // value on each side of it, so a dotted stretch meets the solid one.
  rows.forEach((row, i) => {
    row.purchFlag = !recorded && row.bought != null && (row.flagged || Boolean(rows[i - 1]?.flagged));
    [['sales', 'salesest'], ['stock', 'stockest'], ['returns', 'retest']].forEach(([base, est]) => {
      const nextTo = rows[i - 1]?.[est] != null || rows[i + 1]?.[est] != null;
      row[`${est}Line`] = row[est] ?? (nextTo ? row[base] : null);
    });
  });
  return rows;
}

// The compared months with none of `keys` to show, for naming them above the
// plot. `keys` are the comparison fields the active view draws.
export const comparedMonthsMissing = (rows, keys) => rows
  .filter((row) => row.comparePeriod && keys.every((key) => row[key] == null))
  .map((row) => row.comparePeriod);
