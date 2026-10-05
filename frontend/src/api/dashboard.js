import { apiFetch } from '../auth';
import { cachedRequest, peekCache } from './cache';
import { appendPrincipal } from '../principals';

// This is the ONLY place this shape is defined — components must never
// import it directly, only call getDashboardData(), so swapping the
// backend implementation later stays a one-file change.
//
// principal ('all' | 'unilever' | 'delmonte') restored 2026-09-17 — see
// src/principals.js. It's part of the path (not a header) so the response
// cache keys each scope separately and switching principals can't serve
// another scope's numbers.
function dashboardPath({ period, startPeriod, principal } = {}) {
  const query = new URLSearchParams();
  if (period) query.append('period', period);
  if (startPeriod) query.append('start_period', startPeriod);
  appendPrincipal(query, principal);
  const qs = query.toString();
  return `/dashboard${qs ? `?${qs}` : ''}`;
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

// GET /dashboard/pareto and /dashboard/yoy (backend/routers/dashboard_range
// .py): the selected range's ranking with each class's products, and each
// product's sales against the same months a year earlier. Same query shape
// and cache as the dashboard itself.
function rangeRequest(route, { period, startPeriod, principal } = {}) {
  const query = new URLSearchParams();
  if (period) query.append('period', period);
  if (startPeriod) query.append('start_period', startPeriod);
  appendPrincipal(query, principal);
  const qs = query.toString();
  const path = `/dashboard/${route}${qs ? `?${qs}` : ''}`;
  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (!res.ok) throw new Error(`Failed to fetch the ${route} data`);
    return res.json();
  });
}

export const getRangePareto = (args) => rangeRequest('pareto', args);
export const getRangeYoy = (args) => rangeRequest('yoy', args);
