// Request de-duplication for read-only GETs. NOT a response cache.
//
// It WAS a 5-minute cache: analytics numbers are batch-computed (ETL, ABC,
// forecasting and LP run on a schedule, not per request), so a response was
// treated as valid for minutes to avoid re-paying the Dashboard's 5.4–7.1s
// round-trip on every visit.
//
// Retention removed 2026-09-23, by request: a figure on screen must be the
// figure the database holds at the moment the page was opened, never one up
// to five minutes old. Every mount now refetches.
//
// What survives is the part that was never about staleness: the IN-FLIGHT
// promise is still shared, so two components mounting at once (the Dashboard
// and its card-scoped forecast filter, say) still make ONE request between
// them instead of two. A resolved entry is dropped as soon as its callers
// have it, so nothing is ever served from memory on a later visit.
import { getDataMode } from '../dataMode';

const DEFAULT_TTL_MS = 0;

const store = new Map(); // key -> { promise, value, hasValue, expiresAt, fetchedAt }

// Callers get a copy so a component mutating its response can't corrupt
// what the next visit reads.
const clone = (value) => structuredClone(value);

// "Served" events let the top bar show how old the data on screen is: each
// time a response is handed to a page (fresh or cached), listeners learn
// when that response was really fetched. Notification is deferred because
// peekCache() runs during render, where updating another component's state
// isn't allowed; servedAt is still captured synchronously.
const servedListeners = new Set();
function markServed(entry) {
  const event = { fetchedAt: entry.fetchedAt, servedAt: Date.now() };
  queueMicrotask(() => servedListeners.forEach((listener) => listener(event)));
}

export function subscribeServed(listener) {
  servedListeners.add(listener);
  return () => servedListeners.delete(listener);
}

// A path means different data in preview (src/dataMode.js), so the mode is
// part of the key: a request in flight when the mode flips can't be joined
// by a caller in the other mode. Appended, not prefixed, so
// invalidateCache(prefix) still matches on the path.
const modeKey = (key) => `${key}#${getDataMode()}`;

export function cachedRequest(rawKey, fetcher, { ttlMs = DEFAULT_TTL_MS, force = false } = {}) {
  const key = modeKey(rawKey);
  // Only an UNRESOLVED entry can be joined — that is request de-duplication,
  // not retention. With ttlMs 0 a resolved entry never qualifies, so every
  // mount issues a real request. (hasValue is what separates the two: it is
  // set the moment the response lands.)
  const hit = store.get(key);
  if (!force && hit && !hit.hasValue && hit.expiresAt > Date.now()) {
    return hit.promise.then((value) => {
      markServed(hit);
      return clone(value);
    });
  }

  // expiresAt bounds how long a concurrent caller may join this in-flight
  // request, so a hung fetch can't have newcomers waiting on it forever.
  const entry = { promise: null, value: undefined, hasValue: false, expiresAt: Date.now() + Math.max(ttlMs, 30_000), fetchedAt: null };
  entry.promise = fetcher().then(
    (value) => {
      entry.value = value;
      entry.hasValue = true;
      entry.fetchedAt = Date.now();
      // Drop it once resolved when retention is off, so the next visit
      // refetches instead of reading this response back.
      if (ttlMs <= 0 && store.get(key) === entry) store.delete(key);
      return value;
    },
    (err) => {
      // Never cache a failure — the next visit should retry.
      if (store.get(key) === entry) store.delete(key);
      throw err;
    },
  );
  store.set(key, entry);
  return entry.promise.then((value) => {
    markServed(entry);
    return clone(value);
  });
}

// Synchronous read of an already-resolved response.
//
// Always undefined now that retention is off: a resolved entry is deleted as
// it resolves, so there is nothing to hand back. Kept as a function (rather
// than removed) because callers use it as a "render real data on the first
// frame if we happen to have it" optimisation and must already handle a
// miss — Dashboard.jsx seeds its state from peekDashboardData() and falls
// straight through to its skeleton when that returns undefined. Turning
// retention back on is then a one-line change to DEFAULT_TTL_MS, with no
// call site to revisit.
export function peekCache(key) {
  const hit = store.get(modeKey(key));
  if (!hit || !hit.hasValue || hit.expiresAt <= Date.now()) return undefined;
  markServed(hit);
  return clone(hit.value);
}

// Drop every key starting with `prefix` (or everything, with no prefix).
// Called after any write that changes what a cached GET would return.
export function invalidateCache(prefix) {
  for (const key of store.keys()) {
    if (!prefix || key.startsWith(prefix)) store.delete(key);
  }
}
