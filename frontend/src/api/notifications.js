// frontend/src/api/notifications.js — the notification bell (backend/routers/
// notifications.py, migration 0071, 2026-10-28). Each call reads or marks the
// signed-in user's OWN notifications only. Marking one read never changes the
// request it points to: the request's state is `request_state`, read from the
// request's own row.
//
// GET /notifications -> { ready, unread_count, items: [{ notification_key,
//   kind, request_kind: 'quantity_change'|'dismissal', request_key,
//   recommendation_key, sku_code, product_name, actor_email, actor_name,
//   summary, created_at, read_at, request_state }] }
// ready is false until migration 0071 is applied: the bell then shows nothing.
import { apiFetch } from '../auth';
import { RequestError } from './recommendations';

async function fail(res, fallback) {
  const body = await res.json().catch(() => null);
  const message = typeof body?.detail === 'string' && body.detail ? body.detail : fallback;
  return new RequestError(message, { status: res.status, code: body?.code ?? null, extra: {} });
}

export async function getNotifications({ limit = 30 } = {}) {
  const res = await apiFetch(`/notifications?limit=${encodeURIComponent(limit)}`);
  if (!res.ok) throw await fail(res, 'Failed to load notifications');
  return res.json();
}

export async function markNotificationRead(notificationKey) {
  const res = await apiFetch(`/notifications/${encodeURIComponent(notificationKey)}/read`, { method: 'POST' });
  if (!res.ok) throw await fail(res, 'Failed to mark the notification read');
  return res.json();
}

export async function markAllNotificationsRead() {
  const res = await apiFetch('/notifications/read-all', { method: 'POST' });
  if (!res.ok) throw await fail(res, 'Failed to mark the notifications read');
  return res.json();
}
