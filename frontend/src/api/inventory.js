import { apiFetch } from '../auth';

export async function getInventoryCurrent({ principal, from, to }) {
  const query = new URLSearchParams();
  if (principal) query.append('principal', principal);
  if (from) query.append('from', from);
  if (to) query.append('to', to);
  
  const res = await apiFetch(`/inventory/current?${query.toString()}`);
  if (!res.ok) {
    throw new Error('Failed to fetch current inventory');
  }
  return res.json();
}

export async function getInventoryMovement({ principal, from, to }) {
  const query = new URLSearchParams();
  if (principal) query.append('principal', principal);
  if (from) query.append('from', from);
  if (to) query.append('to', to);
  
  const res = await apiFetch(`/inventory/movement?${query.toString()}`);
  if (!res.ok) {
    throw new Error('Failed to fetch inventory movement');
  }
  return res.json();
}
