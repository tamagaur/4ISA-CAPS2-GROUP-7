import test from 'node:test';
import assert from 'node:assert/strict';
import {
  batchStage, canRun, checklistSummary, CHECK_STATUS, decisionsBlocked, elapsedText, fileRefusals, formatBytes, formatWhen, planChange, processingFacts, reorderPath, runHint, runningStage, runTracker, WORKFLOW, workflowStages,
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
    assert.ok(WORKFLOW[key]?.label && WORKFLOW[key].badge, key);
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
  assert.deepEqual(facts, { month: '2026-03', upload: 'Sales in the database', validation: 'Passed', processing: 'Not started' });
  assert.equal(processingFacts(status(), null).validation, 'Reading');
  assert.equal(processingFacts(status({ files: { sales: { name: 'a.xls' } } }), list({ validated: false, workflow: 'ready_for_validation' })).upload, 'Sales file ready');
  assert.equal(processingFacts(status(), list({ validated: false, workflow: 'not_uploaded' })).upload, 'Not uploaded');
  assert.equal(processingFacts(status(), list({ workflow: 'validating' })).validation, 'In progress');
  assert.equal(processingFacts(status(), list({ workflow: 'action_required', summary: { passed: 8, failed: 1, warning: 0, not_checked: 0 } })).validation, 'Action required');
  assert.equal(processingFacts(status(), list({ summary: { passed: 8, failed: 0, warning: 1, not_checked: 0 } })).validation, 'Passed, with warnings');
  assert.equal(processingFacts(status(), list({ workflow: 'processing' })).processing, 'Running');
  assert.equal(processingFacts(status(), list({ workflow: 'completed' })).processing, 'Completed');
  assert.equal(processingFacts(status(), list({ workflow: 'failed' })).processing, 'Failed');
  assert.equal(processingFacts(status({ job: { status: 'running', kind: 'close' } }), list({ workflow: 'processing' })).processing, 'Closing');
  assert.equal(processingFacts(status({ job: { status: 'running', kind: 'close' } }), list({ workflow: 'processing' })).processing, 'Closing');
});

test('a time from the backend reads as a time, and nothing invents one', () => {
  assert.match(formatWhen('2026-11-04T09:30:00+00:00'), /2026/);
  assert.equal(formatWhen(null), null);
  assert.equal(formatWhen('not a date'), null);
});

const stageStates = (workflow, job) => workflowStages(workflow, job).map((stage) => stage.state);

test('five stages, one for each section, following the backend workflow', () => {
  assert.equal(workflowStages('not_uploaded').length, 5);
  assert.equal(workflowStages('not_uploaded')[4].label, 'Close the month');
  assert.deepEqual(stageStates('not_uploaded'), ['current', 'pending', 'pending', 'pending', 'pending']);
  assert.deepEqual(stageStates('ready_for_validation'), ['done', 'current', 'pending', 'pending', 'pending']);
  assert.deepEqual(stageStates('action_required'), ['done', 'current', 'pending', 'pending', 'pending']);
  assert.deepEqual(stageStates('ready_to_run'), ['done', 'done', 'current', 'pending', 'pending']);
  assert.deepEqual(stageStates('awaiting_review'), ['done', 'done', 'done', 'current', 'pending']);
});

test('only a closed month has every stage done', () => {
  assert.deepEqual(stageStates('closed'), ['done', 'done', 'done', 'done', 'done']);
  assert.equal(workflowStages('closed')[4].detail, 'Closed');
  assert.equal(workflowStages('awaiting_review')[4].detail, 'Not closed');
});

test('a failed run marks the run stage failed, not done', () => {
  assert.deepEqual(stageStates('failed'), ['done', 'done', 'failed', 'pending', 'pending']);
});

test('while the checks are being read no stage is claimed', () => {
  assert.deepEqual(stageStates(undefined), ['pending', 'pending', 'pending', 'pending', 'pending']);
});

test('a running job counts under the section it belongs to', () => {
  // The backend calls all of these "processing".
  assert.deepEqual(stageStates('processing', { status: 'running', kind: 'practice' }), ['current', 'pending', 'pending', 'pending', 'pending']);
  assert.deepEqual(stageStates('processing', { status: 'running', kind: 'plan' }), ['done', 'done', 'current', 'pending', 'pending']);
  assert.deepEqual(stageStates('processing', { status: 'running', kind: 'close' }), ['done', 'done', 'done', 'done', 'current']);
  assert.equal(workflowStages('processing', { status: 'running', kind: 'close' })[4].detail, 'Closing');
});

test('only a stage with a job running is busy', () => {
  assert.equal(workflowStages('processing', { status: 'running', kind: 'plan' })[2].busy, true);
  assert.equal(workflowStages('ready_to_run', { status: 'idle' })[2].busy, false);
  assert.equal(workflowStages('failed', { status: 'failed', kind: 'plan' })[2].busy, false);
});

test('each stage carries its own state in words', () => {
  const facts = { upload: 'Sales file ready', validation: 'Passed', processing: 'Not started' };
  const details = workflowStages('ready_to_run', { status: 'idle' }, facts).map((stage) => stage.detail);
  assert.deepEqual(details, ['Sales file ready', 'Passed', 'Not started', 'No plan yet', 'Not closed']);
  assert.equal(workflowStages('awaiting_review', null, facts)[3].detail, 'Plan ready');
});

test('before validation has run, that is the headline, whatever else is failing', () => {
  const summary = checklistSummary(list({ validated: false, workflow: 'not_uploaded', summary: { passed: 7, failed: 2, warning: 0, not_checked: 0 } }));
  assert.equal(summary.title, 'Not validated yet');
  assert.equal(summary.tone, 'pending');
  assert.match(summary.text, /2 checks already need attention/);
  assert.match(checklistSummary(list({ validated: false, summary: { passed: 8, failed: 1, warning: 0, not_checked: 0 } })).text, /1 check already needs attention/);
  assert.doesNotMatch(checklistSummary(list({ validated: false })).text, /attention/);
});

test('a run in progress does not read as a failed validation', () => {
  // While the run is going, the backend's "no other job running" check fails because of it.
  const busy = list({ workflow: 'processing', summary: { passed: 8, failed: 1, warning: 0, not_checked: 0 } });
  assert.equal(processingFacts(status({ job: { status: 'running', kind: 'plan' } }), busy).validation, 'Passed');
  assert.equal(processingFacts(status({ job: { status: 'idle' } }), list({ workflow: 'action_required', summary: { passed: 8, failed: 1, warning: 0, not_checked: 0 } })).validation, 'Action required');
});

test('a closed month: the run stage says what the run did, the close stage says closed', () => {
  const facts = processingFacts(status({ cycle_state: 'closed' }), list({ workflow: 'closed' }));
  assert.equal(facts.processing, 'Plan written');
  const details = workflowStages('closed', null, facts).map((stage) => stage.detail);
  assert.equal(details[2], 'Plan written');
  assert.equal(details[4], 'Closed');
});

test('after validation the failures are the headline', () => {
  const summary = checklistSummary(list({ validated: true, summary: { passed: 7, failed: 2, warning: 0, not_checked: 0 } }));
  assert.equal(summary.title, 'Action required: 2 checks failed');
});

const progress = (done = []) => ['sales_loaded', 'count_loaded', 'abc_run', 'forecast_next', 'lp_next'].map((id) => ({ id, name: id, done: done.includes(id) }));
const tracked = (over = {}, job = null) => Object.fromEntries(
  runTracker(list({ progress: progress(), ...over }), job).map((node) => [node.id, node.state]),
);

test('validation is a gate, not a stage of the run', () => {
  const nodes = runTracker(list({ progress: progress(), validated: false, can_run: false }), null);
  assert.equal(nodes.length, 5);
  assert.ok(nodes.every((node) => node.id !== 'validation'));
  assert.equal(runHint(list({ validated: false }), null), 'Run validation first.');
});

test('the tracker claims nothing the backend has not reported', () => {
  assert.deepEqual(runTracker(null, null), []);
  assert.deepEqual(tracked(), {
    sales_loaded: 'pending', count_loaded: 'pending', abc_run: 'pending', forecast_next: 'pending', lp_next: 'pending',
  });
  assert.equal(tracked({ progress: progress(['sales_loaded', 'count_loaded']) }).count_loaded, 'done');
});

test('a run in progress: finished steps done, the current one active, the rest pending', () => {
  const job = { kind: 'plan', status: 'running', steps: [{ stage: 'load', state: 'done' }, { stage: 'abc', state: 'done' }, { stage: 'forecast', state: 'running' }] };
  assert.deepEqual(tracked({ progress: progress(['count_loaded']) }, job), {
    sales_loaded: 'done', count_loaded: 'done', abc_run: 'done', forecast_next: 'active', lp_next: 'pending',
  });
});

test('a finished load step says nothing about the stock count', () => {
  const job = { kind: 'plan', status: 'running', steps: [{ stage: 'load', state: 'done' }, { stage: 'abc', state: 'running' }] };
  assert.equal(tracked({}, job).count_loaded, 'pending');
});

test('a stopped stage shows as failed, and never as done', () => {
  const job = { kind: 'plan', status: 'failed', failed_stage: 'forecast', steps: [{ stage: 'load', state: 'skipped' }, { stage: 'abc', state: 'done' }, { stage: 'forecast', state: 'stopped' }] };
  const nodes = runTracker(list({ progress: progress(['sales_loaded', 'count_loaded', 'abc_run']) }), job);
  assert.deepEqual(nodes.find((n) => n.id === 'forecast_next'), { id: 'forecast_next', name: 'forecast_next', state: 'failed', note: 'Stopped' });
  assert.equal(nodes.find((n) => n.id === 'lp_next').state, 'pending');
});

test('a failed load is blamed on one node, the first not done', () => {
  const job = { kind: 'plan', status: 'failed', failed_stage: 'load', steps: [{ stage: 'load', state: 'stopped' }] };
  const nodes = tracked({}, job);
  assert.equal(nodes.sales_loaded, 'failed');
  assert.equal(nodes.count_loaded, 'pending');
  assert.equal(tracked({ progress: progress(['sales_loaded']) }, job).count_loaded, 'failed');
});

test('the running stage is named only while a job runs', () => {
  const steps = [{ stage: 'abc', label: 'ABC classification', state: 'done' }, { stage: 'forecast', label: 'Forecast', state: 'running' }];
  assert.equal(runningStage({ status: 'running', steps }), 'Forecast');
  assert.equal(runningStage({ status: 'failed', steps }), null);
  assert.equal(runningStage({ status: 'running', steps: [] }), null);
  assert.equal(runningStage(null), null);
});

test('elapsed time reads from the start time and makes up nothing', () => {
  const start = '2026-11-04T10:00:00Z';
  const at = (seconds) => Date.parse(start) + seconds * 1000;
  assert.equal(elapsedText(start, at(45)), '45 s');
  assert.equal(elapsedText(start, at(185)), '3 min 05 s');
  assert.equal(elapsedText(null, at(5)), null);
  assert.equal(elapsedText('not a date', at(5)), null);
  assert.equal(elapsedText(start, at(-5)), null);
});

test('a file size in plain units; no size stays absent', () => {
  assert.equal(formatBytes(512), '512 bytes');
  assert.equal(formatBytes(2048), '2 KB');
  assert.equal(formatBytes(12345678), '11.8 MB');
  assert.equal(formatBytes(undefined), null);
});

test('a refusal lands on the slot it belongs to; a warning is not a refusal', () => {
  const details = [
    { table: 'Sales per product', severity: 'failed', reason: 'layout' },
    { table: 'Stock count', severity: 'warning', reason: 'unusual' },
  ];
  const checklist = list({ checks: [{ id: 'files_valid', status: 'failed', details }] });
  assert.deepEqual(fileRefusals(checklist, 'Sales per product').map((d) => d.reason), ['layout']);
  assert.deepEqual(fileRefusals(checklist, 'Stock count'), []);
  assert.deepEqual(fileRefusals(list({ checks: [{ id: 'files_valid', status: 'warning', details }] }), 'Sales per product'), []);
  assert.deepEqual(fileRefusals(null, 'Stock count'), []);
});

// ---- loaded months (live mode)
import { durationText, loadedStateWord, monthName, removedWith } from './monthlyBatchSteps.js';

test('a month is named in words, and anything else stays as it came', () => {
  assert.equal(monthName('2026-03'), 'March 2026');
  assert.equal(monthName('2026-12-01'), 'December 2026');
  assert.equal(monthName('soon'), 'soon');
  assert.equal(monthName(null), '');
});

test('how long a job took comes from its own start and end, and is absent when either is', () => {
  assert.equal(durationText('2026-11-06T10:00:00Z', '2026-11-06T10:02:05Z'), '2 min 05 s');
  assert.equal(durationText('2026-11-06T10:00:00Z', '2026-11-06T10:00:36Z'), '36 s');
  assert.equal(durationText('2026-11-06T10:00:00Z', null), null);
  assert.equal(durationText('2026-11-06T10:05:00Z', '2026-11-06T10:00:00Z'), null);
});

test('rolling a month back also removes every month loaded after it', () => {
  const loaded = [{ month: '2026-03' }, { month: '2026-04' }];
  assert.deepEqual(removedWith(loaded, '2026-03'), ['2026-04']);
  assert.deepEqual(removedWith(loaded, '2026-04'), []);
  assert.deepEqual(removedWith(undefined, '2026-03'), []);
});

test('a loaded month states its state in words', () => {
  assert.equal(loadedStateWord('loaded'), 'Loaded');
  assert.equal(loadedStateWord('taken'), 'Started, not finished');
  assert.equal(loadedStateWord('failed'), 'Did not finish');
  assert.equal(loadedStateWord('unreadable'), 'Unreadable');
});
