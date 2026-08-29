import { apiFetch } from '../auth';

// This is the ONLY place this shape is defined — components must never
// import it directly, only call getDashboardData(), so swapping the
// backend implementation later stays a one-file change.
export async function getDashboardData({ principal, period, startPeriod }) {
  const periodParam = period ? `&period=${period}` : '';
  const startPeriodParam = startPeriod ? `&start_period=${startPeriod}` : '';
  const res = await apiFetch(`/dashboard?principal=${principal || 'all'}${periodParam}${startPeriodParam}`);
  if (!res.ok) {
    throw new Error('Failed to fetch dashboard data');
  }
  return res.json();
}
