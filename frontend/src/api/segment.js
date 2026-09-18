import { apiFetch } from '../auth';
import { cachedRequest } from './cache';
import { appendPrincipal } from '../principals';

// GET /segment?sku=<sku_code> — the Phase-2 diagnostic layer (sku_traits +
// sku_segment) for one SKU. Two honest non-error answers besides a hit:
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
    if (!res.ok) throw new Error('Failed to fetch SKU diagnostics');
    return res.json();
  });
}

// GET /segment/summary — the same sku_traits columns rolled up to cohort
// grain, for the dashboard's diagnostic panel. Returns analyzed_count=0
// with a blocked_reason (not an empty chart) when the requested principal
// has no segmentation rows — the run covers one cohort so far.
export function getSegmentSummary({ principal } = {}) {
  const query = new URLSearchParams();
  appendPrincipal(query, principal);
  const qs = query.toString();
  const path = `/segment/summary${qs ? `?${qs}` : ''}`;

  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (!res.ok) throw new Error('Failed to fetch segmentation summary');
    return res.json();
  });
}
