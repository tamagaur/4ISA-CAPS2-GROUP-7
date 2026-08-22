import { apiFetch } from '../auth';

export async function getABCClassification({ principal, classification_period } = {}) {
  const query = new URLSearchParams();
  if (principal && principal !== 'all') query.append('principal', principal);
  if (classification_period) query.append('classification_period', classification_period);

  const res = await apiFetch(`/abc?${query.toString()}`);
  if (!res.ok) {
    throw new Error('Failed to fetch ABC classification data');
  }
  return res.json();
}
