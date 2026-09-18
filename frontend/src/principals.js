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

// Default scope on first load: 'all'.
//
// Note: under 'all' the backend applies its honest-null rule
// (backend/routers/dashboard.py's _combine_principal_sums) — a period only
// reports a combined figure when BOTH principals have real data for it.
// Unilever's demand runs through 2026-02 while Del Monte's sellout stops
// at 2025-12, so periods in that gap will show as blank under 'all' rather
// than falling back to a single principal's data.
export const DEFAULT_PRINCIPAL = 'all';

export const PRINCIPAL_STORAGE_KEY = 'san2_principal';

export function isValidPrincipal(value) {
  return PRINCIPAL_KEYS.includes(value);
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
  if (principal && principal !== 'all') query.append('principal', principal);
  return query;
}
