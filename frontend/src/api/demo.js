import { apiFetch } from '../auth';
import { cachedRequest } from './cache';

// GET /demo/index — the synthetic demonstration's series for one principal
// (schema demo, CLAUDE.md rule 2; docs/DEMO_DATA.md), each with its taxonomy
// (Del Monte: the 'pre_2025' paths and the '2025' categories) and how many of
// its months are of each origin. Null when the server's DM_DEMO_ENABLED
// switch is off (a plain 404).
export function getDemoIndex(principal) {
  const path = `/demo/index?principal=${encodeURIComponent(principal)}`;
  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error('Failed to fetch the synthetic data index');
    return res.json();
  });
}
