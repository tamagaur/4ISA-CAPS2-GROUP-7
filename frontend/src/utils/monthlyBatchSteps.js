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
  not_uploaded: { label: 'Not uploaded', badge: 'badge-neutral', step: '1. Upload monthly data' },
  ready_for_validation: { label: 'Ready for validation', badge: 'badge-info', step: '2. Validate' },
  validating: { label: 'Validation in progress', badge: 'badge-info', step: '2. Validate' },
  action_required: { label: 'Action required', badge: 'badge-warning', step: '2. Resolve the checklist' },
  ready_to_run: { label: 'Ready to run', badge: 'badge-success', step: '3. Run the month' },
  processing: { label: 'Processing', badge: 'badge-info', step: '3. Run the month' },
  completed: { label: 'Completed', badge: 'badge-success', step: '4. Review the new plan' },
  awaiting_review: { label: 'Plan ready for review', badge: 'badge-info', step: '4. Review the new plan' },
  failed: { label: 'Failed', badge: 'badge-critical', step: '3. Run the month' },
  closed: { label: 'Closed', badge: 'badge-neutral', step: 'Finished' },
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
  if (failed > 0) {
    return { tone: 'action', title: `Action required: ${plural(failed, 'check')} failed`, text: 'Resolve the issues below before running the monthly data.' };
  }
  if (notChecked > 0 || !checklist.validated) {
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

// The five facts at the top of the section.
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
  else if (workflow === 'closed') processing = 'Closed';

  return {
    month: status.month,
    upload,
    validation,
    processing,
    step: job.status === 'running' && job.kind === 'close' ? '5. Close the month' : (WORKFLOW[workflow]?.step ?? 'Reading'),
  };
}

// A timestamp from the backend, in the reader's own time. Absent stays absent.
export function formatWhen(iso) {
  if (!iso) return null;
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? null : when.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' });
}

// What each stage of a run is doing, in words. No percentage: nothing reports one.
export const STEP_STATE = { running: 'Running', done: 'Done', skipped: 'Already done', stopped: 'Stopped' };
