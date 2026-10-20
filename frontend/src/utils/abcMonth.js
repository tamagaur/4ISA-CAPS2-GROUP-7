// The month the ABC picker should show after a response (FE-6).
//
// The picker carries the previous selection over a principal change, which is the
// "equivalent period" for the new principal. GET /abc answers with the nearest
// classification run at or before the month asked for: if that is the month asked for,
// the equivalent period exists and stays. If it is earlier, the principal has no run for
// that month and the picker moves to the run the response was actually built from, which is
// the principal's latest run whenever the carried-over month lies after it (Unilever's
// latest run is 2026-02, Del Monte's 2025-12). It never moves forward.
// Returns the 'YYYY-MM' to select, or null to leave the selection alone.
export function monthToSelect(requested, resolved) {
  if (!requested || !resolved) return null;
  return resolved < requested ? resolved : null;
}

// The latest run for a scope, from GET /abc's tier_a_periods ({ 'Unilever': '2026-02', ... }).
// `label` is the principal's display name, or null for all principals (the latest of any).
export function latestRunFor(tierAPeriods, label) {
  const entries = Object.entries(tierAPeriods || {});
  const periods = (label ? entries.filter(([k]) => k === label) : entries).map(([, p]) => p).filter(Boolean);
  return periods.length ? periods.sort().at(-1) : null;
}
