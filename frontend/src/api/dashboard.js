import { apiFetch } from '../auth';

// This is the ONLY place this shape is defined — components must never
// import it directly, only call getDashboardData(), so swapping the
// backend implementation later stays a one-file change.
//
// Unilever-only (2026-09): no more principal param — the backend always
// scopes to Unilever now.
export async function getDashboardData({ period, startPeriod } = {}) {
  const periodParam = period ? `?period=${period}` : '';
  const startPeriodParam = startPeriod ? `${periodParam ? '&' : '?'}start_period=${startPeriod}` : '';
  const res = await apiFetch(`/dashboard${periodParam}${startPeriodParam}`);
  if (!res.ok) {
    throw new Error('Failed to fetch dashboard data');
  }
  return res.json();
}
