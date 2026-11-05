// What the live demonstration card says, as plain functions of the API's answers, so the wording can be tested without a browser.

export const pieces = (n) => Math.round(Number(n) || 0).toLocaleString('en-US');

// The card's stage: the one thing a person should do next.
export function demoStage(status) {
  const state = status?.state;
  if (!state) return 'unknown';
  if (status.job?.status === 'running') return 'working';
  if (!state.open) return 'closed';
  if (state.generated_rows > 0 && state.newest_cycle && state.session && state.newest_cycle !== state.session.baseline.cycle) return 'ran';
  if (state.generated_rows > 0) return 'loaded';
  if (status.file) return 'file';
  return 'open';
}

// How many of the baseline plan's orders still wait for a person. Run is refused until none does.
export function waitingOrders(status) {
  return status?.state?.baseline_plan_decisions?.waiting ?? 0;
}

export function canRun(status) {
  const stage = demoStage(status);
  return (stage === 'file' || stage === 'open' || stage === 'loaded') && Boolean(status.file || status.state?.generated_rows) && waitingOrders(status) === 0;
}

// Before / now, in the words the Dashboard and Reorder pages use.
export function planLine(label, plan) {
  if (!plan) return `${label}: no plan`;
  return `${label}: ${plan.rows} rows, ${pieces(plan.pieces)} pieces`;
}

export function undoSummary(lastUndo) {
  if (!lastUndo) return null;
  if (!lastUndo.passed) return { ok: false, text: `The last undo did NOT finish: ${(lastUndo.failures || []).join('; ') || 'see the log'}. The snapshot was kept.` };
  const [rows, total] = lastUndo.after || [];
  return { ok: true, text: `Undone and proven: the plan reads ${rows} rows, ${pieces(total)} pieces, every table, view and function equals what it was, and the pinned figures reproduce.` };
}
