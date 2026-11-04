import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, CalendarDays, Check, CheckCircle2, ChevronRight, ClipboardCheck, ClipboardList, FileSpreadsheet, FileText, Info, Loader2, Lock, Play, Sparkles, Upload, X, XCircle,
} from 'lucide-react';
import SectionLede from './ui/SectionLede';
import EmptyState from './ui/EmptyState';
import MonthlyChecklist from './MonthlyChecklist';
import { ApproveFileDialog, PendingDecisionsDialog, RunConfirmDialog } from './MonthlyBatchDialogs';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import {
  closeBatch, generatePracticeMonth, getBatchChecklist, getBatchFeedback, getBatchJob, getBatchStatus, runBatch, signoffBatch, uploadBatchFile, validateBatch,
} from '../api/monthlyBatch';
import {
  batchStage, canRun, decisionsBlocked, elapsedText, fileRefusals, formatBytes, formatWhen, planChange, processingFacts, reorderPath, runHint, runningStage, runTracker, STEP_STATE, WORKFLOW, workflowStages,
} from '../utils/monthlyBatchSteps';
import './MonthlyBatchPanel.css';

const POLL_MS = 2000;
const pieces = (n) => Math.round(n).toLocaleString('en-US');
const pct = (n) => (n == null ? 'n/a' : `${(n * 100).toFixed(1)}%`);

// What POST /batch/files takes (backend/routers/monthly_batch.py), said where the
// file is being chosen.
const FILE_FORMATS = '.xlsx, .xls or .csv, up to 100 MB';

// Whether the file is here, in words. A file waiting is not yet in the database.
const fileState = (file, loaded, refused) => {
  if (refused) return { label: 'Not accepted', badge: 'badge-critical' };
  if (file) return { label: 'File ready', badge: 'badge-success' };
  if (loaded) return { label: 'Already loaded', badge: 'badge-success' };
  return { label: 'Not uploaded', badge: 'badge-neutral' };
};

// `rejected` is a file the upload turned away, `refusals` what the file check found
// in the one waiting. Both show here, in the slot, because this is where they get fixed.
const FileSlot = ({ label, optional, hint, file, loaded, disabled, onPick, rejected, refusals = [] }) => {
  const input = useRef(null);
  const refused = Boolean(rejected) || refusals.length > 0;
  const state = fileState(file, loaded, refused);
  const size = file ? formatBytes(file.bytes) : null;
  return (
    <div className={`mb-file${refused ? ' is-refused' : ''}`}>
      <div className="mb-file-main">
        <span className="mb-tile is-small" aria-hidden="true"><FileSpreadsheet size={18} /></span>
        <div className="mb-file-text">
          <span className="mb-file-title">
            <span className="mb-file-label">{label}{optional && <span className="mb-file-optional"> (optional)</span>}</span>
            <span className={`badge ${state.badge}`}>{state.label}</span>
          </span>
          {file
            ? <span className="mb-file-name">{file.name}{size && <span className="mb-file-size"> · {size}</span>}</span>
            : <span className="mb-file-hint">{hint}</span>}
          <span className="mb-file-formats">{FILE_FORMATS}</span>
        </div>
        <input
          ref={input}
          type="file"
          accept=".xlsx,.xls,.csv"
          aria-label={optional ? `${label} (optional)` : label}
          style={{ display: 'none' }}
          onChange={(e) => { if (e.target.files?.[0]) onPick(e.target.files[0]); e.target.value = ''; }}
        />
        <button type="button" className="btn btn-secondary btn-sm mb-file-btn" disabled={disabled} onClick={() => input.current.click()}>
          {file ? <FileText size={15} aria-hidden="true" /> : <Upload size={15} aria-hidden="true" />}
          {file ? 'Replace' : 'Choose file'}
        </button>
      </div>
      {rejected && (
        <div className="mb-file-refusal" role="alert">
          <XCircle size={16} aria-hidden="true" />
          <span><strong>{rejected.name} was not accepted.</strong> {rejected.message}</span>
        </div>
      )}
      {refusals.map((refusal) => (
        <div className="mb-file-refusal" role="alert" key={`${refusal.file}-${refusal.reason}`}>
          <XCircle size={16} aria-hidden="true" />
          <span><strong>{refusal.reason}</strong> {refusal.action}</span>
        </div>
      ))}
    </div>
  );
};

// A section's heading: its icon, its title and one line, with its action at the right.
const StepHead = ({ icon: Icon, title, lede, children }) => (
  <div className="mb-step-head">
    <span className="mb-tile" aria-hidden="true"><Icon size={20} /></span>
    <div className="mb-step-title">
      <h4>{title}</h4>
      {lede && <p className="mb-small">{lede}</p>}
    </div>
    {children}
  </div>
);

const STAGE_WORDS = { done: 'done', current: 'current step', failed: 'failed', pending: 'not yet' };

// The five stages across the top. Where the month stands comes from the backend.
const WorkflowStages = ({ stages }) => (
  <ol className="mb-flow" aria-label="Monthly processing stages">
    {stages.map((stage, i) => (
      <React.Fragment key={stage.label}>
        {i > 0 && <ChevronRight className="mb-flow-sep" size={18} aria-hidden="true" />}
        <li className={`mb-flow-step is-${stage.state}`} aria-current={stage.state === 'current' ? 'step' : undefined}>
          <span className="mb-flow-dot" aria-hidden="true">
            {stage.state === 'done' && <Check size={16} strokeWidth={3} />}
            {stage.state === 'failed' && <X size={16} strokeWidth={3} />}
            {stage.busy && <Loader2 className="mb-spin" size={16} strokeWidth={3} />}
            {!stage.busy && (stage.state === 'current' || stage.state === 'pending') && i + 1}
          </span>
          <span className="mb-flow-text">
            <span className="mb-flow-label">{stage.label}</span>
            {stage.detail && <span className="mb-flow-detail">{stage.detail}</span>}
          </span>
          <span className="visually-hidden">: {STAGE_WORDS[stage.state]}</span>
        </li>
      </React.Fragment>
    ))}
  </ol>
);

const NODE_WORDS = { done: 'done', active: 'running', failed: 'stopped', pending: 'not yet' };

// What has run for this month, in the order it runs (runTracker). A stage is
// never shown done before the backend or the running job reports it. No percentage.
const RunTracker = ({ nodes }) => (
  <ol className="mb-tracker" aria-label="What has run for this month">
    {nodes.map((node) => (
      <li key={node.id} className={`mb-node is-${node.state}`}>
        <span className="mb-node-dot" aria-hidden="true">
          {node.state === 'done' && <Check size={14} strokeWidth={3} />}
          {node.state === 'failed' && <X size={14} strokeWidth={3} />}
          {node.state === 'active' && <Loader2 className="mb-spin" size={14} strokeWidth={3} />}
        </span>
        <span className="mb-node-text">
          <span className="mb-node-label">{node.name}</span>
          {node.note && <span className="mb-node-note">{node.note}</span>}
          <span className="visually-hidden">: {NODE_WORDS[node.state]}</span>
        </span>
      </li>
    ))}
  </ol>
);

const PlanRow = ({ label, plan, note, isNew = false }) => (
  <tr className={isNew ? 'is-new' : undefined}>
    <th scope="row">{label}</th>
    <td>{plan.rows.toLocaleString('en-US')}</td>
    <td>{plan.ordering.toLocaleString('en-US')}</td>
    <td>{pieces(plan.pieces)}</td>
    <td>{note}</td>
  </tr>
);

const Feedback = ({ report }) => {
  const { forecast: fc, decisions: d, receipts } = report;
  return (
    <div className="mb-feedback">
      <SectionLede className="is-standalone">How {report.cycle} went</SectionLede>
      <dl className="mb-facts">
        <div>
          <dt>Forecast vs sales</dt>
          {fc.status === 'blocked' ? <dd>{fc.reason}</dd> : (
            <dd>
              {pieces(fc.forecast)} forecast, {pieces(fc.actual)} sold across {fc.scored} products.
              {' '}Error {pct(fc.wape)}, bias {pct(fc.bias)}: {fc.over} over, {fc.under} under.
            </dd>
          )}
        </div>
        <div>
          <dt>Planner decisions</dt>
          <dd>
            {d.accepted} accepted, {d.dismissed} dismissed, {d.pending} not decided.
            {' '}{d.overrides} quantity changes ({d.override_change_pieces >= 0 ? '+' : ''}{pieces(d.override_change_pieces)} pieces).
          </dd>
        </div>
        {d.reasons.length > 0 && (
          <div>
            <dt>Reasons given</dt>
            <dd>{d.reasons.map(([reason, n]) => `${reason} (${n})`).join(', ')}</dd>
          </div>
        )}
        <div>
          <dt>Accepted orders</dt>
          <dd>
            {receipts.length === 0 ? 'None recorded for this month.' : receipts.map((r) => (
              `${r.n} ${r.state === 'expected' ? 'still on the way' : 'seen in the stock count'}`
              + `${r.not_visible ? ', but stock did not rise (possible short delivery)' : ''}`
            )).join('; ')}
          </dd>
        </div>
      </dl>
      <p className="mb-small">For people to read. None of this changes the next plan.</p>
    </div>
  );
};

// How the month's run ended, from the backend (batch_checklist.run_result).
// Complete means the job exited 0 and the plan exists: a started job is not a
// finished one. Stages are what the run reported, never a percentage.
const RunStages = ({ steps }) => (
  <ul className="mb-stages">
    {steps.map((s) => (
      <li key={s.stage} className={`is-${s.state}`}>
        <span>{s.label}</span>
        <span className="mb-small">{STEP_STATE[s.state] ?? s.state}</span>
      </li>
    ))}
  </ul>
);

// How long the job has been going. It ticks, so it stays out of the screen reader's
// live region: the stage names are what get announced.
const Elapsed = ({ since }) => {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const text = elapsedText(since, now);
  return text ? <span aria-hidden="true"> {text} so far.</span> : null;
};

const OUTPUT_KIND = { plan: 'Run the month', validate: 'Validation', practice: 'Practice sales', close: 'Close the month' };
const OUTPUT_STATUS = { running: 'Running', done: 'Finished', failed: 'Stopped' };

// The last job: how it ended and the stages it reached. The raw lines are not here on
// purpose: GET /batch/job stopped returning them because they can carry internals
// (docs/MONTHLY_BATCH_REVIEW.md), and the full output stays in the saved log.
const JobOutput = ({ job }) => {
  if (!job?.id) return null;
  const failed = job.status === 'failed';
  return (
    <details className="mb-output" open={job.status === 'running' || failed}>
      <summary>
        <span className="mb-output-title">Output of the last step</span>
        <span className="mb-small">
          {OUTPUT_KIND[job.kind] ?? job.kind}: {OUTPUT_STATUS[job.status] ?? job.status}{failed && job.exit_code != null ? ` (exit ${job.exit_code})` : ''}
        </span>
      </summary>
      {job.steps?.length > 0 && <RunStages steps={job.steps} />}
      <p className="mb-small">Job {job.id}. The full technical log is saved under local/monthly_batch/logs.</p>
    </details>
  );
};

// After the close. The page stays on the closed month until it is reloaded, because
// the backend then opens the next one (run_month.current_month).
const ClosedBanner = ({ month, nextMonth, nextPlan, closedAt }) => (
  <div className="mb-result is-closed" role="status">
    <h5><Lock size={16} aria-hidden="true" /> {month} is closed</h5>
    <p>Its accepted orders are settled against the stock count and its plan is marked closed. Nothing was deleted, and it can be reopened from the command line.</p>
    <dl className="mb-result-facts">
      {closedAt && <div><dt>Closed</dt><dd>{closedAt}</dd></div>}
      <div><dt>Next month</dt><dd>{nextMonth}</dd></div>
      <div><dt>Its plan</dt><dd>{nextPlan.rows.toLocaleString('en-US')} products, {pieces(nextPlan.pieces)} pieces</dd></div>
    </dl>
    <p className="mb-small">Reload the page to move on to {nextMonth}.</p>
  </div>
);

const RunResult = ({ result, job }) => {
  if (!result) return null;
  if (result.state === 'processing') {
    const now = runningStage(job);
    return (
      <div className="mb-result is-processing" role="status">
        <h5><Loader2 className="mb-spin" size={16} aria-hidden="true" /> {result.kind === 'close' ? `Closing ${result.month}` : result.kind === 'practice' ? 'Generating practice sales' : `Processing ${result.month}`}</h5>
        <p>{now ? `Now on: ${now}.` : 'Starting.'}<Elapsed since={job?.started_at} /></p>
        <p className="mb-small">This takes a few minutes. A reload is safe: it comes back still running.</p>
      </div>
    );
  }
  if (result.state === 'completed') {
    const when = formatWhen(result.finished_at);
    return (
      <div className="mb-result is-completed" role="status">
        <h5><CheckCircle2 size={16} aria-hidden="true" /> Monthly Processing Complete</h5>
        <p>The selected month&apos;s data has been processed successfully. Review the new plan, then close the month.</p>
        <dl className="mb-result-facts">
          <div><dt>Processing month</dt><dd>{result.month}</dd></div>
          {when && <div><dt>Completed</dt><dd>{when}</dd></div>}
          {result.run_id != null && <div><dt>Plan run</dt><dd>{result.run_id}</dd></div>}
        </dl>
      </div>
    );
  }
  return (
    <div className="mb-result is-failed" role="alert">
      <h5><XCircle size={16} aria-hidden="true" /> {result.kind === 'plan' ? 'Monthly Processing Failed' : `${result.failed_stage} failed`}</h5>
      <p>{result.kind === 'plan' ? "An issue occurred while processing the selected month's data." : result.message}</p>
      <dl className="mb-result-facts">
        {result.kind === 'plan' && <div><dt>Stopped at</dt><dd>{result.failed_stage}</dd></div>}
        {result.kind === 'plan' && <div><dt>What happened</dt><dd>{result.message}</dd></div>}
        <div><dt>What to do</dt><dd>{result.action}</dd></div>
      </dl>
    </div>
  );
};

// The Data Management page's monthly batch. DataUpload shows this only when the
// backend says it is enabled, which today means the local practice database.
const MonthlyBatchPanel = ({ initialStatus }) => {
  const navigate = useNavigate();
  const { hasPermission } = usePermissions();
  const [status, setStatus] = useState(initialStatus);
  const [job, setJob] = useState(initialStatus.job);
  const [checklist, setChecklist] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [calendarFactor, setCalendarFactor] = useState(null);
  const [reviewed, setReviewed] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState(null);     // 'decisions' | 'run' | 'approve'
  const [rejected, setRejected] = useState({});   // { sales | count: { name, message } }
  const uploadStep = useRef(null);
  const month = status.month;
  const running = job?.status === 'running';
  const stage = running ? 'running' : batchStage({ ...status, job });

  // Both answers are read fresh, so the page never acts on what it saw earlier.
  const refresh = useCallback(async (forMonth) => {
    const [next, list] = await Promise.all([getBatchStatus(forMonth), getBatchChecklist(forMonth)]);
    setStatus(next);
    setJob(next.job);
    setChecklist(list);
    return list;
  }, []);

  useEffect(() => {
    let current = true;
    getBatchChecklist(initialStatus.month)
      .then((list) => { if (current) setChecklist(list); })
      .catch((e) => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [initialStatus.month]);

  // One request at a time. `busy` disables the buttons on the next render, which
  // is too late for a second click on the same button; this answers at once.
  const inFlight = useRef(false);
  const act = async (fn) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError('');
    setNotice('');
    setBusy(true);
    try {
      await fn();
      setJob(await getBatchJob());
    } catch (e) {
      setError(e.message);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  // While a step runs, follow it; when it ends, read the new state of the month.
  useEffect(() => {
    if (job?.status !== 'running') return undefined;
    const timer = setInterval(async () => {
      try {
        const next = await getBatchJob();
        setJob(next);
        if (next.status !== 'running') {
          clearInterval(timer);
          setFeedback(null);
          const list = await refresh(month);
          if (next.kind === 'validate' && decisionsBlocked(list)) setDialog('decisions');
        }
      } catch (e) {
        setError(e.message);
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [job?.status, month, refresh]);

  useEffect(() => {
    if (stage !== 'review' && stage !== 'closed') return undefined;
    let current = true;
    getBatchFeedback(month).then((r) => { if (current) setFeedback(r); }).catch((e) => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [stage, month]);

  // A refusal is said in the file's own slot. The file on record may have changed
  // either way, so the month is read again.
  const pick = (kind) => (file) => act(async () => {
    setRejected((current) => ({ ...current, [kind]: null }));
    try {
      await uploadBatchFile(month, kind, file);
    } catch (e) {
      setRejected((current) => ({ ...current, [kind]: { name: file.name, message: e.message } }));
    }
    await refresh(month);
  });

  const validate = () => act(async () => {
    const res = await validateBatch(month);
    if (!res.started) {
      const list = await refresh(month);
      if (decisionsBlocked(list)) setDialog('decisions');
    }
  });

  const run = () => {
    setDialog(null);
    act(async () => {
      try {
        await runBatch(month, calendarFactor);
      } catch (e) {
        // Something changed since the last look. The backend's answer stands.
        if (e.code === 'batch_checks_failed') {
          const list = await refresh(month);
          if (decisionsBlocked(list)) setDialog('decisions');
        }
        throw e;
      }
    });
  };

  const approve = async () => {
    await signoffBatch(month);
    await refresh(month);
    setDialog(null);
    setNotice('The file is approved. It can load as long as it does not change.');
  };

  const onCheckAction = (actionId) => {
    if (actionId === 'validate') validate();
    else if (actionId === 'review_recommendations') setDialog('decisions');
    else if (actionId === 'approve') setDialog('approve');
    else if (actionId === 'upload') uploadStep.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const expectedTotal = Math.round(status.next_plan.pieces);
  const change = planChange(status.plan.pieces, status.next_plan.pieces);
  const practiceAvailable = month === status.practice_month && !status.checks.sales_loaded;
  const workflow = WORKFLOW[checklist?.workflow];
  const facts = processingFacts({ ...status, job }, checklist);
  const result = checklist?.result ?? status.result;
  const shownResult = running && job.kind !== 'validate' ? { state: 'processing', kind: job.kind, month } : result;
  const hint = runHint(checklist, calendarFactor);
  const inputsLocked = running || busy;
  const finished = stage === 'review' || stage === 'closed';
  const closeMissing = status.close_missing || [];
  const validating = running && job.kind === 'validate';
  const runningPlan = running && job.kind === 'plan';
  const stages = workflowStages(checklist?.workflow, job, facts);
  const planWritten = finished && checklist?.workflow !== 'failed';
  const nodes = runTracker(checklist, job);

  return (
    <section className="mb-panel" aria-label="Monthly Data Processing">
      <p className="ui-note is-info mb-note-raised" role="note">
        <Info size={16} aria-hidden="true" />
        <span>
          <strong>Local practice database.</strong> This runs the real monthly steps on its own copy, not on the live system. The Dashboard and Reorder pages do not read that copy, so nothing done here appears on them.
          {status.synthetic_rows > 0 && ` ${pieces(status.synthetic_rows)} sales rows this month are generated practice data, so nothing here is a real result.`}
        </span>
      </p>

      <div className="mb-body">
        <div className="mb-overview">
          <header className="mb-head">
            <span className="mb-tile" aria-hidden="true"><CalendarDays size={20} /></span>
            <div>
              <h3 className="mb-title">Monthly Data Processing</h3>
              <p className="mb-small">Upload and validate monthly records before updating inventory analytics.</p>
            </div>
            {workflow && <span className="visually-hidden" role="status">{workflow.label}</span>}
          </header>

          <div className="mb-month">
            <CalendarDays size={18} aria-hidden="true" />
            <span>
              <span className="mb-month-label">Processing month</span>
              <strong>{facts.month}</strong>
            </span>
          </div>
        </div>

        <WorkflowStages stages={stages} />

        {error && <p className="ui-note is-warning mb-note-raised" role="alert"><AlertTriangle size={16} aria-hidden="true" /><span>{error}</span></p>}
        {notice && <p className="ui-note is-success mb-note-raised" role="status"><CheckCircle2 size={16} aria-hidden="true" /><span>{notice}</span></p>}
        <RunResult result={shownResult} job={job} />
        {stage === 'closed' && (
          <ClosedBanner month={month} nextMonth={status.next_month} nextPlan={status.next_plan} closedAt={job?.kind === 'close' ? formatWhen(job.finished_at) : null} />
        )}

        <ol className="mb-steps">
          <li className="mb-step mb-step-upload" ref={uploadStep}>
            <StepHead icon={Upload} title="1. Upload monthly data" lede="Unilever only: sales per product and stock count for the processing month. Del Monte has no per-product sales, so it has no file here." />
            {status.checks.sales_loaded ? (
              <p className="mb-done"><CheckCircle2 size={16} aria-hidden="true" /> {month} sales are in the database.</p>
            ) : (
              <div className="mb-files">
                <FileSlot label="Sales per product" hint="The Unilever sales-per-SKU file" file={status.files.sales} disabled={inputsLocked} onPick={pick('sales')} rejected={rejected.sales} refusals={fileRefusals(checklist, 'Sales per product')} />
                <FileSlot label="Stock count" optional hint="The month's stock count" file={status.files.count} loaded={status.checks.count_loaded} disabled={inputsLocked} onPick={pick('count')} rejected={rejected.count} refusals={fileRefusals(checklist, 'Stock count')} />
                {practiceAvailable && (
                  <div className="mb-practice">
                    <span className="mb-tile is-small is-info" aria-hidden="true"><Sparkles size={18} /></span>
                    <div className="mb-practice-text">
                      <span className="mb-file-label">No file? Generate practice sales</span>
                      <span className="mb-file-hint">Create practice sales data for {month} to try the full process.</span>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        disabled={inputsLocked}
                        onClick={() => act(() => generatePracticeMonth(month))}
                      >
                        <Sparkles size={15} aria-hidden="true" />
                        Generate practice sales
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </li>

          <li className="mb-step mb-step-validate">
            <StepHead icon={ClipboardCheck} title="2. Validate" lede="Carries over the Reorder page's decisions and checks any waiting file. It loads nothing.">
              <button
                type="button"
                className={`btn mb-step-action ${checklist?.workflow === 'ready_for_validation' ? 'btn-primary' : 'btn-secondary'}`}
                disabled={inputsLocked || finished}
                onClick={validate}
              >
                {validating ? <Loader2 className="mb-spin" size={15} aria-hidden="true" /> : <Play size={15} aria-hidden="true" />}
                {validating ? 'Validating' : (checklist?.validated ? 'Run Validation Again' : 'Run Validation')}
              </button>
            </StepHead>
            <MonthlyChecklist checklist={checklist} onAction={onCheckAction} busy={inputsLocked} />
          </li>

          <li className="mb-step mb-step-run">
            <StepHead icon={Play} title="3. Run the month" lede={`Loads any files, then updates ABC, the forecast and the order plan for ${status.next_month}. It stops before anything is closed.`} />
            <div className="mb-run">
              <div className="mb-run-controls">
                {planWritten ? (
                  <p className="mb-done"><CheckCircle2 size={16} aria-hidden="true" /> The {status.next_month} plan is written.</p>
                ) : (
                  <>
                    <fieldset className="mb-choice" disabled={inputsLocked}>
                      <legend>Calendar factor</legend>
                      {['on', 'off'].map((value) => (
                        <label key={value} className={`mb-choice-option${calendarFactor === value ? ' is-selected' : ''}`}>
                          <input type="radio" name="calendar-factor" value={value} checked={calendarFactor === value} onChange={() => setCalendarFactor(value)} />
                          {value === 'on' ? 'On (as the live forecast)' : 'Off'}
                        </label>
                      ))}
                    </fieldset>
                    <button
                      type="button"
                      className="btn btn-primary mb-run-btn"
                      disabled={inputsLocked || !canRun(checklist, calendarFactor)}
                      onClick={() => setDialog('run')}
                    >
                      {runningPlan ? <Loader2 className="mb-spin" size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
                      {runningPlan ? 'Running' : 'Run the Month'}
                    </button>
                    {hint && <p className="mb-run-gate"><Lock size={14} aria-hidden="true" /> {hint}</p>}
                  </>
                )}
              </div>
              <div className="mb-run-progress">
                <h5 className="mb-subhead">Run progress</h5>
                {nodes.length > 0 && <RunTracker nodes={nodes} />}
              </div>
            </div>
            <JobOutput job={job} />
          </li>

          <li className="mb-step mb-step-review">
            <StepHead icon={ClipboardList} title="4. Review the new plan" lede={finished ? 'The current plan beside the new one.' : 'The old and new plans appear here after the run.'} />
            {finished ? (
              <>
                <div className="mb-table-wrap">
                  <table className="mb-table">
                    <thead><tr><th scope="col">Plan</th><th scope="col">Products</th><th scope="col">Ordering</th><th scope="col">Pieces</th><th scope="col">Note</th></tr></thead>
                    <tbody>
                      <PlanRow label={month} plan={status.plan} note="Current" />
                      <PlanRow label={status.next_month} plan={status.next_plan} note={change ? `${change} the current plan` : 'New'} isNew />
                    </tbody>
                  </table>
                </div>
                {status.count_lines.slice(0, 1).map((line) => <p className="mb-small" key={line}>{line}</p>)}
                {feedback && <Feedback report={feedback} />}
              </>
            ) : (
              <>
                <EmptyState icon={FileText} title="No new plan to review yet" className="mb-empty">
                  Run the month to generate the updated plan.
                </EmptyState>
                <p className="ui-note is-info" role="note">
                  <Info size={16} aria-hidden="true" />
                  <span>After a successful run, comparison results (old vs. new plan) will appear here.</span>
                </p>
              </>
            )}
          </li>

          <li className="mb-step mb-step-close">
            <StepHead icon={Lock} title={`5. Close ${month}`} lede="Completes the month after you have reviewed the plan. It settles accepted orders against the stock count and marks this month's plan closed. Nothing is deleted." />
            {stage === 'closed' ? (
              <p className="mb-done"><CheckCircle2 size={16} aria-hidden="true" /> {month} is closed.</p>
            ) : (
              <>
                {stage === 'review' && closeMissing.length > 0 && (
                  <p className="mb-small">Closing will be refused until: {closeMissing.join('; ')}.</p>
                )}
                <label className="mb-confirm">
                  <input type="checkbox" checked={reviewed} disabled={stage !== 'review'} onChange={(e) => setReviewed(e.target.checked)} />
                  <span>
                    <span className="mb-confirm-text">I have read the plan above{stage === 'review' ? ` (${pieces(expectedTotal)} pieces)` : ''}.</span>
                    <span className="mb-small mb-confirm-help">Check the plan and the forecast before closing the month.</span>
                  </span>
                </label>
                <button
                  type="button"
                  className="btn mb-close-btn"
                  disabled={stage !== 'review' || !reviewed || !calendarFactorForClose(calendarFactor) || busy}
                  onClick={() => act(() => closeBatch(month, calendarFactorForClose(calendarFactor), expectedTotal))}
                >
                  <Lock size={15} aria-hidden="true" />
                  Close {month}
                </button>
              </>
            )}
          </li>
        </ol>
      </div>

      {dialog === 'decisions' && checklist && (
        <PendingDecisionsDialog
          month={month}
          nextMonth={status.next_month}
          decisions={checklist.decisions}
          canReview={hasPermission(P.LP_VIEW)}
          onReview={() => navigate(reorderPath(checklist.decisions))}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'run' && checklist && (
        <RunConfirmDialog
          month={month}
          nextMonth={status.next_month}
          calendarFactor={calendarFactor}
          warnings={checklist.summary.warning}
          onConfirm={run}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'approve' && checklist && (
        <ApproveFileDialog fileCheck={checklist.file_check} onApprove={approve} onClose={() => setDialog(null)} />
      )}
    </section>
  );
};

// The close does not use the factor; run_month requires the argument on every call.
const calendarFactorForClose = (chosen) => chosen || 'on';

export default MonthlyBatchPanel;
