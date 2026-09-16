import { apiFetch } from '../auth';
import { cachedRequest, peekCache } from './cache';

// This is the ONLY place this shape is defined — components must never
// import it directly, only call getDashboardData(), so swapping the
// backend implementation later stays a one-file change.
//
// Unilever-only (2026-09): no more principal param — the backend always
// scopes to Unilever now.
function dashboardPath({ period, startPeriod } = {}) {
  const periodParam = period ? `?period=${period}` : '';
  const startPeriodParam = startPeriod ? `${periodParam ? '&' : '?'}start_period=${startPeriod}` : '';
  return `/dashboard${periodParam}${startPeriodParam}`;
}

export function getDashboardData(args = {}, { force = false } = {}) {
  const path = dashboardPath(args);
  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (!res.ok) {
      throw new Error('Failed to fetch dashboard data');
    }
    return res.json();
  }, { force });
}

export function peekDashboardData(args = {}) {
  return peekCache(dashboardPath(args));
}
