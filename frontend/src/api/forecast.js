import { apiFetch } from '../auth';

// Unilever-only (2026-09): no more principal param — the backend always
// resolves sku_id against Unilever now.
export async function getForecast(skuId) {
  const res = await apiFetch(`/forecast/${encodeURIComponent(skuId)}`);
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error('Failed to fetch forecast data');
  }
  return res.json();
}
