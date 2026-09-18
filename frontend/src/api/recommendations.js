import { apiFetch } from '../auth';
import { cachedRequest, invalidateCache } from './cache';
import { appendPrincipal } from '../principals';

// Unilever-only (2026-09): no more principal param — the backend always
// scopes to Unilever now. from/to (2026-09): the shared date-range
// picker's applied start/end, 'YYYY-MM-DD' — filters on planning_cycle_date.
// Both must be given together or neither is used, matching every other
// call site of the shared picker (see backend/routers/recommendations.py).
export function getRecommendations({ status, from, to, principal } = {}) {
  const query = new URLSearchParams();
  if (status) query.append('status', status);
  appendPrincipal(query, principal);
  if (from && to) {
    query.append('from', from);
    query.append('to', to);
  }
  const path = `/recommendations?${query.toString()}`;

  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (!res.ok) {
      throw new Error('Failed to fetch reorder recommendations');
    }
    return res.json();
  });
}

export async function decideRecommendation(recommendationKey, status) {
  const res = await apiFetch(`/recommendations/${recommendationKey}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) {
    throw new Error('Failed to update recommendation');
  }
  // An accepted/dismissed row changes this page's list AND the Dashboard's
  // reorder preview counts, so drop everything rather than guess which
  // cached responses it touched.
  invalidateCache();
  return res.json();
}
