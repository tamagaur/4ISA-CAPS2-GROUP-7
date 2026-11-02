// The forecast-error card's two miss totals (RangeCards.jsx, "Where the misses went"). A total the backend
// did not send (null/undefined) is ABSENT, not ₱0: it prints NOT_COLLECTED and has no share of sales and no
// bar (audit A-FE-10, 2026-10-24; before this, `surplus_pesos ?? 0` printed a missing total as "₱0"). A real
// zero is still ₱0, 0% of sales.
import { isMissing, NOT_COLLECTED } from './formatters.js';

// The total as a share of what sold over the range, or null when either side is missing or nothing sold.
export function missShare(value, sold) {
  if (isMissing(value) || isMissing(sold) || !(sold > 0)) return null;
  return value / sold;
}

// A count for a table cell: thousands-separated, NOT_COLLECTED when absent (never "0").
export function formatCount(value) {
  return isMissing(value) ? NOT_COLLECTED : Number(value).toLocaleString();
}
