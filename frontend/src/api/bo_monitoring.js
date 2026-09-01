import { apiFetch } from '../auth';

// Unilever-only (2026-09): no more principal param — the backend always
// scopes to Unilever now.
export async function getBOMonitoringData({ from, to } = {}) {
  const query = new URLSearchParams();
  if (from) query.append('from', from);
  if (to) query.append('to', to);
  
  const res = await apiFetch(`/bo-monitoring?${query.toString()}`);
  if (!res.ok) {
    throw new Error('Failed to fetch BO monitoring data');
  }
  return res.json();
}
