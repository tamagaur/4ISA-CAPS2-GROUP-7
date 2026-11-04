// Where the current plan's decisions stand, the same three counts as the batch review screen (scripts/cycle_feedback.py).
// `items` is GET /recommendations?cycle=current with no status filter, whose rows are exactly the plan.
export function decisionCounts(items = []) {
  const counts = { accepted: 0, dismissed: 0, pending: 0 };
  items.forEach((item) => {
    if (item.status in counts) counts[item.status] += 1;
  });
  return counts;
}

export function decisionLine({ accepted, dismissed, pending }) {
  const fmt = (n) => n.toLocaleString('en-US');
  return `${fmt(accepted)} accepted, ${fmt(dismissed)} dismissed, ${fmt(pending)} not decided`;
}

// Run or closed (GET /recommendations plan_state). Only the practice copy sends it (backend/practice_copy.py): elsewhere this is null and nothing shows.
const STATE_WORDS = { run: 'run, not closed', closing: 'closing, not finished', closed: 'closed' };
export function planStateLine(state) {
  if (!state) return null;
  const closedOn = state.state === 'closed' && state.closed_at ? ` on ${String(state.closed_at).slice(0, 10)}` : '';
  const prior = state.prior ? ` ${state.prior.cycle} is ${STATE_WORDS[state.prior.state]}.` : '';
  return `This plan (${state.cycle}) is ${STATE_WORDS[state.state]}${closedOn}.${prior}`;
}
