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
      // The status lets the page say why in plain words (ui/LoadError.jsx).
      const err = new Error('Failed to fetch dashboard data');
      err.status = res.status;
      throw err;
    }
    return res.json();
  }, { force });
}

export function peekDashboardData(args = {}) {
  return peekCache(dashboardPath(args));
}

// The range routes the data marts added (backend/routers/dashboard_range.py,
// 2026-10-04/05). Each takes the dashboard's own range and principal, so a
// card's list is always the one behind the figure GET /dashboard gave it.
function rangePath(route, { period, startPeriod, principal, ...extra } = {}) {
  const query = new URLSearchParams();
  if (period) query.append('period', period);
  if (startPeriod) query.append('start_period', startPeriod);
  Object.entries(extra).forEach(([key, value]) => {
    if (value != null) query.append(key, value);
  });
  appendPrincipal(query, principal);
  const qs = query.toString();
  return `/dashboard/${route}${qs ? `?${qs}` : ''}`;
}

function getRange(route, args, failure) {
  const path = rangePath(route, args);
  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (!res.ok) throw new Error(failure);
    return res.json();
  });
}

// Every product idle at the range-end count (the dashboard carries the first 10).
export function getIdleStock(args = {}) {
  const { startPeriod, ...rest } = args; // the count is the range's end; no start
  return getRange('idle-stock', rest, 'Failed to load the idle stock list');
}

// Products that entered or left Class A against the same months a year before.
export function getClassChanges(args = {}) {
  return getRange('class-changes', args, 'Failed to load Class A changes');
}

// Forecast against sales; level 'product' gives one row per product x month.
export function getForecastAccuracy(args = {}) {
  return getRange('accuracy', { level: 'summary', ...args }, 'Failed to load forecast accuracy');
}

// Del Monte's product sales, estimated from total sales x stock share (DEC-31).
export function getProductSales(args = {}) {
  return getRange('product-sales', args, 'Failed to load product sales');
}

// The selected range ranked into classes A/B/C, with each class's products
// (the same ranking the dashboard's ABC ring draws, so counts match).
export function getRangePareto(args = {}) {
  return getRange('pareto', args, 'Failed to load the class list');
}

// Per product (Del Monte: category), the range's real sales against the same
// months a year earlier.
export function getRangeYoy(args = {}) {
  return getRange('yoy', args, 'Failed to load the year-over-year figures');
}
