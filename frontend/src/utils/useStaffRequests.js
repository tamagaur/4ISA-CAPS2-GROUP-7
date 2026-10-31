// frontend/src/utils/useStaffRequests.js — the Reorder page's staff-request
// list (components/ReorderRequests.jsx StaffRequestsTab), loaded by the page
// itself so the tab can show its count before it is opened.
//
// An admin gets everyone's quantity changes and dismissal requests and the
// stock counts still to be checked; anyone else gets their own requests (the
// server scopes the lists: backend/routers/reorder_approval.py list_changes,
// reorder_requests.py). Every state is loaded once (state=all), so the tab
// badge and the summary cards count from the data whatever filter the tab
// shows; the filtering is client-side (reorderRequests.filterRequests). A server without the tables answers
// 503 approval_not_ready / requests_not_ready: reported as not set up
// (changesReady / dismissalsReady false), never as an error.
import { useCallback, useEffect, useState } from 'react';
import { getDismissalRequests, getQuantityChanges, getStockObservations } from '../api/recommendations';
import { requestCounts, serverTime } from './reorderRequests';

// A server older than the endpoint answers 404 or 405 (seen 2026-10-28 on a
// local server with migration 0068's routes but not 0070's): not set up too.
const isNotReady = (err) => [404, 405, 503].includes(err?.status)
  || err?.code === 'approval_not_ready' || err?.code === 'requests_not_ready';

export function useStaffRequests({ enabled, isAdmin }) {
  const [state, setState] = useState({ status: enabled ? 'loading' : 'off' });
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) {
      setState({ status: 'off' });
      return undefined;
    }
    let cancelled = false;
    setState((prev) => (prev.status === 'ready' ? { ...prev, refreshing: true } : { status: 'loading' }));
    const listState = 'all';
    (async () => {
      let changes = [];
      let changesReady = true;
      try {
        changes = (await getQuantityChanges({ state: listState })).items || [];
      } catch (err) {
        if (!isNotReady(err)) throw err;
        changesReady = false;
      }
      let dismissals = [];
      let dismissalsReady = changesReady;
      if (changesReady) {
        try {
          dismissals = (await getDismissalRequests({ state: listState })).items || [];
        } catch (err) {
          if (!isNotReady(err)) throw err;
          dismissalsReady = false;
        }
      }
      let observations = [];
      if (isAdmin && dismissalsReady) {
        try {
          observations = (await getStockObservations({ state: 'unverified' })).items || [];
        } catch (err) {
          if (!isNotReady(err)) throw err;
        }
      }
      if (cancelled) return;
      const items = [
        ...changes.map((c) => ({
          ...c, kind: 'quantity_change', key: `c${c.change_key}`, at: c.proposed_at, by: c.proposed_by, byName: c.proposed_by_name || null,
          proposed: c.proposed_q_i,
        })),
        ...dismissals.map((d) => ({
          ...d, kind: 'dismissal', key: `d${d.request_key}`, at: d.requested_at, by: d.requested_by, byName: d.requested_by_name || null,
          proposed: 0,
        })),
      ].sort((a, b) => (serverTime(b.at)?.getTime() || 0) - (serverTime(a.at)?.getTime() || 0));
      setState({ status: 'ready', changesReady, dismissalsReady, items, observations });
    })().catch((err) => {
      if (!cancelled) setState({ status: 'error', message: err.message });
    });
    return () => { cancelled = true; };
  }, [enabled, isAdmin, attempt]);

  // For an admin, everyone's requests waiting for a decision; for staff, their own.
  const counts = requestCounts(state.status === 'ready' ? state.items : []);
  return { ...state, counts, pendingCount: counts.pending_approval, reload };
}

