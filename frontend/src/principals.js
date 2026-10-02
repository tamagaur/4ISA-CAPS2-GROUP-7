// Principal filter — the three scopes the whole app shares.
//
// Restored 2026-09-17 after the 2026-09 Unilever-only period (commit
// c4be61c). Kept in one module so the Topbar's segmented control, the
// localStorage key, and every api/*.js wrapper agree on the exact strings
// the backend validates against (backend/principals.py's VALID_PRINCIPALS).
export const PRINCIPALS = [
  { key: 'all', label: 'All principals' },
  { key: 'delmonte', label: 'Del Monte' },
  { key: 'unilever', label: 'Unilever' },
];

export const PRINCIPAL_KEYS = PRINCIPALS.map((p) => p.key);

// All principals is hidden from every filter for now (2026-09-30, Audrey):
// the Topbar offers Del Monte and Unilever only. Everything that handles
// 'all' stays in place — flip this to true to bring the option back. The
// Dashboard forecast card's own principal filter was removed at the same
// time; the code as it was is on branch parked/all-principals-filter.
export const SHOW_ALL_PRINCIPALS = false;

// The options a filter offers, and the only values a stored choice may
// restore to.
export const SELECTABLE_PRINCIPALS = SHOW_ALL_PRINCIPALS
  ? PRINCIPALS
  : PRINCIPALS.filter((p) => p.key !== 'all');

// The combined scope. Named, so the checks that mean "all principals" say
// so instead of leaning on DEFAULT_PRINCIPAL (which was 'all' until
// 2026-09-24).
//
// Note: under 'all' the backend applies its honest-null rule
// (backend/routers/dashboard.py's _combine_principal_sums) — a period only
// reports a combined figure when BOTH principals have real data for it.
// Unilever's demand runs through 2026-02 while Del Monte's sellout stops
// at 2025-12, so periods in that gap will show as blank under 'all' rather
// than falling back to a single principal's data.
export const ALL_PRINCIPALS = 'all';

// Default scope on first load: Unilever (2026-09-24, Audrey). The combined
// All principals figures are still being fixed, so no page opens on them;
// All principals and Del Monte stay one click away in the Topbar.
export const DEFAULT_PRINCIPAL = 'unilever';

// Bumped from 'san2_principal' with the default change. A scope saved under
// the old key could be All principals, the view this change keeps people
// off, so everyone starts once on the new default; choices made from here
// on are remembered as before.
export const PRINCIPAL_STORAGE_KEY = 'san2_principal_v2';

// Selectable, not merely known: a stored 'all' from before the option was
// hidden falls back to DEFAULT_PRINCIPAL instead of reopening on it.
export function isValidPrincipal(value) {
  return SELECTABLE_PRINCIPALS.some((p) => p.key === value);
}

export function labelForPrincipal(key) {
  return PRINCIPALS.find((p) => p.key === key)?.label || key;
}

// Appends ?principal= to a URLSearchParams, skipping 'all' so the common
// case stays the shortest URL (the backend treats an omitted param and
// 'all' identically). Shared so no wrapper invents its own convention —
// and because the response cache is keyed by path, an inconsistent
// spelling here would silently split the cache.
export function appendPrincipal(query, principal) {
  if (principal && principal !== ALL_PRINCIPALS) query.append('principal', principal);
  return query;
}
