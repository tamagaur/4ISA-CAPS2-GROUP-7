// frontend/src/utils/usersApi.js — admin-only user management calls.
// Create goes through /auth/register (the account that's already wired for
// admin-only + duplicate-email checks); list/update/delete hit /users.
import { apiFetch } from '../auth';

async function parseErrorOrThrow(res, fallback) {
  if (res.ok) return res;
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  const message = typeof detail === 'string'
    ? detail
    : Array.isArray(detail)
      ? detail.map((e) => e.msg || JSON.stringify(e)).join(' ')
      : fallback;
  throw new Error(message);
}

export async function listUsers() {
  const res = await apiFetch('/users');
  await parseErrorOrThrow(res, 'Failed to load users.');
  return res.json();
}

export async function createUser({ email, password, fullName, role }) {
  const res = await apiFetch('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password, full_name: fullName, role }),
  });
  await parseErrorOrThrow(res, 'Failed to create user.');
  return res.json();
}

export async function updateUser(userId, { email, password, fullName, role }) {
  const body = {};
  if (email !== undefined) body.email = email;
  if (fullName !== undefined) body.full_name = fullName;
  if (role !== undefined) body.role = role;
  if (password) body.password = password;

  const res = await apiFetch(`/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
  await parseErrorOrThrow(res, 'Failed to update user.');
  return res.json();
}

export async function deleteUser(userId) {
  const res = await apiFetch(`/users/${userId}`, { method: 'DELETE' });
  await parseErrorOrThrow(res, 'Failed to delete user.');
}
