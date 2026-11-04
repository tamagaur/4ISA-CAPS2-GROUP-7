// Where the monthly batch stands, from GET /batch/status and GET /batch/checklist.
// Pure, so it can be tested without a browser. The backend decides what is
// allowed; this only decides what the page shows next, and works out no check.
export function batchStage(status) {
  if (status.job?.status === 'running') return 'running';
  if (status.cycle_state === 'closed') return 'closed';
  if (status.checks?.lp_next) return 'review';
  if (status.checks?.sales_loaded || status.files?.sales) return 'ready';
  return 'needs_data';
}

export function planChange(oldPieces, newPieces) {
  return oldPieces > 0 ? `${(newPieces / oldPieces).toFixed(2)}x` : null;
}

// The button follows the backend's own verdict, and POST /batch/run asks every
// check again anyway. The calendar factor has no default on purpose: see
// scripts/run_month.py.
export function canRun(checklist, calendarFactor) {
  return Boolean(checklist?.can_run && checklist?.validated) && (calendarFactor === 'on' || calendarFactor === 'off');
}

// Why the button is not available, in a few words. Null when it is.
export function runHint(checklist, calendarFactor) {
  if (!checklist) return 'Reading the checks.';
  if (checklist.status === 'running') return 'Wait for the step that is running.';
  if (!checklist.validated) return 'Run validation first.';
  if (!checklist.can_run) return 'Resolve the checklist first.';
  if (calendarFactor !== 'on' && calendarFactor !== 'off') return 'Choose the calendar factor.';
  return null;
}

// The eight states of the month, plus the two either side of a finished run.
export const WORKFLOW = {
  not_uploaded: { label: 'Not uploaded', badge: 'badge-neutral' },
  ready_for_validation: { label: 'Ready for validation', badge: 'badge-info' },
  validating: { label: 'Validation in progress', badge: 'badge-info' },
  action_required: { label: 'Action required', badge: 'badge-warning' },
  ready_to_run: { label: 'Ready to run', badge: 'badge-success' },
  processing: { label: 'Processing', badge: 'badge-info' },
  completed: { label: 'Completed', badge: 'badge-success' },
  awaiting_review: { label: 'Plan ready for review', badge: 'badge-info' },
  failed: { label: 'Failed', badge: 'badge-critical' },
  closed: { label: 'Closed', badge: 'badge-neutral' },
};

// Status is said in words and shown as an icon, never by colour alone.
export const CHECK_STATUS = {
  passed: { label: 'Passed', badge: 'badge-success' },
  failed: { label: 'Failed', badge: 'badge-critical' },
  warning: { label: 'Warning', badge: 'badge-warning' },
  not_checked: { label: 'Not checked', badge: 'badge-neutral' },
};

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

// The line above the checklist. Every count is the backend's.
export function checklistSummary(checklist) {
  if (!checklist) return null;
  const { failed, warning, not_checked: notChecked } = checklist.summary;
  if (checklist.status === 'running') {
    return { tone: 'pending', title: 'A step is running', text: 'The checks are read again when it finishes.' };
  }
  if (['completed', 'awaiting_review', 'closed'].includes(checklist.workflow)) {
    return { tone: 'done', title: 'This month has been run', text: 'These checks applied before the run.' };
  }
  if (!checklist.validated) {
    const seen = failed > 0 ? ` ${plural(failed, 'check')} already need${failed === 1 ? 's' : ''} attention.` : '';
    return { tone: 'pending', title: 'Not validated yet', text: `Run validation to check this month against the latest decisions and files.${seen}` };
  }
  if (failed > 0) {
    return { tone: 'action', title: `Action required: ${plural(failed, 'check')} failed`, text: 'Resolve the issues below before running the monthly data.' };
  }
  if (notChecked > 0) {
    return { tone: 'pending', title: 'Not validated yet', text: 'Run validation to check this month against the latest decisions and files.' };
  }
  if (warning > 0) {
    return { tone: 'ok', title: 'All required checks passed', text: `Monthly data is ready for processing. Read the ${plural(warning, 'warning')} first.` };
  }
  return { tone: 'ok', title: 'All checks passed', text: 'Monthly data is ready for processing.' };
}

// The decisions check is what opens the Pending Reorder Decisions dialog.
export function decisionsBlocked(checklist) {
  const check = checklist?.checks?.find((c) => c.id === 'decisions_settled');
  return check?.status === 'failed' && check.action_id === 'review_recommendations';
}

// The plan's rows when any wait for a decision, the requests tab when only
// staff requests do. The Reorder page has no other filter for this.
export function reorderPath(decisions) {
  return decisions?.unresolved > 0 || !(decisions?.staff_requests > 0) ? '/reorder' : '/reorder?tab=requests';
}

// Where each stage stands, in words: the line under its name in the stage bar.
export function processingFacts(status, checklist) {
  const job = status.job || {};
  const workflow = checklist?.workflow;
  let upload = 'Not uploaded';
  if (status.checks?.sales_loaded) upload = 'Sales in the database';
  else if (status.files?.sales) upload = 'Sales file ready';

  let validation = 'Reading';
  if (checklist) {
    const { failed, warning, not_checked: notChecked } = checklist.summary;
    if (workflow === 'validating') validation = 'In progress';
    // The route only starts a run once every check has passed. While it runs, "no
    // other job running" fails because of that very run, which says nothing here.
    else if (job.status === 'running' && job.kind === 'plan') validation = 'Passed';
    else if (['completed', 'awaiting_review', 'closed'].includes(workflow)) validation = 'Not needed now';
    else if (!checklist.validated) validation = 'Not run';
    else if (failed > 0 || notChecked > 0) validation = 'Action required';
    else validation = warning > 0 ? 'Passed, with warnings' : 'Passed';
  }

  let processing = 'Not started';
  if (job.status === 'running' && job.kind === 'close') processing = 'Closing';
  else if (job.status === 'running' && job.kind === 'practice') processing = 'Generating practice sales';
  else if (workflow === 'processing') processing = 'Running';
  else if (workflow === 'completed') processing = 'Completed';
  else if (workflow === 'failed') processing = 'Failed';
  else if (workflow === 'awaiting_review') processing = 'Plan written';
  // The month is closed, and the close has its own stage. The run's part was the plan.
  else if (workflow === 'closed') processing = 'Plan written';

  return {
    month: status.month,
    upload,
    validation,
    processing,
  };
}

// The five stages across the top, one for each section below, each with its own
// state in words. Where the month stands is the backend's `workflow`; the job only
// says which section a running job belongs to, because the backend calls every
// running job other than validation "processing".
const WORKFLOW_STAGES = ['Upload monthly data', 'Validate', 'Run the month', 'Review the new plan', 'Close the month'];
const STAGE_AT = {
  not_uploaded: 0, ready_for_validation: 1, validating: 1, action_required: 1, ready_to_run: 2, processing: 2, failed: 2, completed: 3, awaiting_review: 3, closed: 5,
};

function reviewWord(workflow) {
  if (workflow === 'closed') return 'Done';
  return workflow === 'completed' || workflow === 'awaiting_review' ? 'Plan ready' : 'No plan yet';
}

export function workflowStages(workflow, job, facts = {}) {
  const runningKind = job?.status === 'running' ? job.kind : null;
  const at = { practice: 0, close: 4 }[runningKind] ?? STAGE_AT[workflow];
  const closing = runningKind === 'close' ? 'Closing' : 'Not closed';
  const details = [facts.upload, facts.validation, facts.processing, reviewWord(workflow), workflow === 'closed' ? 'Closed' : closing];
  return WORKFLOW_STAGES.map((label, i) => {
    const stage = { label, detail: details[i] ?? null };
    if (at == null || i > at) return { ...stage, state: 'pending' };
    if (i < at) return { ...stage, state: 'done' };
    return { ...stage, state: workflow === 'failed' ? 'failed' : 'current', busy: runningKind != null };
  });
}

// The run tracker: the pipeline's own flags (GET /batch/checklist's `progress`).
// Validation is not in it: it is a gate before the run, not something the run does.
// A node is done only when the backend says so, or when the running job has
// reported finishing it. Never a percentage: nothing reports one.
const NODE_STAGE = { sales_loaded: 'load', count_loaded: 'load', abc_run: 'abc', forecast_next: 'forecast', lp_next: 'lp' };

export function runTracker(checklist, job) {
  if (!checklist?.progress) return [];
  const plan = job?.kind === 'plan' ? job : null;
  const running = plan?.status === 'running';
  const states = Object.fromEntries((plan?.steps || []).map((step) => [step.stage, step.state]));
  // One load step covers two nodes: it is blamed on the first not yet done.
  let loadNamed = false;
  return checklist.progress.map((p) => {
    const base = { id: p.id, name: p.name };
    if (p.done) return { ...base, state: 'done' };
    const stage = NODE_STAGE[p.id];
    const reported = states[stage];
    if (stage === 'load' && loadNamed) return { ...base, state: 'pending' };
    if (plan?.status === 'failed' && (reported === 'stopped' || plan.failed_stage === stage)) {
      if (stage === 'load') loadNamed = true;
      return { ...base, state: 'failed', note: STEP_STATE.stopped };
    }
    if (running && reported === 'running') {
      if (stage === 'load') loadNamed = true;
      return { ...base, state: 'active', note: STEP_STATE.running };
    }
    // The load step finishing proves the sales arrived. Whether a stock count did
    // is the backend's flag alone, read again when the job ends.
    if (reported === 'done' || reported === 'skipped') return { ...base, state: p.id === 'count_loaded' ? 'pending' : 'done' };
    return { ...base, state: 'pending' };
  });
}

// The stage a running job has reached, by its name. Null when none is running.
export function runningStage(job) {
  if (job?.status !== 'running') return null;
  return (job.steps || []).filter((step) => step.state === 'running').at(-1)?.label ?? null;
}

// How long a running job has been going, from the backend's start time. No
// estimate of what is left: nothing reports one.
export function elapsedText(startedAt, nowMs) {
  const started = Date.parse(startedAt ?? '');
  if (Number.isNaN(started) || nowMs < started) return null;
  const seconds = Math.floor((nowMs - started) / 1000);
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes} min ${String(seconds % 60).padStart(2, '0')} s` : `${seconds} s`;
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return null;
  if (bytes < 1024) return `${bytes} bytes`;
  const kb = bytes / 1024;
  return kb < 1024 ? `${kb.toFixed(0)} KB` : `${(kb / 1024).toFixed(1)} MB`;
}

// What the file check refused for one upload slot, by the slot's table name
// (backend/batch_checklist.TABLES). A warning is not a refusal.
export function fileRefusals(checklist, table) {
  const check = checklist?.checks?.find((c) => c.id === 'files_valid');
  if (check?.status !== 'failed') return [];
  return (check.details || []).filter((d) => d.severity === 'failed' && d.table === table);
}

// A timestamp from the backend, in the reader's own time. Absent stays absent.
export function formatWhen(iso) {
  if (!iso) return null;
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? null : when.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' });
}

// What each stage of a run is doing, in words. No percentage: nothing reports one.
export const STEP_STATE = { running: 'Running', done: 'Done', skipped: 'Already done', stopped: 'Stopped' };
