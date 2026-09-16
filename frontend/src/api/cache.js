// In-memory response cache for read-only GETs.
//
// Every analytics number in this app is batch-computed (ETL, ABC, MA3 and LP
// all run on a schedule, not per request), so a response stays valid for
// minutes. Without this, every page visit re-paid the full round-trip — the
// Dashboard's alone measured 5.4–7.1s against Supabase — even when the user
// had just been on that page with the same date range.
//
// Caches the in-flight promise, not just the result, so two callers asking
// for the same key at once share one network request.

const DEFAULT_TTL_MS = 5 * 60 * 1000;

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

export function cachedRequest(key, fetcher, { ttlMs = DEFAULT_TTL_MS, force = false } = {}) {
  const hit = store.get(key);
  if (!force && hit && hit.expiresAt > Date.now()) {
    return hit.promise.then((value) => {
      markServed(hit);
      return clone(value);
    });
  }

  const entry = { promise: null, value: undefined, hasValue: false, expiresAt: Date.now() + ttlMs, fetchedAt: null };
  entry.promise = fetcher().then(
    (value) => {
      entry.value = value;
      entry.hasValue = true;
      entry.fetchedAt = Date.now();
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

// Synchronous read of an already-resolved, unexpired response, so a page can
// render real data on its very first frame instead of flashing a loading
// state for a request it doesn't need to make.
export function peekCache(key) {
  const hit = store.get(key);
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
