import { apiFetch } from '../auth';

// Unilever-only (2026-09): no more principal param — the backend always
// scopes to Unilever now.
export async function getSKUs({ status } = {}) {
  const query = new URLSearchParams();
  if (status) query.append('status', status);

  const res = await apiFetch(`/sku?${query.toString()}`);
  if (!res.ok) {
    throw new Error('Failed to fetch SKUs');
  }
  return res.json();
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
  return res.json();
}
