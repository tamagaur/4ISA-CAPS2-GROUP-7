import { apiFetch } from '../auth';
import { cachedRequest, invalidateCache } from './cache';
import { appendPrincipal } from '../principals';

// Unilever-only (2026-09): no more principal param — the backend always
// scopes to Unilever now. from/to (2026-09): the shared date-range
// picker's applied start/end, 'YYYY-MM-DD' — filters on planning_cycle_date.
// Both must be given together or neither is used, matching every other
// call site of the shared picker (see backend/routers/recommendations.py).
// cycle (optional): 'current' (the server's default, the plan on screen) or
// 'all' (every stored cycle, newest first; with from/to, only those months).
// The Reorder page's "Changes since the previous plan" reads an earlier
// cycle this way (backend/routers/recommendations.py get_recommendations).
export function getRecommendations({ status, from, to, principal, cycle, includeNotPlanned } = {}) {
  const query = new URLSearchParams();
  if (status) query.append('status', status);
  if (cycle === 'current' || cycle === 'all') query.append('cycle', cycle);
  appendPrincipal(query, principal);
  if (from && to) {
    query.append('from', from);
    query.append('to', to);
  }
  if (includeNotPlanned) query.append('include_not_planned', 'true');
  const path = `/recommendations?${query.toString()}`;

  return cachedRequest(path, async () => {
    const res = await apiFetch(path);
    if (!res.ok) {
      throw new Error('Failed to fetch reorder recommendations');
    }
    return res.json();
  });
}

// `reason` (optional, at most 500 characters) is why the decision was made;
// the server records it in the decision's Audit Log entry. Left out when
// empty. `reviewed` confirms a person checked a row flagged for review
// (needs_review); the server refuses to accept a flagged row without it, so
// only a single row's confirm dialog sends it — never bulk accept.
// `stockObservation` (dismissals only, 2026-10-28): a stock count the person
// says they made, {quantity, unit, counted_at?, location?, notes?}. The
// server keeps it as an observation for an admin to check; it never changes
// stock on hand or the plan.
export async function decideRecommendation(recommendationKey, status, reason, { reviewed = false, stockObservation = null } = {}) {
  const body = { status };
  const trimmedReason = reason?.trim();
  if (trimmedReason) body.reason = trimmedReason;
  if (reviewed) body.reviewed = true;
  if (stockObservation && status === 'dismissed') body.stock_observation = stockObservation;
  const res = await apiFetch(`/recommendations/${recommendationKey}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    // The server's own sentence when it sent one: already decided, from a
    // superseded cycle, a reason required (backend/routers/recommendations.py
    // refusal_for and the PATCH checks). A fixed "Failed to update" used to
    // replace every one of them (audit FE-8). A validation error's detail is a
    // list, not a sentence, and a body that isn't JSON has none: both keep
    // the fixed text.
    // Since 2026-10-28 requestError (below) does this, adds the code (e.g.
    // 409 while a staff request is open on the row) for a caller that
    // branches on it, and reads a validation list as its messages.
    throw await requestError(res, 'Failed to update recommendation');
  }
  // An accepted/dismissed row changes this page's list AND the Dashboard's
  // reorder preview counts, so drop everything rather than guess which
  // cached responses it touched.
  invalidateCache();
  return res.json();
}

// ── Staff requests and admin approval (2026-10-28) ───────────────────────────
// backend/routers/reorder_approval.py (quantity changes, migration 0068) and
// reorder_requests.py (dismissal requests, stock counts, open requests and a
// row's history, migration 0070); docs/REORDER_APPROVAL_API.md. Quantities
// are pieces throughout. None of these reads go through cachedRequest: a
// queue an admin is working through is read fresh every time.

// A refused request, with what the server said so the page can branch on it:
// `status` (HTTP), `code` (e.g. 'not_whole_cases', 'recommendation_changed',
// 'approval_not_ready'), and `extra`, the error's other fields
// (nearest_below / nearest_above / pack_size for not_whole_cases).
export class RequestError extends Error {
  constructor(message, { status, code = null, extra = {} } = {}) {
    super(message);
    this.name = 'RequestError';
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

// The server's own sentence when it sent one. A validation error (422 from
// FastAPI) has a list as `detail`: its messages are joined instead, less the
// "Value error, " prefix pydantic puts on them. No JSON body: `fallback`.
async function requestError(res, fallback) {
  const body = await res.json().catch(() => null);
  let message = fallback;
  if (typeof body?.detail === 'string' && body.detail) {
    message = body.detail;
  } else if (Array.isArray(body?.detail) && body.detail.length) {
    const parts = body.detail.map((d) => String(d?.msg || '').replace(/^Value error, /, '')).filter(Boolean);
    if (parts.length) message = parts.join('; ');
  }
  const { detail: _detail, code = null, ...extra } = body && typeof body === 'object' ? body : {};
  return new RequestError(message, { status: res.status, code, extra });
}

async function readJson(path, fallback) {
  const res = await apiFetch(path);
  if (!res.ok) throw await requestError(res, fallback);
  return res.json();
}

// A write: POST with a JSON body. Each can change a row's status, the plan
// total and the Dashboard's reorder counts, so the in-flight cache is
// dropped afterwards, as decideRecommendation does.
async function postJson(path, body, fallback) {
  const res = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw await requestError(res, fallback);
  invalidateCache();
  return res.json();
}

const listQuery = (params) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v != null && v !== '') query.append(k, String(v));
  });
  const s = query.toString();
  return s ? `?${s}` : '';
};

// Whether the caller's quantity changes apply at once (an admin, or a grant)
// or wait for an admin: {can_apply_directly, reason, approval_ready}.
export function getDirectApplyStatus() {
  return readJson('/recommendations/direct-apply-grants/me', 'Failed to check how quantity changes apply');
}

// A different quantity for one row. 202 {outcome:'held', change} when it
// waits for an admin; 200 {outcome:'applied', item} when it applied at once.
// `reason` is required. Send `stockObservation` only when the change will be
// held: the server refuses one (400 observation_needs_request) otherwise.
export function requestQuantityChange(recommendationKey, { quantity, reason, reviewed = false, stockObservation = null }) {
  const body = { quantity, reason: reason.trim() };
  if (reviewed) body.reviewed = true;
  if (stockObservation) body.stock_observation = stockObservation;
  return postJson(`/recommendations/${recommendationKey}/quantity-change`, body, 'Failed to send the quantity change');
}

// state: pending_approval | approved | rejected | all. An admin gets every
// change; anyone else only their own. Newest first.
export function getQuantityChanges({ state = 'pending_approval', recommendationKey } = {}) {
  return readJson(`/recommendations/changes${listQuery({ state, recommendation_key: recommendationKey })}`,
    'Failed to load quantity changes');
}

export function approveQuantityChange(changeKey, note) {
  return postJson(`/recommendations/changes/${changeKey}/approve`, note?.trim() ? { note: note.trim() } : {},
    'Failed to approve the change');
}

export function rejectQuantityChange(changeKey, reason) {
  return postJson(`/recommendations/changes/${changeKey}/reject`, { reason: reason.trim() }, 'Failed to reject the change');
}

// Ask an admin to dismiss a row (lp.propose; an admin dismisses directly and
// gets 400 use_direct_dismissal). The row stays pending until it is decided.
export function requestDismissal(recommendationKey, { reason, stockObservation = null }) {
  const body = { reason: reason.trim() };
  if (stockObservation) body.stock_observation = stockObservation;
  return postJson(`/recommendations/${recommendationKey}/dismissal-request`, body, 'Failed to send the dismissal request');
}

export function getDismissalRequests({ state = 'pending_approval', recommendationKey } = {}) {
  return readJson(`/recommendations/dismissal-requests${listQuery({ state, recommendation_key: recommendationKey })}`,
    'Failed to load dismissal requests');
}

export function approveDismissalRequest(requestKey, note) {
  return postJson(`/recommendations/dismissal-requests/${requestKey}/approve`, note?.trim() ? { note: note.trim() } : {},
    'Failed to approve the dismissal');
}

export function rejectDismissalRequest(requestKey, reason) {
  return postJson(`/recommendations/dismissal-requests/${requestKey}/reject`, { reason: reason.trim() },
    'Failed to reject the dismissal request');
}

// Stock counts people reported with a request or a dismissal. state:
// unverified | verified | rejected | all.
export function getStockObservations({ state = 'unverified', recommendationKey } = {}) {
  return readJson(`/recommendations/stock-observations${listQuery({ state, recommendation_key: recommendationKey })}`,
    'Failed to load stock counts');
}

// An admin records that they checked a count (a note is required to reject
// it). This records the check only: stock on hand and the plan are unchanged.
export function verifyStockObservation(observationKey, { verified, note }) {
  const body = { verified: Boolean(verified) };
  if (note?.trim()) body.note = note.trim();
  return postJson(`/recommendations/stock-observations/${observationKey}/verify`, body, 'Failed to record the check');
}

// Every request waiting for an admin, for any viewer of the table (lp.view):
// {ready, items:[{kind, key, recommendation_key, recommended_q_i,
// proposed_q_i, requested_at, mine, requested_by}]}.
export function getOpenRequests() {
  return readJson('/recommendations/open-requests', 'Failed to load open requests');
}

// One recommendation's life, oldest first (lp.decide or lp.propose).
export function getRecommendationHistory(recommendationKey) {
  return readJson(`/recommendations/${recommendationKey}/history`, 'Failed to load the history');
}
