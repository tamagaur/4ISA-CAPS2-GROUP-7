import { apiFetch } from '../auth';

// Unilever-only (2026-09): no more principal param — the backend always
// scopes to Unilever now.
export async function getABCClassification({ classification_period } = {}) {
  const query = new URLSearchParams();
  if (classification_period) query.append('classification_period', classification_period);

  const res = await apiFetch(`/abc?${query.toString()}`);
  if (!res.ok) {
    throw new Error('Failed to fetch ABC classification data');
  }
  return res.json();
}
