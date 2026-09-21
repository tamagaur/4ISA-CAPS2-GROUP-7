import { apiFetch } from '../auth';
import { cachedRequest } from './cache';
import { appendPrincipal } from '../principals';

// The descriptive / predictive endpoints added for the analytical mapping:
//   GET /fsn              D3  fast / slow / non-moving per product
//   GET /pareto           D1  brand- and category-level ABC
//   GET /decomposition    D4  STL trend / seasonality of one SKU
//   GET /category-trends  P1  category revenue trend, 12 months ahead
// All read-only and computed from the loaded history, so the usual
// response cache applies.

async function getJson(path, what) {
  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`Failed to fetch ${what}`);
    return res.json();
  });
}

export function getFsn({ principal, period } = {}) {
  const query = new URLSearchParams();
  appendPrincipal(query, principal);
  if (period) query.append('period', period);
  const qs = query.toString();
  return getJson(`/fsn${qs ? `?${qs}` : ''}`, 'FSN classification');
}

export function getPareto({ grain = 'brand', principal, period, months = 1 } = {}) {
  const query = new URLSearchParams({ grain, months: String(months) });
  appendPrincipal(query, principal);
  if (period) query.append('period', period);
  return getJson(`/pareto?${query.toString()}`, 'Pareto');
}

export function getDecomposition(sku, { principal } = {}) {
  const query = new URLSearchParams({ sku });
  appendPrincipal(query, principal);
  return getJson(`/decomposition?${query.toString()}`, 'STL decomposition');
}

export function getCategoryTrends({ principal } = {}) {
  const query = new URLSearchParams();
  appendPrincipal(query, principal);
  const qs = query.toString();
  return getJson(`/category-trends${qs ? `?${qs}` : ''}`, 'category trends');
}
