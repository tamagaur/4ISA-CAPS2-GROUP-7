// The dashboard's two forecast cards (2026-10-21, mockup pass): the points
// the demand chart marks and its "Key takeaways" list, and the status a
// month of the accuracy chart gets. Pure functions of the series the cards
// already plot, so the labels, the takeaways and the plot can't disagree,
// and nothing here computes a figure the API did not send. Tested by
// forecastHighlights.test.js (`npm test`).

import { approxCount } from './formatNumber.js';

// The highest and lowest month of actual demand, and the next forecast.
// `series` is PortfolioForecastWidget's: [{ period, actual, forecast,
// confidenceLower, confidenceUpper }], actual only on history months,
// forecast only on projected ones.
//   peak / low  { period, value }: null unless at least two months have
//               actual demand and the two differ (one month, or a flat line,
//               has no high or low to name)
//   next        { period, value, low, high }: the first month with a
//               forecast and no actual; low/high null without a range
export function demandHighlights(series = []) {
  const actual = series.filter((p) => p && p.actual != null && Number.isFinite(p.actual));
  let peak = null;
  let low = null;
  if (actual.length >= 2) {
    peak = actual.reduce((best, p) => (p.actual > best.actual ? p : best));
    low = actual.reduce((best, p) => (p.actual < best.actual ? p : best));
    if (peak.actual === low.actual) {
      peak = null;
      low = null;
    }
  }
  const nextPoint = series.find((p) => p && p.actual == null && p.forecast != null && Number.isFinite(p.forecast));
  const hasRange = nextPoint && nextPoint.confidenceLower != null && nextPoint.confidenceUpper != null;
  return {
    peak: peak ? { period: peak.period, value: peak.actual } : null,
    low: low ? { period: low.period, value: low.actual } : null,
    next: nextPoint
      ? {
        period: nextPoint.period,
        value: nextPoint.forecast,
        low: hasRange ? nextPoint.confidenceLower : null,
        high: hasRange ? nextPoint.confidenceUpper : null,
      }
      : null,
  };
}

// Which of the chart's labels to draw: in priority order, each kept only if
// it clears every label already kept, measured in pixels from the month
// slot's width (`slotPx`) and each label's own width (`width`). A label that
// would collide is left to the tooltip. `candidates`: [{ idx, width, ... }].
export function labelsThatFit(candidates, slotPx, gap = 8) {
  const kept = [];
  for (const c of candidates) {
    if (!c) continue;
    const clear = kept.every((k) => Math.abs(c.idx - k.idx) * slotPx >= (c.width + k.width) / 2 + gap);
    if (clear) kept.push(c);
  }
  return kept;
}

// A month of the accuracy chart: forecast minus actual, so above zero the
// forecast was too high and below zero too low. Exactly zero is a match;
// nothing here calls a month "accurate" or "within range", since no
// threshold for that exists on record.
export function missStatus(variance) {
  if (variance == null || !Number.isFinite(variance)) return null;
  if (variance > 0) return 'high';
  if (variance < 0) return 'low';
  return 'exact';
}

export const MISS_STATUS_LABEL = {
  high: 'Forecast too high',
  low: 'Forecast too low',
  exact: 'Exact match',
};

// "Why it may have changed" on the SKU Forecast page (2026-10-24): short
// observations beside the forecast, built only from what GET /forecast/{sku}
// and the page's accuracy rows already send. Each line states what the
// figures show ("Sales rose over the last three months"), never a cause of
// demand. A line whose data is missing is left out, never estimated.
//
//   actuals         GET /forecast's actuals: [{ period 'YYYY-MM', quantity,
//                   reason }] (codes: backend/series_gaps.py)
//   forecastPeriod  the month forecast, 'YYYY-MM'
//   basisPeriod     the last actual month the forecast is compared with
//   principal       'unilever' | 'delmonte'
//   calendar        { factor, years } from model_params (forecastModel.js
//                   withCalendar), or null when the value is not adjusted
//   stockLimited    'YYYY-MM' months flagged possibly_stock_limited
//
// Which months count: a point with a quantity and no reason, or a Unilever
// month with reason 'no_sale' (a real zero sale). A Del Monte gap, a blank
// capture, a month outside the product's life or a generated month is never
// read as a value, and a month the API did not send is never assumed zero.
const MONTH_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December'];

const monthIndex = (period) => {
  const m = /^(\d{4})-(\d{2})/.exec(String(period || ''));
  return m ? Number(m[1]) * 12 + Number(m[2]) - 1 : null;
};
const periodOf = (index) => `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, '0')}`;
const monthText = (period) => {
  const i = monthIndex(period);
  return i == null ? String(period) : `${MONTH_SHORT[i % 12]} ${Math.floor(i / 12)}`;
};
// A whole number with a true minus sign: a month's net figure is below zero
// when returns outweighed sales (2026-10-24: "about -12 pcs" was read as a
// sale of minus twelve). Rounded the way the headline rounds (2026-10-26:
// formatNumber.js approxCount, so "about 65,576 pcs" beside "about 133,000
// pcs" reads as 66,000); the exact figure is the part's `value`.
const num = (v) => {
  const n = approxCount(v);
  return n < 0 ? `−${Math.abs(n).toLocaleString('en-US')}` : n.toLocaleString('en-US');
};
// A line is built from parts (2026-10-26): text, and { value, text } for a
// figure, so the page can put the exact figure in a hover (ExactValue) and
// `text` stays the plain sentence. `say` is a template tag: a figure is
// Q(v), a list of figures an array of parts.
const Q = (v) => ({ value: v, text: num(v) });
const say = (strings, ...vals) => {
  const parts = [];
  strings.forEach((s, i) => {
    if (s) parts.push(s);
    if (i < vals.length) [vals[i]].flat(Infinity).forEach((v) => v != null && v !== '' && parts.push(v));
  });
  return parts;
};
const lineOf = (key, parts) => ({
  key,
  parts,
  text: parts.map((p) => (typeof p === 'string' ? p : p.text)).join(''),
});
const pcs = (v) => [Q(v), ' pcs'];
const qtyText = (v) => (v === 0 ? 'nothing' : ['about ', pcs(v)]);
// Items each a string or a list of parts.
const joinAnd = (items) => (items.length <= 1 ? items
  : [...items.slice(0, -1).flatMap((it, i) => (i === 0 ? [it] : [', ', it])), ' and ', items[items.length - 1]]);

export function usableQuantity(point, principal) {
  if (!point || point.quantity == null || !Number.isFinite(point.quantity)) return null;
  if (point.reason == null) return point.quantity;
  if (point.reason === 'no_sale' && principal === 'unilever') return point.quantity;
  return null;
}

//   longTermTrend   GET /segment's traits.trend ('up' | 'down' | 'none'),
//                   the Mann-Kendall direction since the first sale that the
//                   Sales pattern panel shows, or null when not analyzed
//   changePct       the headline's change of the forecast against the
//                   basis month, in %, or null
export function forecastWhy({
  actuals = [], forecastPeriod = null, basisPeriod = null, principal = null, calendar = null, stockLimited = [],
  longTermTrend = null, changePct = null,
} = {}) {
  const byPeriod = new Map((actuals || []).filter(Boolean).map((p) => [String(p.period).slice(0, 7), p]));
  const valueAt = (index) => usableQuantity(byPeriod.get(periodOf(index)), principal);
  const lines = [];

  // The last three actual months, ending at the month the forecast is compared with.
  const basis = monthIndex(basisPeriod);
  if (basis != null) {
    const idx = [basis - 2, basis - 1, basis];
    const vals = idx.map(valueAt);
    if (vals.every((v) => v != null)) {
      const [a, b, c] = vals;
      const span = `${monthText(periodOf(idx[0]))} – ${monthText(periodOf(idx[2]))}`;
      const list = [joinAnd(vals.map(Q)), ' pcs'];
      const negatives = vals.filter((v) => v < 0).length;
      let parts;
      // Net sales below zero (returns outweighed sales) are said as such,
      // never as a rise or fall in sales.
      if (negatives > 0) {
        parts = say`Net sales over the last three months were about ${list} (${span}): returns outweighed sales in ${
          negatives === 1 ? '1 of them' : `${negatives} of them`}.`;
      } else if (a < b && b < c) parts = say`Sales rose in each of the last three months: about ${list} (${span}).`;
      else if (a > b && b > c) parts = say`Sales fell in each of the last three months: about ${list} (${span}).`;
      else if (a === b && b === c) parts = say`Sales were the same in each of the last three months: ${qtyText(a)} a month (${span}).`;
      else parts = say`Sales went up and down over the last three months: about ${list} (${span}).`;
      lines.push(lineOf('last_three', parts));
    }
    const flagged = idx.map(periodOf).filter((p) => (stockLimited || []).includes(p));
    if (flagged.length) {
      lines.push(lineOf('stock_limited', say`${joinAnd(flagged.map(monthText))} ${flagged.length === 1 ? 'is' : 'are'} flagged: stock may have run out, so real demand may have been higher than sales.`));
    }
  }

  // The same month a year earlier, and the month before it, if on record.
  const target = monthIndex(forecastPeriod);
  if (target != null) {
    const sameMonth = valueAt(target - 12);
    const before = valueAt(target - 13);
    const sm = monthText(periodOf(target - 12));
    const bm = monthText(periodOf(target - 13));
    if (sameMonth != null && before != null && (sameMonth < 0 || before < 0)) {
      lines.push(lineOf('last_year',
        say`A year earlier, net sales were about ${pcs(before)} in ${bm} and ${pcs(sameMonth)} in ${sm} (returns outweighed sales).`));
    } else if (sameMonth != null && before != null) {
      const parts = sameMonth > before
        ? say`A year earlier, sales rose from ${qtyText(before)} in ${bm} to ${qtyText(sameMonth)} in ${sm}.`
        : sameMonth < before
          ? say`A year earlier, sales fell from ${qtyText(before)} in ${bm} to ${qtyText(sameMonth)} in ${sm}.`
          : say`A year earlier, sales were ${qtyText(sameMonth)} in both ${bm} and ${sm}.`;
      lines.push(lineOf('last_year', parts));
    } else if (sameMonth != null) {
      lines.push(lineOf('last_year', say`In ${sm}, the same month last year, ${sameMonth === 0 ? 'it sold nothing'
        : sameMonth < 0 ? say`returns outweighed sales (net about ${pcs(sameMonth)})` : say`it sold about ${pcs(sameMonth)}`}.`));
    }
  }

  // The calendar adjustment (analytics/forecasting/calendar.py): above 1
  // when, across every real Unilever product (calendar.py company_totals),
  // the month has on average sold more than the 3
  // months before it in earlier years; 1 with no earlier year on record.
  const factor = calendar?.factor != null ? Number(calendar.factor) : null;
  if (factor != null && Number.isFinite(factor) && target != null) {
    const month = MONTH_LONG[target % 12];
    const years = calendar.years;
    const yearsText = years != null ? ` (${years} earlier ${years === 1 ? 'year' : 'years'})` : '';
    const pct = Math.abs((factor - 1) * 100).toFixed(1);
    let text = null;
    if (factor > 1) {
      text = `Across all Unilever products, ${month} has on average sold more than the 3 months before it${yearsText}, `
        + `so the forecast is raised by about ${pct}%.`;
    } else if (factor < 1) {
      text = `Across all Unilever products, ${month} has on average sold less than the 3 months before it${yearsText}, `
        + `so the forecast is lowered by about ${pct}%.`;
    } else if (years === 0) {
      text = `No calendar adjustment: there is no earlier ${month} on record to compare with.`;
    } else if (years != null) {
      text = `Across all Unilever products, ${month} has sold about the same as the 3 months before it${yearsText}, `
        + 'so the calendar adjustment leaves the forecast unchanged.';
    }
    if (text) lines.push(lineOf('calendar', [text]));
  }

  // The bridge (2026-10-26): the headline says next month is up while the
  // Sales pattern panel says "Going down" (or the reverse). One line ties
  // them, pointing only at the lines above; shown only when both the
  // direction and the change are known, they disagree, and there is a line
  // above to point at. The same ±0.5% the headline's "about the same" uses.
  const up = changePct != null && Number.isFinite(changePct) && changePct > 0.5;
  const down = changePct != null && Number.isFinite(changePct) && changePct < -0.5;
  const LISTED = { last_three: 'the last three months', last_year: 'the same month last year', calendar: 'the calendar adjustment' };
  const listed = lines.filter((l) => LISTED[l.key]).map((l) => LISTED[l.key]);
  if (basis != null && listed.length && ((up && longTermTrend === 'down') || (down && longTermTrend === 'up'))) {
    const longRun = longTermTrend === 'down' ? 'going down' : 'going up';
    lines.push(lineOf('trend_bridge', [
      `Over the longer run (since its first sale), sales of this product have been ${longRun}. `
        + `Next month's ${up ? 'higher' : 'lower'} figure is a comparison with ${monthText(periodOf(basis))} only; `
        + `what changed around it is ${joinAnd(listed).join('')}, above.`,
    ]));
  }

  // Fixed order: recent sales, the stock flag on them, last year, the
  // calendar, then the bridge to the longer-run direction.
  const order = ['last_three', 'stock_limited', 'last_year', 'calendar', 'trend_bridge'];
  return lines.sort((x, y) => order.indexOf(x.key) - order.indexOf(y.key));
}
