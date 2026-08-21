import { apiFetch } from '../auth';

export async function getDashboardData({ principal, from, to }) {
  const query = new URLSearchParams();
  if (principal) query.append('principal', principal);
  if (from) query.append('from', from);
  if (to) query.append('to', to);
  
  const res = await apiFetch(`/dashboard?${query.toString()}`);
  if (!res.ok) {
    throw new Error('Failed to fetch dashboard data');
  }
  return res.json();
}
