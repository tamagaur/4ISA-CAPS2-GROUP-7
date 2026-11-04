import test from 'node:test';
import assert from 'node:assert/strict';
import { batchStage, planChange, canRun } from './monthlyBatchSteps.js';

const checks = (over = {}) => ({
  sales_loaded: false, count_loaded: true, abc_run: false, forecast_next: false, lp_next: false, ...over,
});
const status = (over = {}) => ({ checks: checks(), cycle_state: 'open', files: {}, job: { status: 'idle' }, ...over });

test('no sales and no file: the month needs data', () => {
  assert.equal(batchStage(status()), 'needs_data');
});

test('an uploaded sales file means it can run, though nothing is loaded yet', () => {
  assert.equal(batchStage(status({ files: { sales: { name: 'a.xls' } } })), 'ready');
});

test('sales loaded and no plan: ready to run', () => {
  assert.equal(batchStage(status({ checks: checks({ sales_loaded: true }) })), 'ready');
});

test('a written plan waits for review', () => {
  assert.equal(batchStage(status({ checks: checks({ sales_loaded: true, lp_next: true }) })), 'review');
});

test('a closed month is closed, whatever else is true', () => {
  assert.equal(batchStage(status({ cycle_state: 'closed', checks: checks({ lp_next: true }) })), 'closed');
});

test('a running job wins over everything', () => {
  assert.equal(batchStage(status({ cycle_state: 'closed', job: { status: 'running' } })), 'running');
});

test('the plan change is a ratio, and absent when the old plan is empty', () => {
  assert.equal(planChange(100, 250), '2.50x');
  assert.equal(planChange(0, 250), null);
});

test('running needs the calendar factor stated', () => {
  assert.equal(canRun('ready', null), false);
  assert.equal(canRun('ready', 'off'), true);
  assert.equal(canRun('needs_data', 'on'), false);
});
