// Where the monthly batch stands, from GET /batch/status. Pure, so it can be
// tested without a browser. The backend decides what is allowed; this only
// decides what the page shows next.
export function batchStage(status) {
  if (status.job?.status === 'running') return 'running';
  if (status.cycle_state === 'closed') return 'closed';
  if (status.checks?.lp_next) return 'review';
  if (status.checks?.sales_loaded || status.files?.sales) return 'ready';
  return 'needs_data';
}

export function planChange(oldPieces, newPieces) {
  return oldPieces > 0 ? `${(newPieces / oldPieces).toFixed(2)}x` : null;
}

// The calendar factor has no default on purpose: see scripts/run_month.py.
export function canRun(stage, calendarFactor) {
  return stage === 'ready' && (calendarFactor === 'on' || calendarFactor === 'off');
}
