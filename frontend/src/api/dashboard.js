import { apiFetch } from '../auth';

// This is the ONLY place this shape is defined — components must never
// import it directly, only call getDashboardData(), so swapping the
// backend implementation later stays a one-file change.
export async function getDashboardData({ principal }) {
  const res = await apiFetch(`/dashboard?principal=${principal || 'all'}`);
  if (!res.ok) {
    throw new Error('Failed to fetch dashboard data');
  }
  return res.json();
}
