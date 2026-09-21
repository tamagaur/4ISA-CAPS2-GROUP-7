import { apiFetch } from '../auth';
import { cachedRequest } from './cache';
import { appendPrincipal } from '../principals';

// principal ('all' | 'unilever' | 'delmonte') restored 2026-09-17 — see
// src/principals.js. NOTE: Del Monte has no abc_classification rows yet,
// so 'delmonte' legitimately returns an empty result until ABC is run for
// it at category grain; that's an honest empty, not a failed request.
//
// view: 'last_known' returns each product's most recent tier at or before
// the period, each with its own tier_period (see backend/routers/abc.py).
// Omitted = the backend default, only SKUs ranked in that one run.
export function getABCClassification({ classification_period, principal, view } = {}) {
  const query = new URLSearchParams();
  if (classification_period) query.append('classification_period', classification_period);
  if (view) query.append('view', view);
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
