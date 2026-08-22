import { apiFetch } from '../auth';

export async function getRecommendations({ principal, status } = {}) {
  const query = new URLSearchParams();
  if (principal && principal !== 'all') query.append('principal', principal);
  if (status) query.append('status', status);

  const res = await apiFetch(`/recommendations?${query.toString()}`);
  if (!res.ok) {
    throw new Error('Failed to fetch reorder recommendations');
  }
  return res.json();
}

export async function decideRecommendation(recommendationKey, status) {
  const res = await apiFetch(`/recommendations/${recommendationKey}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) {
    throw new Error('Failed to update recommendation');
  }
  return res.json();
}
