import { apiFetch } from '../auth';
import { cachedRequest } from './cache';
import { appendPrincipal } from '../principals';

// principal ('all' | 'unilever' | 'delmonte') restored 2026-09-17 — see
// src/principals.js. NOTE: Del Monte has no abc_classification rows yet,
// so 'delmonte' legitimately returns an empty result until ABC is run for
// it at category grain; that's an honest empty, not a failed request.
export function getABCClassification({ classification_period, principal } = {}) {
  const query = new URLSearchParams();
  if (classification_period) query.append('classification_period', classification_period);
  appendPrincipal(query, principal);
  const path = `/abc?${query.toString()}`;

  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (!res.ok) {
      throw new Error('Failed to fetch ABC classification data');
    }
    return res.json();
  });
}
