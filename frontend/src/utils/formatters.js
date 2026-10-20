// Split out of Charts.jsx (2026-08): a component file that also exports a
// plain function breaks Vite's React Fast Refresh — every edit to Charts.jsx
// forced a full HMR "invalidate" (visible in the dev server log) instead of
// a clean hot-swap, which meant an already-open browser tab could keep
// showing stale state after a change until a hard refresh. Kept here so
// Charts.jsx goes back to exporting components only.
//
// What every number formatter prints for a value that is not there. null and undefined are ABSENCE (nothing
// collected, no figure), never zero: Math.abs(null), Math.round(null) and null.toLocaleString-style coercions
// all give 0 in JavaScript, which is how a missing figure used to print as "₱0" (audit FE-4, 2026-10-20). A real
// zero still prints as a zero. The backend makes the same distinction (null + a reason vs 0).
export const NOT_COLLECTED = '—';
export const isMissing = (value) => value == null || (typeof value === 'number' && Number.isNaN(value));

// Exact pesos, thousands-separated: ₱1,234,567 (Charts tooltip, purchases tooltip).
export function formatExactPesos(value) {
  return isMissing(value) ? NOT_COLLECTED : `₱${Math.round(value).toLocaleString('en-PH')}`;
}

// A quantity in a few characters: 3,800,930 -> 3.8M, 356,287 -> 356k, 812 -> 812. Axis ticks and direct labels.
// `millionDigits` is how many decimals a million shows (trailing zeros dropped).
export function formatCompactQty(value, millionDigits = 1) {
  if (isMissing(value)) return NOT_COLLECTED;
  const n = Math.abs(value);
  // 999,600 rounds to "1000k" in thousands, so it is shown as 1M instead.
  if (Math.round(n / 1_000) >= 1_000) return `${parseFloat((value / 1_000_000).toFixed(millionDigits))}M`;
  if (n >= 1_000) return `${Math.round(value / 1_000)}k`;
  return `${Math.round(value)}`;
}

// ₱500k / ₱1.2M / ₱0 — compact currency, unsigned (callers prepend a sign
// where one is needed). Shared by the axis ticks and the bar-end labels so
// the two can never disagree on formatting.
export function formatCompactPesos(value) {
  if (isMissing(value)) return NOT_COLLECTED;
  const abs = Math.abs(value);
  // A five-year total passes ₱1 billion (2026-10-16): ₱1.51B, not ₱1511.7M.
  if (abs >= 1_000_000_000) {
    const billions = abs / 1_000_000_000;
    return `₱${Number.isInteger(billions) ? billions : Math.round(billions * 100) / 100}B`;
  }
  if (abs >= 1_000_000) {
    const millions = abs / 1_000_000;
    return `₱${Number.isInteger(millions) ? millions : millions.toFixed(1)}M`;
  }
  if (abs >= 1_000) return `₱${Math.round(abs / 1000)}k`;
  return `₱${Math.round(abs)}`;
}
