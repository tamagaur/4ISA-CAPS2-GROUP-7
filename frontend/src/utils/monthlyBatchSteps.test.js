import test from 'node:test';
import assert from 'node:assert/strict';
import {
  batchStage, canRun, checklistSummary, CHECK_STATUS, decisionsBlocked, formatWhen, planChange, processingFacts, reorderPath, runHint, WORKFLOW,
} from './monthlyBatchSteps.js';

const checks = (over = {}) => ({
  sales_loaded: false, count_loaded: true, abc_run: false, forecast_next: false, lp_next: false, ...over,
});
const status = (over = {}) => ({ month: '2026-03', checks: checks(), cycle_state: 'open', files: {}, job: { status: 'idle' }, ...over });
const list = (over = {}) => ({
  can_run: true, validated: true, status: 'ready', workflow: 'ready_to_run',
  summary: { passed: 9, failed: 0, warning: 0, not_checked: 0 }, checks: [], decisions: { unresolved: 0, staff_requests: 0 }, ...over,
});

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

test('running needs the backend to allow it, a validation, and the calendar factor stated', () => {
  assert.equal(canRun(list(), null), false);
  assert.equal(canRun(list(), 'off'), true);
  assert.equal(canRun(list(), 'on'), true);
  assert.equal(canRun(list({ can_run: false }), 'on'), false);
  assert.equal(canRun(list({ validated: false }), 'on'), false);
  assert.equal(canRun(null, 'on'), false);
});

test('the hint says what stands in the way of the button', () => {
  assert.match(runHint(null, 'on'), /Reading/);
  assert.match(runHint(list({ status: 'running' }), 'on'), /Wait/);
  assert.match(runHint(list({ validated: false }), 'on'), /validation/);
  assert.match(runHint(list({ can_run: false }), 'on'), /checklist/);
  assert.match(runHint(list(), null), /calendar factor/);
  assert.equal(runHint(list(), 'on'), null);
});

test('the brief\'s eight states and the two around a finished run all have words', () => {
  for (const key of ['not_uploaded', 'ready_for_validation', 'validating', 'action_required', 'ready_to_run', 'processing', 'completed', 'failed', 'awaiting_review', 'closed']) {
    assert.ok(WORKFLOW[key]?.label && WORKFLOW[key].badge && WORKFLOW[key].step, key);
  }
  assert.equal(WORKFLOW.validating.label, 'Validation in progress');
  assert.equal(WORKFLOW.action_required.label, 'Action required');
});

test('every check status has words as well as a colour', () => {
  assert.deepEqual(Object.keys(CHECK_STATUS).sort(), ['failed', 'not_checked', 'passed', 'warning']);
  assert.equal(CHECK_STATUS.not_checked.label, 'Not checked');
});

test('the summary counts come from the backend', () => {
  const one = checklistSummary(list({ workflow: 'action_required', summary: { passed: 8, failed: 1, warning: 0, not_checked: 0 } }));
  assert.equal(one.tone, 'action');
  assert.equal(one.title, 'Action required: 1 check failed');
  const two = checklistSummary(list({ workflow: 'action_required', summary: { passed: 7, failed: 2, warning: 0, not_checked: 0 } }));
  assert.equal(two.title, 'Action required: 2 checks failed');
});

test('nothing is called ready until it has been validated', () => {
  const summary = checklistSummary(list({ validated: false, workflow: 'ready_for_validation' }));
  assert.equal(summary.tone, 'pending');
  assert.equal(checklistSummary(list({ summary: { passed: 8, failed: 0, warning: 0, not_checked: 1 } })).tone, 'pending');
});

test('all passed, with and without warnings', () => {
  assert.equal(checklistSummary(list()).title, 'All checks passed');
  const warned = checklistSummary(list({ summary: { passed: 8, failed: 0, warning: 1, not_checked: 0 } }));
  assert.equal(warned.title, 'All required checks passed');
  assert.match(warned.text, /1 warning first/);
});

test('after the run the checks are not read as failures', () => {
  for (const workflow of ['completed', 'awaiting_review', 'closed']) {
    assert.equal(checklistSummary(list({ workflow, summary: { passed: 8, failed: 1, warning: 0, not_checked: 0 } })).tone, 'done');
  }
});

test('a running step is not read as a failed check', () => {
  const summary = checklistSummary(list({ status: 'running', workflow: 'processing', summary: { passed: 8, failed: 1, warning: 0, not_checked: 0 } }));
  assert.equal(summary.tone, 'pending');
  assert.equal(summary.title, 'A step is running');
});

test('the dialog opens only for decisions people can settle', () => {
  const row = (over) => ({ checks: [{ id: 'decisions_settled', status: 'failed', action_id: 'review_recommendations', ...over }] });
  assert.equal(decisionsBlocked(row({})), true);
  assert.equal(decisionsBlocked(row({ status: 'passed' })), false);
  assert.equal(decisionsBlocked(row({ action_id: null })), false);
  assert.equal(decisionsBlocked({ checks: [] }), false);
  assert.equal(decisionsBlocked(null), false);
});

test('the review link goes to the plan, or to the requests when only they wait', () => {
  assert.equal(reorderPath({ unresolved: 3, staff_requests: 0 }), '/reorder');
  assert.equal(reorderPath({ unresolved: 3, staff_requests: 2 }), '/reorder');
  assert.equal(reorderPath({ unresolved: 0, staff_requests: 2 }), '/reorder?tab=requests');
  assert.equal(reorderPath(null), '/reorder');
});

test('the facts follow the backend\'s state', () => {
  const facts = processingFacts(status({ checks: checks({ sales_loaded: true }) }), list());
  assert.deepEqual(facts, { month: '2026-03', upload: 'Sales in the database', validation: 'Passed', processing: 'Not started', step: '3. Run the month' });
  assert.equal(processingFacts(status(), null).validation, 'Reading');
  assert.equal(processingFacts(status(), null).step, 'Reading');
  assert.equal(processingFacts(status({ files: { sales: { name: 'a.xls' } } }), list({ validated: false, workflow: 'ready_for_validation' })).upload, 'Sales file ready');
  assert.equal(processingFacts(status(), list({ validated: false, workflow: 'not_uploaded' })).upload, 'Not uploaded');
  assert.equal(processingFacts(status(), list({ workflow: 'validating' })).validation, 'In progress');
  assert.equal(processingFacts(status(), list({ workflow: 'action_required', summary: { passed: 8, failed: 1, warning: 0, not_checked: 0 } })).validation, 'Action required');
  assert.equal(processingFacts(status(), list({ summary: { passed: 8, failed: 0, warning: 1, not_checked: 0 } })).validation, 'Passed, with warnings');
  assert.equal(processingFacts(status(), list({ workflow: 'processing' })).processing, 'Running');
  assert.equal(processingFacts(status(), list({ workflow: 'completed' })).processing, 'Completed');
  assert.equal(processingFacts(status(), list({ workflow: 'failed' })).processing, 'Failed');
  assert.equal(processingFacts(status({ job: { status: 'running', kind: 'close' } }), list({ workflow: 'processing' })).processing, 'Closing');
  assert.equal(processingFacts(status({ job: { status: 'running', kind: 'close' } }), list({ workflow: 'processing' })).step, '5. Close the month');
});

test('a time from the backend reads as a time, and nothing invents one', () => {
  assert.match(formatWhen('2026-11-04T09:30:00+00:00'), /2026/);
  assert.equal(formatWhen(null), null);
  assert.equal(formatWhen('not a date'), null);
});
