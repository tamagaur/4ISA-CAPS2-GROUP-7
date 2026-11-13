// What "now" is for the date filter: the latest month with REAL sales, per
// principal. Since 2026-10-20 it comes from the API — GET /data-mode's
// `coverage` (backend/marts.real_coverage), asked by the layout on every page
// — so a new month of data moves every page's default range by itself.
//
// There is NO fallback month (2026-11-13). Until then a constant (Feb 2026 /
// Dec 2025) was shown on the first render and whenever that call failed: the
// same defect as the old June 2026 hardcode, a month that stops being true the
// day a new month loads. The layout (components/DashboardLayout.jsx) now waits
// for the answer, showing a loading state, and on a failure says so with a
// retry, instead of rendering any page on a guessed month.

// First year of real data — both principals start in 2023-01.
export const FIRST_DATA_YEAR = 2023;

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
 * The latest month with real sales for `principal` ('all', 'unilever',
 * 'delmonte'), as { month, year }, from `coverage` (GET /data-mode's); null
 * when there is no answer to read. 'all' is the later of the two principals,
 * so a view that includes Unilever never rewinds to Del Monte's shorter data;
 * Del Monte alone ends at its own latest month, so its default range has no
 * empty months at the end. A principal the answer does not list takes the
 * answer's overall month: still a measured month, never a constant.
 */
export function latestFor(coverage, principal = 'all') {
  const overall = parsePeriod(coverage?.latest_data_period);
  const byPrincipal = coverage?.latest_data_period_by_principal || {};
  if (principal === 'unilever' || principal === 'delmonte') {
    return parsePeriod(byPrincipal[principal]) || overall;
  }
  return overall;
}

/**
 * The live latest period, when it is NEWER than the one the page's filters
 * end on (`applied`, the layout's own latest): a month loaded after the layout
 * read GET /data-mode, before it read it again. Null otherwise (and when
 * either is missing), so a caller renders the notice on a truthy value only.
 */
export function staleCoverageNotice(latestDataPeriod, applied) {
  const live = parsePeriod(latestDataPeriod);
  if (!live || !applied) return null;
  if (periodToOrdinal(live) <= periodToOrdinal(applied)) return null;
  return {
    live: `${live.month} ${live.year}`,
    pinned: `${applied.month} ${applied.year}`,
  };
}
