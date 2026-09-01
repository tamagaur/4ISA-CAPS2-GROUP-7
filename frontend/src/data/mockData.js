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
