import React from 'react';
import { AlertTriangle, RotateCw } from 'lucide-react';
import EmptyState from './EmptyState';

// A request that failed, said in plain words, with Try again (2026-10-16).
// An empty answer is EmptyState, not this.

// Why it failed, for a person: no codes, no stack traces. `err` is what the
// api/*.js call threw: a TypeError when the server never answered (fetch's
// own failure), else an Error carrying the response's `status`.
export function describeLoadError(err) {
  if (err instanceof TypeError) {
    return "The server didn't answer. It may be starting up (on the live site this can take up to a minute "
      + 'after a quiet period), or your internet connection may be down.';
  }
  const status = err?.status;
  if (status === 403) return "Your account doesn't have access to this data. Ask an admin.";
  if (status === 404) return "This data couldn't be found. It may have been removed or renamed.";
  if (status >= 500) return 'The server ran into a problem while preparing this data.';
  return err?.message || 'Something went wrong while loading.';
}

const LoadError = ({ what, message, onRetry, retrying = false }) => (
  <EmptyState
    tone="error"
    role="alert"
    icon={AlertTriangle}
    title={`Couldn't load ${what}`}
    actions={onRetry && (
      <button type="button" className="btn btn-primary" onClick={onRetry} disabled={retrying}>
        <RotateCw size={14} aria-hidden="true" className={retrying ? 'empty-state-spin' : undefined} />
        {retrying ? 'Trying again…' : 'Try again'}
      </button>
    )}
  >
    <p>{message}</p>
    <p>If it keeps happening, tell the admin which page you were on.</p>
  </EmptyState>
);

export default LoadError;
