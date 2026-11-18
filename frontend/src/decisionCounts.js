// Where the current plan's decisions stand. `items` is GET /recommendations?cycle=current with no status filter, whose rows are
// exactly the plan. A pending row that orders nothing (0 pieces) has no Accept or Dismiss button, so it is not "not decided":
// it is counted apart as `noOrder`, the way the Dashboard (`no_order`) and the month-load check (`q_i > 0`) treat it. Before
// 2026-11-18 it was counted as waiting, so after every orderable row was accepted the banner still read "51 not decided".
export function decisionCounts(items = []) {
  const counts = { accepted: 0, dismissed: 0, pending: 0, noOrder: 0 };
  items.forEach((item) => {
    if (item.status === 'pending') {
      const pieces = Number(item.plan_q_i ?? item.q_i);
      if (Number.isFinite(pieces) && pieces > 0) counts.pending += 1;
      else counts.noOrder += 1;
    } else if (item.status in counts) counts[item.status] += 1;
  });
  return counts;
}

export function decisionLine({ accepted, dismissed, pending, noOrder = 0 }) {
  const fmt = (n) => n.toLocaleString('en-US');
  const base = `${fmt(accepted)} accepted, ${fmt(dismissed)} dismissed, ${fmt(pending)} not decided`;
  return noOrder > 0 ? `${base}; ${fmt(noOrder)} order nothing, so need no decision` : base;
}

// Run or closed (GET /recommendations plan_state). Only the practice copy sends it (backend/practice_copy.py): elsewhere this is null and nothing shows.
const STATE_WORDS = { run: 'run, not closed', closing: 'closing, not finished', closed: 'closed' };
export function planStateLine(state) {
  if (!state) return null;
  const closedOn = state.state === 'closed' && state.closed_at ? ` on ${String(state.closed_at).slice(0, 10)}` : '';
  const prior = state.prior ? ` ${state.prior.cycle} is ${STATE_WORDS[state.prior.state]}.` : '';
  return `This plan (${state.cycle}) is ${STATE_WORDS[state.state]}${closedOn}.${prior}`;
}
