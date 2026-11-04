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
