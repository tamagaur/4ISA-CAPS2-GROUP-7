import { apiFetch } from '../auth';
import { cachedRequest } from './cache';
import { appendPrincipal } from '../principals';

// GET /segment?sku=<sku_code> — one SKU's demand pattern (trend and
// variability, from sku_traits + sku_segment). Two honest non-error answers besides a hit:
//   - 200 with analyzed=false: the product exists but the segmentation run
//     hasn't covered it (its cohort is Unilever Tier A, 2026-02, so this
//     is the common case) — callers show a "not yet analyzed" state.
//   - 404: no such product for that principal — resolved to null here,
//     same convention as getForecast.
// principal scopes the sku_code lookup (codes aren't unique across
// principals), and is part of the cache key for the same reason.
export function getSegment(skuId, { principal } = {}) {
  const query = new URLSearchParams();
  query.append('sku', skuId);
  appendPrincipal(query, principal);
  const path = `/segment?${query.toString()}`;

  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error('Failed to fetch the SKU demand pattern');
    return res.json();
  });
}
