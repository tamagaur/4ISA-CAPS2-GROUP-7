import test from 'node:test';
import assert from 'node:assert/strict';
import { canRun, demoStage, planLine, undoSummary, waitingOrders } from './liveDemoModel.js';

const base = (over = {}) => ({
  file: null,
  job: { status: 'idle' },
  state: { open: true, generated_rows: 0, newest_cycle: '2026-03', session: { baseline: { cycle: '2026-03', rows: 109, pieces: 435988 } },
    baseline_plan_decisions: { waiting: 0, decided: 1 }, ...(over.state || {}) },
  ...Object.fromEntries(Object.entries(over).filter(([k]) => k !== 'state')),
});

test('the stage is the one thing to do next', () => {
  assert.equal(demoStage({ state: { open: false } }), 'closed');
  assert.equal(demoStage(base()), 'open');
  assert.equal(demoStage(base({ file: { name: 'a.csv' } })), 'file');
  assert.equal(demoStage(base({ state: { generated_rows: 709 } })), 'loaded');
  assert.equal(demoStage(base({ state: { generated_rows: 709, newest_cycle: '2026-04' } })), 'ran');
  assert.equal(demoStage(base({ job: { status: 'running' } })), 'working');
  assert.equal(demoStage(null), 'unknown');
});

test('Run waits for a file and for every order of the baseline plan to be decided', () => {
  assert.equal(canRun(base()), false);
  assert.equal(canRun(base({ file: { name: 'a.csv' } })), true);
  const waiting = base({ file: { name: 'a.csv' }, state: { baseline_plan_decisions: { waiting: 73, decided: 1 } } });
  assert.equal(waitingOrders(waiting), 73);
  assert.equal(canRun(waiting), false);
  assert.equal(canRun(base({ file: { name: 'a.csv' }, job: { status: 'running' } })), false);
  assert.equal(canRun(base({ state: { generated_rows: 709, newest_cycle: '2026-04' }, file: null })), false);
});

test('plans and the undo result are said in whole pieces', () => {
  assert.equal(planLine('Plan 2026-03', { rows: 109, pieces: 435988 }), 'Plan 2026-03: 109 rows, 435,988 pieces');
  assert.equal(planLine('Plan', null), 'Plan: no plan');
  assert.equal(undoSummary(null), null);
  assert.match(undoSummary({ passed: true, after: [109, 435988] }).text, /109 rows, 435,988 pieces/);
  const failed = undoSummary({ passed: false, failures: ['the pinned figures do not reproduce'] });
  assert.equal(failed.ok, false);
  assert.match(failed.text, /did NOT finish/);
});
