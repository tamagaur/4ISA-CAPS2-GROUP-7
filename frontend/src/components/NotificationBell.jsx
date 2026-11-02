// The notification bell in the top bar (2026-10-28, migration 0071,
// backend/routers/notifications.py).
//
// An admin is told when a staff member asks for a quantity change or a
// dismissal; the staff member is told when an admin approves or rejects it.
// The red badge is the UNREAD count, a separate number from the Staff
// Requests tab's pending count: reading a notification marks it read and
// nothing else, and the request keeps its own state (`request_state`, read
// from the request's row, shown on each item).
//
// There is no live push in this app, so the bell asks again every 60 s while
// the window is visible, when the window regains focus, and after its own
// writes. Clicking a notification marks it read and opens the request on the
// Reorder page (/reorder?tab=requests&request=<kind>-<key>).
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, Check, CheckCheck } from 'lucide-react';
import { getNotifications, markAllNotificationsRead, markNotificationRead } from '../api/notifications';
import { formatDateTime } from '../utils/formatDate';
import './NotificationBell.css';

const POLL_MS = 60_000;

const KIND_LABEL = {
  quantity_change_requested: 'Quantity change request',
  dismissal_requested: 'Dismissal request',
  quantity_change_approved: 'Quantity change approved',
  quantity_change_rejected: 'Quantity change rejected',
  dismissal_approved: 'Dismissal approved',
  dismissal_rejected: 'Dismissal rejected',
};

const STATE_PILL = {
  pending_approval: ['Pending', 'pill pill-warning'],
  approved: ['Approved', 'pill pill-success'],
  rejected: ['Rejected', 'pill pill-critical'],
};

const requestLink = (n) => `/reorder?tab=requests&request=${encodeURIComponent(`${n.request_kind}-${n.request_key}`)}`;

const NotificationBell = () => {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState({ status: 'loading', ready: true, unread: 0, items: [] });
  const [busy, setBusy] = useState(false);
  const rootRef = useRef(null);
  const latest = useRef(0);

  const load = useCallback(async () => {
    const call = ++latest.current;
    try {
      const res = await getNotifications({ limit: 30 });
      if (call !== latest.current) return;
      setData({ status: 'ready', ready: res.ready !== false, unread: res.unread_count ?? 0, items: res.items || [] });
    } catch (err) {
      if (call !== latest.current) return;
      // Keep what was shown; say the refresh failed.
      setData((prev) => ({ ...prev, status: prev.status === 'loading' ? 'error' : prev.status, error: err.message }));
    }
  }, []);

  // First load, then every minute while the window is visible, and on focus.
  useEffect(() => {
    load();
    const tick = () => { if (document.visibilityState === 'visible') load(); };
    const timer = setInterval(tick, POLL_MS);
    const onVisible = () => { if (document.visibilityState === 'visible') load(); };
    window.addEventListener('focus', onVisible);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', onVisible);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load]);

  // Close on a click outside or Escape; refresh when opened.
  useEffect(() => {
    if (!open) return undefined;
    load();
    const onDown = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, load]);

  const markRead = async (n) => {
    if (n.read_at) return;
    // Shown read at once; the server's answer settles the count.
    setData((prev) => ({
      ...prev,
      unread: Math.max(0, prev.unread - 1),
      items: prev.items.map((i) => (i.notification_key === n.notification_key ? { ...i, read_at: new Date().toISOString() } : i)),
    }));
    try {
      const res = await markNotificationRead(n.notification_key);
      setData((prev) => ({ ...prev, unread: res.unread_count ?? prev.unread }));
    } catch {
      load();
    }
  };

  const openItem = async (n) => {
    setOpen(false);
    await markRead(n);
    navigate(requestLink(n));
  };

  const markAll = async () => {
    setBusy(true);
    try {
      await markAllNotificationsRead();
    } catch {
      // The reload below shows whatever the server kept.
    }
    await load();
    setBusy(false);
  };

  const unread = data.ready ? data.unread : 0;
  const badge = unread > 99 ? '99+' : String(unread);

  return (
    <div className="notif" ref={rootRef}>
      <button
        type="button"
        className={`notif-btn${open ? ' is-open' : ''}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
        onClick={() => setOpen((v) => !v)}
      >
        <Bell size={18} aria-hidden="true" />
        {unread > 0 && <span className="notif-badge" aria-hidden="true">{badge}</span>}
      </button>

      {open && (
        <div className="notif-panel" role="dialog" aria-label="Notifications">
          <div className="notif-head">
            <span className="notif-title">Notifications</span>
            {data.ready && unread > 0 && (
              <button type="button" className="notif-markall" onClick={markAll} disabled={busy}>
                <CheckCheck size={14} aria-hidden="true" /> Mark all as read
              </button>
            )}
          </div>

          {data.status === 'loading' && <p className="notif-empty">Loading…</p>}
          {data.status === 'error' && (
            <p className="notif-empty" role="alert">
              Couldn&apos;t load notifications: {data.error}{' '}
              <button type="button" className="link-button" onClick={load}>Try again</button>
            </p>
          )}
          {data.status === 'ready' && !data.ready && (
            <p className="notif-empty">Notifications are not set up on this server yet.</p>
          )}
          {data.status === 'ready' && data.ready && data.items.length === 0 && (
            <p className="notif-empty">No notifications yet.</p>
          )}
          {data.status === 'ready' && data.ready && data.items.length > 0 && (
            <ul className="notif-list">
              {data.items.map((n) => {
                const [stateText, stateClass] = STATE_PILL[n.request_state] || [];
                return (
                  <li key={n.notification_key} className={`notif-item${n.read_at ? '' : ' is-unread'}`}>
                    <button type="button" className="notif-open" onClick={() => openItem(n)}>
                      <span className="notif-dot" aria-hidden="true" />
                      <span className="notif-body">
                        <span className="notif-line">
                          <strong>{n.actor_name || n.actor_email}</strong>
                          <span className="notif-kind">{KIND_LABEL[n.kind] || n.kind}</span>
                        </span>
                        <span className="notif-summary">
                          {n.product_name ? `${n.product_name} · ` : ''}{n.summary}
                        </span>
                        <span className="notif-meta">
                          <time dateTime={n.created_at}>{formatDateTime(n.created_at)}</time>
                          {stateText && <span className={stateClass}>{stateText}</span>}
                          <span className="visually-hidden">{n.read_at ? 'Read' : 'Unread'}</span>
                        </span>
                      </span>
                    </button>
                    {!n.read_at && (
                      <button type="button" className="notif-read" onClick={() => markRead(n)}
                        aria-label={`Mark as read: ${KIND_LABEL[n.kind] || n.kind}, ${n.summary}`} title="Mark as read">
                        <Check size={14} aria-hidden="true" />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};

export default NotificationBell;
