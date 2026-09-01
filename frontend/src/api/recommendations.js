import { apiFetch } from '../auth';

// Unilever-only (2026-09): no more principal param — the backend always
// scopes to Unilever now. from/to (2026-09): the shared date-range
// picker's applied start/end, 'YYYY-MM-DD' — filters on planning_cycle_date.
// Both must be given together or neither is used, matching every other
// call site of the shared picker (see backend/routers/recommendations.py).
export async function getRecommendations({ status, from, to } = {}) {
  const query = new URLSearchParams();
  if (status) query.append('status', status);
  if (from && to) {
    query.append('from', from);
    query.append('to', to);
  }

  const res = await apiFetch(`/recommendations?${query.toString()}`);
  if (!res.ok) {
    throw new Error('Failed to fetch reorder recommendations');
  }
  return res.json();
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
  return res.json();
}
