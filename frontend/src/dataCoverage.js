// What "now" is for the date filter: the latest month with REAL sales, per
// principal. Since 2026-10-20 it comes from the API — GET /data-mode's
// `coverage` (backend/marts.real_coverage), asked by the layout on every page
// — so a new month of data moves every page's default range by itself.
//
// The values below are only the fallback until that answer arrives (and if it
// fails): the coverage as of 2026-10-20. Unilever's demand runs 2023-01 to
// 2026-02 and Del Monte's sell-out 2023-01 to 2025-12; the later of the two
// bounds the date picker.
export const LATEST_DATA_PERIOD = { month: 'Feb', year: '2026' };
export const LATEST_BY_PRINCIPAL = {
  unilever: { month: 'Feb', year: '2026' },
  delmonte: { month: 'Dec', year: '2025' },
};

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
 * 'delmonte'), as { month, year }: from `coverage` (GET /data-mode's) when
 * it has the answer, else the fallback above. 'all' is the later of the two
 * principals, so a view that includes Unilever never rewinds to Del Monte's
 * shorter data; Del Monte alone ends at its own latest month, so its default
 * range has no empty months at the end.
 */
export function latestFor(coverage, principal = 'all') {
  const byPrincipal = coverage?.latest_data_period_by_principal || {};
  if (principal === 'unilever' || principal === 'delmonte') {
    return parsePeriod(byPrincipal[principal]) || LATEST_BY_PRINCIPAL[principal];
  }
  return parsePeriod(coverage?.latest_data_period) || LATEST_DATA_PERIOD;
}

/**
 * The live latest period, when it is NEWER than the one the page's filters
 * end on (`applied`, the layout's own latest) — which can only happen when
 * GET /data-mode could not be read and the layout fell back to the constant.
 * Null otherwise, so a caller renders the notice on a truthy value only.
 */
export function staleCoverageNotice(latestDataPeriod, applied = LATEST_DATA_PERIOD) {
  const live = parsePeriod(latestDataPeriod);
  if (!live || !applied) return null;
  if (periodToOrdinal(live) <= periodToOrdinal(applied)) return null;
  return {
    live: `${live.month} ${live.year}`,
    pinned: `${applied.month} ${applied.year}`,
  };
}
