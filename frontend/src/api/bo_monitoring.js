import { apiFetch } from '../auth';

export async function getBOMonitoringData({ principal, from, to }) {
  const query = new URLSearchParams();
  if (principal) query.append('principal', principal);
  if (from) query.append('from', from);
  if (to) query.append('to', to);
  
  const res = await apiFetch(`/bo-monitoring?${query.toString()}`);
  if (!res.ok) {
    throw new Error('Failed to fetch BO monitoring data');
  }
  return res.json();
}
