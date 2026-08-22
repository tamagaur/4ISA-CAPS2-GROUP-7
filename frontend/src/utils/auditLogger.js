import { postAuditLogEntry } from '../api/auditLog';

// Fire-and-forget: callers don't await this (e.g. auth.js's login/logout,
// action handlers throughout the app), so a failed write here must never
// throw into the caller's flow — it's best-effort logging, not a user-
// facing operation. user identity is attached server-side from the JWT,
// not sent from here (see backend/routers/audit_log.py).
export const logAction = (action, details) => {
  postAuditLogEntry(action, details).catch((err) => {
    console.error('Failed to record audit log entry:', err);
  });
};
