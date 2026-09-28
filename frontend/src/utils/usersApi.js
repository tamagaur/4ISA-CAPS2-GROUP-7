// frontend/src/utils/usersApi.js — admin-only user management calls.
// Create goes through /auth/register (the account that's already wired for
// admin-only + duplicate-email checks); list/update/delete/send-link hit
// /users. Admins never set or see a password: new accounts get an emailed
// one-time link and choose their own (see SetPassword.jsx).
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

// -> { user, email_sent, setup_link, expires_at, email_problem }. The
// server emails the invite itself; setup_link is only filled in when that
// email didn't go out, so the admin can pass the link on by hand.
export async function createUser({ email, fullName, role }) {
  const res = await apiFetch('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, full_name: fullName, role }),
  });
  await parseErrorOrThrow(res, 'Failed to create user.');
  return res.json();
}

export async function updateUser(userId, { email, fullName, role }) {
  const body = {};
  if (email !== undefined) body.email = email;
  if (fullName !== undefined) body.full_name = fullName;
  if (role !== undefined) body.role = role;

  const res = await apiFetch(`/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
  await parseErrorOrThrow(res, 'Failed to update user.');
  return res.json();
}

// Emails a fresh one-time link: an invite while the account has no password
// yet, a reset link once it has one. -> { purpose: 'invite' | 'reset',
// email_sent, setup_link, expires_at, email_problem }, same rule for
// setup_link as createUser.
export async function sendUserLink(userId) {
  const res = await apiFetch(`/users/${userId}/send-link`, { method: 'POST' });
  await parseErrorOrThrow(res, 'Failed to send the link.');
  return res.json();
}

export async function deleteUser(userId) {
  const res = await apiFetch(`/users/${userId}`, { method: 'DELETE' });
  await parseErrorOrThrow(res, 'Failed to delete user.');
}
