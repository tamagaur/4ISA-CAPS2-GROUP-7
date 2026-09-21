import { apiFetch } from '../auth';

export async function getAuditLog({ action, excludeActions, userEmail, limit } = {}) {
  const query = new URLSearchParams();
  if (action) query.append('action', action);
  (excludeActions || []).forEach((a) => query.append('exclude_action', a));
  if (userEmail) query.append('user_email', userEmail);
  if (limit) query.append('limit', limit);

  const res = await apiFetch(`/audit-log?${query.toString()}`);
  if (!res.ok) {
    throw new Error('Failed to fetch audit log');
  }
  return res.json();
}

export async function postAuditLogEntry(action, details) {
  const res = await apiFetch('/audit-log', {
    method: 'POST',
    body: JSON.stringify({ action, details }),
  });
  if (!res.ok) {
    throw new Error('Failed to record audit log entry');
  }
  return res.json();
}

// One row per user: sign-in count and longest session (GET /audit-log/users).
export async function getAuditUserSummary() {
  const res = await apiFetch('/audit-log/users');
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || 'Failed to fetch audit log');
  }
  return res.json();
}
