// The latest month with real sales data — the date picker's ceiling and the
// "today" every page's default range ends on (DateFilter.jsx,
// DashboardLayout.jsx). Unilever's demand runs 2023-01 to 2026-02 and Del
// Monte's sell-out 2023-01 to 2025-12, so the later of the two bounds the
// picker.
//
// Hard-coded, so it needs a manual edit when a new month of data loads —
// this is the ONE place to make it. GET /dashboard also returns the value
// as `latest_data_period` (task E3); reading it from there is the follow-up
// that retires this constant.
export const LATEST_DATA_PERIOD = { month: 'Feb', year: '2026' };

// First year of real data — both principals start in 2023-01.
export const FIRST_DATA_YEAR = 2023;

// ── Staleness detection ─────────────────────────────────────────────────
// The constant above is the date picker's ceiling AND the app's pinned
// "today", and it is edited by hand. If a new month of data lands and
// nobody edits it, every page silently keeps ending at the old month —
// the figures stay real, but they are no longer the latest, and nothing
// on screen says so. That is the failure this guards.
//
// GET /dashboard returns the true value as `latest_data_period`. Pages
// hand it here; when it is AHEAD of the constant the layout shows a
// notice naming the file to edit. Deliberately detection rather than an
// automatic override: the picker builds its year and month option lists
// from the constant at module load, so silently moving the ceiling past
// what the dropdown offers would let "today" select a month the user
// cannot pick. One honest warning beats a half-applied value.
const MONTH_ORDER = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function periodToOrdinal({ month, year }) {
  return Number(year) * 12 + MONTH_ORDER.indexOf(month);
}

/** 'YYYY-MM' -> {month:'Feb', year:'2026'}; null for anything unparsable. */
export function parsePeriod(period) {
  if (!period) return null;
  const [year, num] = String(period).split('-');
  const month = MONTH_ORDER[Number(num) - 1];
  return month && year ? { month, year } : null;
}

/**
 * The live latest period, when it is NEWER than the hardcoded constant.
 * Returns null when the constant is current (the normal case) — so a
 * caller can render the notice on a truthy value and nothing otherwise.
 */
export function staleCoverageNotice(latestDataPeriod) {
  const live = parsePeriod(latestDataPeriod);
  if (!live) return null;
  if (periodToOrdinal(live) <= periodToOrdinal(LATEST_DATA_PERIOD)) return null;
  return {
    live: `${live.month} ${live.year}`,
    pinned: `${LATEST_DATA_PERIOD.month} ${LATEST_DATA_PERIOD.year}`,
  };
}
