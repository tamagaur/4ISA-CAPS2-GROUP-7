// The ABC page's month picker (audit FE-6 + NEW-FE-3, 2026-10-21).
//
// The person's pick is kept apart from what the page shows. Until 2026-10-21 a
// response that came from an earlier run than the month asked for (Del Monte's
// latest run is 2025-12, Unilever's 2026-02) was written into the selection
// itself. That counted as a pick, so "Clear" appeared for nothing; it changed
// the month asked for, so the page loaded twice; and after Del Monte the
// selection sat on 2025-12, which Unilever also has, so Unilever never came back
// to 2026-02. Now nothing but the person changes the pick.

// The month GET /abc is asked for: the person's pick, else the dashboard
// range's last month, so with no pick the page follows the range for every
// principal. 'YYYY-MM' or null.
export function requestedAbcPeriod(picked, rangeEnd) {
  return picked || rangeEnd || null;
}

// The month the picker shows: the run the page is displaying, once the
// answer on screen is the one for the current request (GET /abc answers
// with the nearest run at or before the month asked for); until then, the
// month asked for.
export function shownAbcPeriod(requested, resolved, answerIsCurrent) {
  return answerIsCurrent && resolved ? resolved : requested;
}

// The latest run for a scope, from GET /abc's tier_a_periods ({ 'Unilever': '2026-02', ... }).
// `label` is the principal's display name, or null for all principals (the latest of any).
export function latestRunFor(tierAPeriods, label) {
  const entries = Object.entries(tierAPeriods || {});
  const periods = (label ? entries.filter(([k]) => k === label) : entries).map(([, p]) => p).filter(Boolean);
  return periods.length ? periods.sort().at(-1) : null;
}

// Del Monte regrouped its product categories in Jan 2025: about 80 old
// sub-category paths became five categories, with no mapping between them
// (DEC-03). A Del Monte row last ranked before this month is one of the old
// paths. GET /abc already leaves those out of the ABC page (its
// retired_series_count, audit BE-3); GET /sku still lists them, so SKU
// Management uses this test to keep them out of its class counts, and the
// two pages give the same Del Monte Class A (2026-10-22). The backend's own
// rule reads each path's first and last real month; a last ABC run before
// Jan 2025 picks out the same 80 rows today.
export const DEL_MONTE_REGROUP_PERIOD = '2025-01';
export function isPreRegroupDelMonte(principal, tierPeriod) {
  return principal === 'delmonte' && !!tierPeriod && tierPeriod < DEL_MONTE_REGROUP_PERIOD;
}
