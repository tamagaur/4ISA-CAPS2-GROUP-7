import { apiFetch } from '../auth';
import { cachedRequest } from './cache';
import { appendPrincipal } from '../principals';

// principal ('all' | 'unilever' | 'delmonte') restored 2026-09-17 — see
// src/principals.js. It scopes which principal's product the sku_code
// resolves to: sku_code is NOT unique across principals in
// product_dimension, so an unscoped lookup could match either one's row.
export function getForecast(skuId, { principal } = {}) {
  const query = new URLSearchParams();
  appendPrincipal(query, principal);
  const qs = query.toString();
  const path = `/forecast/${encodeURIComponent(skuId)}${qs ? `?${qs}` : ''}`;

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

// The synthetic view, Del Monte (schema demo, CLAUDE.md rule 2): one product
// category's demonstration history and its 3-month-average forecast, from
// GET /forecast/{category}?principal=delmonte&category=. Every point says how
// it was made (`origin`); no accuracy and no range come with it. Null when the
// server's DM_DEMO_ENABLED switch is off.
export function getDemoCategoryForecast(category) {
  const path = `/forecast/${encodeURIComponent(category)}?principal=delmonte&category=${encodeURIComponent(category)}`;
  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error('Failed to fetch the category forecast');
    return res.json();
  });
}
