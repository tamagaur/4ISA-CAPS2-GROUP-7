// node --test src/utils (npm test): the Reorder page's comparison of two plan cycles.
import test from 'node:test';
import assert from 'node:assert/strict';
import { compareCycles, planQuantity, previousCycleDate, previousRunCycleDate, previousWindow, productKey, runCycles } from './cycleComparison.js';

const row = (sku, q, extra = {}) => ({
  sku_id: sku, principal: 'unilever', product_name: `Product ${sku}`, planning_cycle_date: '2026-03-01', q_i: q, ...extra,
});

test('products are matched by principal and code, never by name', () => {
  const cur = [row('A', 10, { product_name: 'Renamed' })];
  const prev = [row('A', 10, { product_name: 'Old name' }), row('B', 5, { product_name: 'Renamed' })];
  const out = compareCycles(cur, prev);
  assert.equal(out.unchanged, 1);
  assert.deepEqual(out.added, []);
  assert.deepEqual(out.removed.map((r) => r.sku), ['B']);
  assert.equal(productKey(row('A', 1)), 'unilever|A');
  assert.notEqual(productKey(row('A', 1)), productKey(row('A', 1, { principal: 'delmonte' })));
});

test('new, gone, up and down, with both quantities and the change', () => {
  const cur = [row('NEW', 40), row('UP', 30), row('DOWN', 5), row('SAME', 7)];
  const prev = [row('GONE', 12), row('UP', 10), row('DOWN', 20), row('SAME', 7)];
  const out = compareCycles(cur, prev);
  assert.deepEqual(out.added.map((r) => [r.sku, r.quantity]), [['NEW', 40]]);
  assert.deepEqual(out.removed.map((r) => [r.sku, r.quantity]), [['GONE', 12]]);
  assert.deepEqual(out.increased.map((r) => [r.sku, r.before, r.after, r.change]), [['UP', 10, 30, 20]]);
  assert.deepEqual(out.decreased.map((r) => [r.sku, r.before, r.after, r.change]), [['DOWN', 20, 5, -15]]);
  assert.equal(out.unchanged, 1);
  assert.equal(out.currentCount, 4);
  assert.equal(out.previousCount, 4);
});

test('the plan quantity is the accepted one where a planner changed it, in whole pieces as the table shows', () => {
  assert.equal(planQuantity({ q_i: 100, plan_q_i: 80 }), 80);
  assert.equal(planQuantity({ q_i: 100, plan_q_i: null }), 100);
  assert.equal(planQuantity({ q_i: 10.2 }), 11);
  assert.equal(planQuantity({ q_i: 1782.0000000002 }), 1782);
  const out = compareCycles([row('A', 100, { plan_q_i: 80 })], [row('A', 100)]);
  assert.deepEqual(out.decreased.map((r) => [r.before, r.after]), [[100, 80]]);
  // A change smaller than a piece that the table would show as the same figure is not a change.
  assert.equal(compareCycles([row('A', 10.0000001)], [row('A', 10)]).unchanged, 1);
});

test('a missing quantity is counted apart, never read as 0', () => {
  const out = compareCycles([row('A', null)], [row('A', 5)]);
  assert.equal(out.unknownQuantity, 1);
  assert.deepEqual(out.decreased, []);
  const gone = compareCycles([], [row('X', null), row('Y', 3)]);
  assert.deepEqual(gone.removed.map((r) => r.sku), ['Y', 'X']); // no quantity sorts last
});

test('a code listed twice in a cycle, or a row with no code, is set aside, not guessed', () => {
  const out = compareCycles([row('A', 1), row('A', 2), row('', 3)], [row('A', 5), row('B', 1), row('B', 2)]);
  assert.deepEqual(out.added, []);
  assert.deepEqual(out.removed, []);
  assert.deepEqual(out.increased, []);
  assert.deepEqual(out.decreased, []);
  assert.equal(out.unmatched, 3); // A, B, and the row with no code
});

test('lists run largest first, then by code', () => {
  const out = compareCycles([row('C', 5), row('A', 50), row('B', 5)], []);
  assert.deepEqual(out.added.map((r) => r.sku), ['A', 'B', 'C']);
});

test('the previous cycle is the newest one strictly before the current', () => {
  const rows = [{ planning_cycle_date: '2025-11-01' }, { planning_cycle_date: '2026-02-01' }, { planning_cycle_date: '2026-03-01' }];
  assert.equal(previousCycleDate(rows, '2026-03-01'), '2026-02-01');
  assert.equal(previousCycleDate(rows.slice(2), '2026-03-01'), null);
  assert.equal(previousCycleDate([], '2026-03-01'), null);
});

test('the search window is the 12 months before the cycle, ending the day before it', () => {
  assert.deepEqual(previousWindow('2026-03-01'), { from: '2025-03-01', to: '2026-02-28' });
  assert.deepEqual(previousWindow('2024-03-01'), { from: '2023-03-01', to: '2024-02-29' });
  assert.deepEqual(previousWindow('2026-01-01'), { from: '2025-01-01', to: '2025-12-31' });
  assert.equal(previousWindow(null), null);
  assert.equal(previousWindow('March'), null);
});

// 2026-10-26: only a cycle a stored plan run produced is compared with.
test('a run is known only from lp_model.run with inputs_source run, never from defaults', () => {
  const current = { lp_model: { inputs_source: 'run', run: { planning_cycle_date: '2026-03-01' } } };
  const defaults = { lp_model: { inputs_source: 'defaults', run: null } };
  assert.deepEqual([...runCycles(current, defaults, null, {})], ['2026-03-01']);
  assert.equal(runCycles(defaults).size, 0);
});

test('the previous cycle skips earlier cycles with no stored run', () => {
  const rows = [
    { planning_cycle_date: '2025-11-01' },
    { planning_cycle_date: '2026-01-01' },
    { planning_cycle_date: '2026-02-01' },
  ];
  // Feb 2026 holds leftover rows but no run: walk back to January, which has one.
  assert.equal(previousRunCycleDate(rows, '2026-03-01', new Set(['2026-01-01', '2026-03-01'])), '2026-01-01');
  // No earlier cycle with a run: nothing to compare with (the live case, 2026-10-26).
  assert.equal(previousRunCycleDate(rows, '2026-03-01', new Set(['2026-03-01'])), null);
  assert.equal(previousRunCycleDate(rows, '2026-03-01', undefined), null);
  // The current cycle itself is never its own previous.
  assert.equal(previousRunCycleDate([{ planning_cycle_date: '2026-03-01' }], '2026-03-01', ['2026-03-01']), null);
});
