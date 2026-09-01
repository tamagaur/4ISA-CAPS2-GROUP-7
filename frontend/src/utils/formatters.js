// Split out of Charts.jsx (2026-08): a component file that also exports a
// plain function breaks Vite's React Fast Refresh — every edit to Charts.jsx
// forced a full HMR "invalidate" (visible in the dev server log) instead of
// a clean hot-swap, which meant an already-open browser tab could keep
// showing stale state after a change until a hard refresh. Kept here so
// Charts.jsx goes back to exporting components only.
//
// ₱500k / ₱1.2M / ₱0 — compact currency, unsigned (callers prepend a sign
// where one is needed). Shared by the axis ticks and the bar-end labels so
// the two can never disagree on formatting.
export function formatCompactPesos(value) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) {
    const millions = abs / 1_000_000;
    return `₱${Number.isInteger(millions) ? millions : millions.toFixed(1)}M`;
  }
  if (abs >= 1_000) return `₱${Math.round(abs / 1000)}k`;
  return `₱${Math.round(abs)}`;
}
