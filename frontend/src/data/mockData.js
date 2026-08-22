// src/data/mockData.js
//
// Single source of mock data for the Inventory Pulse main dashboard. Every
// figure that appears on more than one card/panel reads from here, so the
// numbers can't drift apart across the page the way "Products to reorder"
// and "Total reorder value" used to. Swapping to a real backend later is a
// matter of replacing the values below with a fetch in a wrapper module
// (see src/api/dashboard.js's existing pattern), not touching Dashboard.jsx's
// rendering logic.
//
// PLACEHOLDER — awaiting allocation schedule from principals:
//   allocationOffered, cashFreed, allocationVariance[], takeLessRecs[], askMoreRecs[]
// PLACEHOLDER — awaiting historical accept-vs-offer records:
//   benchmark

// Real reason codes from SSM's return records — replaces the earlier
// invented Expiry / Transport Damage / Storage Issue / Supplier Defect
// labels everywhere bad-order reasons are shown.
export const BAD_ORDER_REASONS = [
  'Packaging Defect (Torn/Deformed/Broken)',
  'Order cancelled by customer',
  'Overlanded/Shortlanded',
  'Good – Full Return',
  'Stock not available',
  'Stock Recall',
];

// One LP solver run per cycle covers every principal at once — the header
// status line is a fact about the run, not about whichever principal is
// currently toggled, so it doesn't vary with the filter. solvedAt is NOT
// listed here — a fixed date would drift out of sync with whatever date
// range the picker is set to (see solverTimestampFor() below), so it's
// derived at render time from the selected range instead of hardcoded.
export const SOLVER_STATUS = {
  cycle: 34,
  status: 'optimal',
  classACount: 45,
};

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// The solve always runs a few days after the period it covers closes, so
// the header's "solved [date]" can never land before the end of whatever
// range the date picker shows — deterministic (fixed 3-day offset), not a
// random or hardcoded date, so it moves whenever the selected range does.
// Returns the pieces (not a single formatted string) because the header
// states the range's own month/year separately from the solve day/month
// ("Cycle 34 · Sep 2026 · solved 3 Sep, 09:12") — the solve can even fall
// in the month after the range if the +3 day offset crosses a boundary,
// which is correct, not a bug.
export function solverTimestampFor(endMonth, endYear) {
  const monthIdx = MONTH_NAMES.indexOf(endMonth);
  const year = parseInt(endYear, 10) || 2026;
  const lastDayOfPeriod = new Date(Date.UTC(year, (monthIdx < 0 ? 7 : monthIdx) + 1, 0));
  const solveDate = new Date(lastDayOfPeriod);
  solveDate.setUTCDate(solveDate.getUTCDate() + 3);
  return {
    day: solveDate.getUTCDate(),
    month: MONTH_NAMES[solveDate.getUTCMonth()],
    year: solveDate.getUTCFullYear(),
    time: '09:12',
  };
}

// variance = allocationCases - forecastCases: negative = allocation is
// below forecast (shortfall, stockout risk); positive = allocation exceeds
// forecast (excess, trapped capital). Computed here, once, so the chart,
// the tooltip, and both recommendation panels can never disagree about a
// SKU's numbers.
//
// recommendedAccept is capped at the offer — SSM cannot accept more than
// a principal offers (the LP's own supplier allocation ceiling, Q ≤ A), so
// forecastCases alone was never a valid "recommended acceptance" whenever
// it exceeded allocationCases. Where the offer falls short of demand,
// shortfallCases is how many more cases the gap represents, reported
// separately (as a request back to the principal) rather than folded into
// an impossible acceptance number.
function withVariance(row) {
  const varianceCases = row.allocationCases - row.forecastCases;
  return {
    ...row,
    varianceCases,
    variancePesos: Math.round(varianceCases * row.unitPricePesos),
    recommendedAccept: Math.min(row.allocationCases, row.forecastCases),
    shortfallCases: Math.max(0, row.forecastCases - row.allocationCases),
  };
}

// SKU names here are what render in the chart's y-axis and the "Accept
// this cycle" panel — kept short (no wrapping in the chart's label column)
// and, for Del Monte, plain-language rather than the "CAT-" codes used
// internally elsewhere (BadOrders.jsx, ABCClassification.jsx, etc. — those
// are separate mock datasets, unaffected by names chosen here).
const UNILEVER_VARIANCE = [
  { sku: 'Surf powder 1kg', allocationCases: 120, forecastCases: 180, unitPricePesos: 9000 },
  { sku: 'Closeup 190g', allocationCases: 220, forecastCases: 40, unitPricePesos: 2900 },
  { sku: 'Dove 340ml', allocationCases: 160, forecastCases: 210, unitPricePesos: 10000 },
  { sku: 'Sunsilk 180ml', allocationCases: 140, forecastCases: 85, unitPricePesos: 3000 },
  { sku: 'Rexona 40ml', allocationCases: 190, forecastCases: 140, unitPricePesos: 2000 },
  { sku: 'Lux Bar Soap 135g', allocationCases: 90, forecastCases: 130, unitPricePesos: 1900 },
  { sku: 'Breeze Detergent Powder 500g', allocationCases: 150, forecastCases: 120, unitPricePesos: 1600 },
].map(withVariance);

const DELMONTE_VARIANCE = [
  { sku: 'Canned fruits (category)', allocationCases: 210, forecastCases: 150, unitPricePesos: 1600 },
  { sku: 'Juices (category)', allocationCases: 300, forecastCases: 360, unitPricePesos: 1500 },
  { sku: 'Corned beef (category)', allocationCases: 140, forecastCases: 95, unitPricePesos: 1950 },
  { sku: 'Sauces & vegetables (category)', allocationCases: 260, forecastCases: 300, unitPricePesos: 1700 },
  { sku: 'Pasta & sauces (category)', allocationCases: 180, forecastCases: 220, unitPricePesos: 1400 },
].map(withVariance);

// Chart display order: signed peso variance ascending — most-negative
// shortfall first, most-positive excess last. Rendered top-to-bottom in
// this order, that reads as one smooth arrow (reds tapering toward zero,
// then ambers growing away from it) instead of zigzagging across the axis
// the way sorting by absolute impact alone would.
function orderForChart(rows) {
  return [...rows].sort((a, b) => a.variancePesos - b.variancePesos);
}

function countNegative(rows) {
  return rows.filter((r) => r.variancePesos < 0).length;
}

// The chart's job is scale, not detail — the top 5 SKUs by absolute peso
// impact (mixed sign), not a fixed split per side. Exact figures for the
// rest live in the "Accept less"/"Request more" cards below it instead of
// being duplicated as a bar-end label here. The Stockout risk KPI card
// still counts every negative row via countNegative() on the FULL array,
// independent of this capped chart subset.
function selectVarianceForChart(rows, n = 5) {
  const top = [...rows]
    .sort((a, b) => Math.abs(b.variancePesos) - Math.abs(a.variancePesos))
    .slice(0, n);
  return orderForChart(top);
}

// "Take less of these" — the largest excesses, each with the (capped,
// never-impossible) accept quantity and how much cash it frees.
function takeLessRecsFrom(rows, n = 4) {
  return [...rows]
    .filter((r) => r.variancePesos > 0)
    .sort((a, b) => b.variancePesos - a.variancePesos)
    .slice(0, n)
    .map((r) => ({
      sku: r.sku,
      accept: r.recommendedAccept,
      offered: r.allocationCases,
      freesPesos: r.variancePesos,
    }));
}

// "Ask for more of these" — the largest shortfalls, each with the offer,
// the actual demand, and the gap in cases (a request back to the
// principal, not something SSM can resolve by accepting more of the offer
// on the table — there is no more to accept). impactPesos is the card's
// secondary (small, grey) figure — the instruction itself is primary.
function askMoreRecsFrom(rows, n = 4) {
  return [...rows]
    .filter((r) => r.variancePesos < 0)
    .sort((a, b) => a.variancePesos - b.variancePesos)
    .slice(0, n)
    .map((r) => ({
      sku: r.sku,
      offered: r.allocationCases,
      need: r.forecastCases,
      shortCases: r.shortfallCases,
      impactPesos: Math.abs(r.variancePesos),
    }));
}

const ALL_VARIANCE = [...UNILEVER_VARIANCE, ...DELMONTE_VARIANCE];

const UNILEVER = {
  kpis: {
    allocationOffered: { valueM: 5.8, cases: 870, classACount: 42 },
    cashFreed: { valueM: 1.4, offeredM: 4.3, pctLess: 24 },
    stockoutRisk: { count: countNegative(UNILEVER_VARIANCE) },
    forecastHealth: { passed: 38, total: 42, fallback: 4 },
  },
  allocationVariance: selectVarianceForChart(UNILEVER_VARIANCE),
  funnel: {
    activeSKUs: 318,
    classA: 42,
    classARevenuePct: 68,
    forecastPassed: 38,
    optimised: 42,
    fallback: 4,
  },
  takeLessRecs: takeLessRecsFrom(UNILEVER_VARIANCE),
  askMoreRecs: askMoreRecsFrom(UNILEVER_VARIANCE),
  benchmark: {
    holdingCost: { modelM: 0.83, currentM: 1.15 },
    spoilage: { modelK: 184, currentK: 264 },
    stockoutDays: { model: 8, current: 13 },
  },
};

const DELMONTE = {
  kpis: {
    allocationOffered: { valueM: 2.6, cases: 370, classACount: 3 },
    cashFreed: { valueM: 0.7, offeredM: 2.0, pctLess: 21 },
    stockoutRisk: { count: countNegative(DELMONTE_VARIANCE) },
    forecastHealth: { passed: 2, total: 3, fallback: 1 },
  },
  allocationVariance: selectVarianceForChart(DELMONTE_VARIANCE),
  funnel: {
    activeSKUs: 12,
    classA: 3,
    classARevenuePct: 71,
    forecastPassed: 2,
    optimised: 3,
    fallback: 1,
  },
  takeLessRecs: takeLessRecsFrom(DELMONTE_VARIANCE),
  askMoreRecs: askMoreRecsFrom(DELMONTE_VARIANCE),
  benchmark: {
    holdingCost: { modelM: 0.47, currentM: 0.65 },
    spoilage: { modelK: 103, currentK: 148 },
    stockoutDays: { model: 11, current: 16 },
  },
};

const ALL = {
  kpis: {
    allocationOffered: { valueM: 8.4, cases: 1240, classACount: 45 },
    cashFreed: { valueM: 2.1, offeredM: 6.3, pctLess: 25 },
    stockoutRisk: { count: countNegative(ALL_VARIANCE) },
    forecastHealth: { passed: 41, total: 45, fallback: 4 },
  },
  allocationVariance: selectVarianceForChart(ALL_VARIANCE),
  funnel: {
    activeSKUs: 330,
    classA: 45,
    classARevenuePct: 80,
    forecastPassed: 41,
    optimised: 45,
    fallback: 4,
  },
  takeLessRecs: takeLessRecsFrom(ALL_VARIANCE),
  askMoreRecs: askMoreRecsFrom(ALL_VARIANCE),
  benchmark: {
    holdingCost: { modelM: 1.3, currentM: 1.8 },
    spoilage: { modelK: 287, currentK: 412 },
    stockoutDays: { model: 9, current: 14 },
  },
};

// One typed object, keyed by the same principal values the rest of the app
// already uses ('all' | 'unilever' | 'delmonte') — DashboardLayout's
// existing principal state, no second filter mechanism.
export const MOCK_DASHBOARD = { all: ALL, unilever: UNILEVER, delmonte: DELMONTE };

export function getMockDashboard(principal) {
  return MOCK_DASHBOARD[principal] ?? MOCK_DASHBOARD.all;
}
