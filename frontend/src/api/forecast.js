import { apiFetch } from '../auth';
import { cachedRequest } from './cache';

// Unilever-only (2026-09): no more principal param — the backend always
// resolves sku_id against Unilever now.
export function getForecast(skuId) {
  const path = `/forecast/${encodeURIComponent(skuId)}`;

  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (res.status === 404) {
      return null;
    }
    if (!res.ok) {
      throw new Error('Failed to fetch forecast data');
    }
    return res.json();
  });
}
