// frontend/src/api/profile.js — the signed-in person's own profile (the My
// profile page): display name and picture, PATCH /auth/me
// (backend/routers/auth.py, backend/profile.py).
import { apiFetch } from '../auth';

// body: { full_name?: string, avatar_data_url?: string | null } — a field
// left out is unchanged; avatar_data_url null removes the picture.
// -> the same shape as GET /auth/me, with the new values.
export async function updateProfile(body) {
  const res = await apiFetch('/auth/me', { method: 'PATCH', body: JSON.stringify(body) });
  const payload = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = payload?.detail;
    const err = new Error(typeof detail === 'string' ? detail : 'Could not save your profile.');
    err.status = res.status;
    err.code = payload?.code;
    throw err;
  }
  return payload;
}
