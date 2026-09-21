import { apiFetch } from '../auth';
import { cachedRequest } from './cache';
import { appendPrincipal } from '../principals';

// GET /bo-monitoring — bad-order (BO) returns by month and principal
// (backend/routers/bo_monitoring.py). No date range is sent: the loaded BO
// history is short (Del Monte, 2025-03..2025-12 as of 2026-09-21), and the
// page shows all of it with its gaps.
export function getBoMonitoring({ principal } = {}) {
  const query = new URLSearchParams();
  appendPrincipal(query, principal);
  const qs = query.toString();
  const path = `/bo-monitoring${qs ? `?${qs}` : ''}`;

  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (!res.ok) throw new Error('Failed to fetch bad-order data');
    return res.json();
  });
}
