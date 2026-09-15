import { apiFetch } from '../auth';
import { cachedRequest } from './cache';

// Unilever-only (2026-09): no more principal param — the backend always
// scopes to Unilever now.
export function getABCClassification({ classification_period } = {}) {
  const query = new URLSearchParams();
  if (classification_period) query.append('classification_period', classification_period);
  const path = `/abc?${query.toString()}`;

  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (!res.ok) {
      throw new Error('Failed to fetch ABC classification data');
    }
    return res.json();
  });
}
