// frontend/src/api/profile.js — the signed-in person's own profile (the My
// profile page): display name and picture, PATCH /auth/me
// (backend/routers/auth.py, backend/profile.py), and changing the password.
import { apiFetch } from '../auth';

// POST /auth/change-password. Throws with err.code 'wrong_current_password'
// (400), 'same_password' (422) or a 429 after too many wrong current
// passwords; err.message is the server's sentence.
export async function changePassword(currentPassword, newPassword) {
  const res = await apiFetch('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    const detail = payload?.detail;
    const err = new Error(typeof detail === 'string' ? detail : 'Could not change your password.');
    err.status = res.status;
    err.code = payload?.code;
    throw err;
  }
}

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
