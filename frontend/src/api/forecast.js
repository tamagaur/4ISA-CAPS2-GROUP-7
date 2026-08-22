import { apiFetch } from '../auth';

export async function getForecast(skuId, principal) {
  const query = new URLSearchParams({ principal });
  const res = await apiFetch(`/forecast/${encodeURIComponent(skuId)}?${query.toString()}`);
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error('Failed to fetch forecast data');
  }
  return res.json();
}
