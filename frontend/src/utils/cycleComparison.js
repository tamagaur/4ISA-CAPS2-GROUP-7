// What changed between two order-plan cycles (the Reorder page's "Changes since
// the previous plan", 2026-10-24). Pure: GET /recommendations rows in, four lists out.
//
// Products are matched by principal + sku_id (the product code), never by name:
// recommendation_key is one row of one cycle, so it never matches across cycles,
// and the response carries no product_key. A code that appears twice in one cycle
// can't be matched to one row, so it is set aside and counted, never guessed.
//
// The quantity compared is the one the page's plan total uses: plan_q_i (the
// quantity a planner accepted instead, where one did), else q_i, in whole pieces
// rounded up exactly as the table shows them (formatNumber.wholeUnits). A row with
// no quantity is counted apart, never read as 0.
import { wholeUnits } from './formatNumber.js';

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})/;

export const productKey = (row) => (row?.sku_id ? `${row.principal}|${row.sku_id}` : null);

export const planQuantity = (row) => wholeUnits(row?.plan_q_i ?? row?.q_i);

// The window searched for the previous cycle: the 12 months before `cycle`
// ('YYYY-MM-DD'), as GET /recommendations' from/to (both inclusive, on
// planning_cycle_date). null for a date it can't read.
export function previousWindow(cycle, months = 12) {
  const m = DATE_ONLY.exec(String(cycle || ''));
  if (!m) return null;
  const start = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1 - months, 1));
  const end = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]) - 1));
  const iso = (d) => d.toISOString().slice(0, 10);
  return { from: iso(start), to: iso(end) };
}

// The newest cycle strictly before `cycle` among `rows`, or null.
export function previousCycleDate(rows, cycle) {
  const before = (rows || [])
    .map((r) => String(r.planning_cycle_date || '').slice(0, 10))
    .filter((d) => d && (!cycle || d < String(cycle).slice(0, 10)));
  return before.length ? before.sort().at(-1) : null;
}

// The cycles a stored plan run (lp_run) is known to be behind, from GET
// /recommendations responses: lp_model.run.planning_cycle_date where
// inputs_source is 'run'. A response without one (inputs_source 'defaults',
// run null) names none. 2026-10-26.
export function runCycles(...responses) {
  const out = new Set();
  responses.forEach((res) => {
    const run = res?.lp_model?.inputs_source === 'run' ? res.lp_model.run : null;
    const d = run?.planning_cycle_date ? String(run.planning_cycle_date).slice(0, 10) : '';
    if (DATE_ONLY.test(d)) out.add(d);
  });
  return out;
}

// The cycle to compare with (2026-10-26): the newest earlier cycle among
// `rows` that a stored plan run produced (its date in `withRun`), or null.
// A cycle with rows but no run (live: 2025-03..2026-02 hold 2-15 leftover
// rows each from the retired planner, lp_run_key null) is skipped, never
// compared with, so its few rows can't read as "products dropped".
export function previousRunCycleDate(rows, cycle, withRun) {
  const runs = withRun instanceof Set ? withRun : new Set(withRun || []);
  return previousCycleDate((rows || []).filter((r) => runs.has(String(r.planning_cycle_date || '').slice(0, 10))), cycle);
}

// One cycle's rows by product key; codes seen twice, and rows with no code, apart.
function index(rows) {
  const byKey = new Map();
  const duplicated = new Set();
  let noCode = 0;
  (rows || []).forEach((row) => {
    const key = productKey(row);
    if (!key) {
      noCode += 1;
      return;
    }
    if (byKey.has(key)) duplicated.add(key);
    else byKey.set(key, row);
  });
  duplicated.forEach((key) => byKey.delete(key));
  return { byKey, duplicated, noCode };
}

const entry = (key, row) => ({
  key,
  sku: row.sku_id,
  product: row.product_name || null,
  principal: row.principal,
});

// currentRows / previousRows: GET /recommendations items of one cycle each.
// Returns { added, removed, increased, decreased, unchanged, unknownQuantity,
// unmatched, currentCount, previousCount }, each list largest quantity (or
// change) first, then by code so the order is stable.
export function compareCycles(currentRows, previousRows) {
  const cur = index(currentRows);
  const prev = index(previousRows);
  const added = [];
  const removed = [];
  const increased = [];
  const decreased = [];
  let unchanged = 0;
  let unknownQuantity = 0;

  cur.byKey.forEach((row, key) => {
    if (prev.duplicated.has(key)) return; // can't say which earlier row it was
    const after = planQuantity(row);
    const earlier = prev.byKey.get(key);
    if (!earlier) {
      added.push({ ...entry(key, row), quantity: after });
      return;
    }
    const before = planQuantity(earlier);
    if (before == null || after == null) {
      unknownQuantity += 1;
    } else if (after > before) {
      increased.push({ ...entry(key, row), before, after, change: after - before });
    } else if (after < before) {
      decreased.push({ ...entry(key, row), before, after, change: after - before });
    } else {
      unchanged += 1;
    }
  });
  prev.byKey.forEach((row, key) => {
    if (cur.byKey.has(key) || cur.duplicated.has(key)) return;
    removed.push({ ...entry(key, row), quantity: planQuantity(row) });
  });

  // A row with no quantity goes last, never ranked as if it were 0.
  const size = (v) => (v == null ? -1 : Math.abs(v));
  const bySize = (field) => (a, b) => size(b[field]) - size(a[field]) || (a.key < b.key ? -1 : 1);
  added.sort(bySize('quantity'));
  removed.sort(bySize('quantity'));
  increased.sort(bySize('change'));
  decreased.sort(bySize('change'));

  const unmatchedKeys = new Set([...cur.duplicated, ...prev.duplicated]);
  return {
    added,
    removed,
    increased,
    decreased,
    unchanged,
    unknownQuantity,
    // Rows that could not be matched at all: a code listed twice in a cycle, or no code.
    unmatched: unmatchedKeys.size + cur.noCode + prev.noCode,
    currentCount: (currentRows || []).length,
    previousCount: (previousRows || []).length,
  };
}
