import { apiFetch } from '../auth';
import { cachedRequest, invalidateCache } from './cache';
import { appendPrincipal } from '../principals';

// principal ('all' | 'unilever' | 'delmonte') restored 2026-09-17 — see
// src/principals.js. Both principals have real product_dimension rows, so
// every scope returns data here; note they differ in grain (DEC-03), so an
// 'all' list mixes SKU- and category-grain rows by design.
export function getSKUs({ status, principal } = {}) {
  const query = new URLSearchParams();
  if (status) query.append('status', status);
  appendPrincipal(query, principal);
  const path = `/sku?${query.toString()}`;

  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (!res.ok) {
      // Surface the backend's own `detail` when there is one, same as
      // createSKU/updateSKU below — this used to always throw the generic
      // string, flattening a real cause (DB down, auth rejected) into
      // something the user couldn't act on.
      const body = await res.json().catch(() => null);
      throw new Error(body?.detail || 'Failed to fetch SKUs');
    }
    return res.json();
  });
}

export async function createSKU(payload) {
  const res = await apiFetch('/sku', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || 'Failed to create SKU');
  }
  invalidateCache();
  return res.json();
}

export async function updateSKU(productKey, payload) {
  const res = await apiFetch(`/sku/${productKey}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || 'Failed to update SKU');
  }
  // A SKU edit can change what the SKU list, ABC and forecast pages show,
  // so every cached read is dropped rather than tracking which ones.
  invalidateCache();
  return res.json();
}
