import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, Circle, FileText, Loader2, Upload, XCircle } from 'lucide-react';
import SectionLede from './ui/SectionLede';
import MonthlyChecklist from './MonthlyChecklist';
import { ApproveFileDialog, PendingDecisionsDialog, RunConfirmDialog } from './MonthlyBatchDialogs';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import {
  closeBatch, generatePracticeMonth, getBatchChecklist, getBatchFeedback, getBatchJob, getBatchStatus, runBatch, signoffBatch, uploadBatchFile, validateBatch,
} from '../api/monthlyBatch';
import {
  batchStage, canRun, decisionsBlocked, formatWhen, planChange, processingFacts, reorderPath, runHint, STEP_STATE, WORKFLOW,
} from '../utils/monthlyBatchSteps';
import './MonthlyBatchPanel.css';

const POLL_MS = 2000;
const pieces = (n) => Math.round(n).toLocaleString('en-US');
const pct = (n) => (n == null ? 'n/a' : `${(n * 100).toFixed(1)}%`);

const FileSlot = ({ label, hint, file, disabled, onPick }) => {
  const input = useRef(null);
  return (
    <div className="mb-file">
      <div className="mb-file-text">
        <span className="mb-file-label">{label}</span>
        <span className="mb-file-hint">{file ? file.name : hint}</span>
      </div>
      <input
        ref={input}
        type="file"
        accept=".xlsx,.xls,.csv"
        aria-label={label}
        style={{ display: 'none' }}
        onChange={(e) => { if (e.target.files?.[0]) onPick(e.target.files[0]); e.target.value = ''; }}
      />
      <button type="button" className="btn btn-secondary btn-sm" disabled={disabled} onClick={() => input.current.click()}>
        {file ? <FileText size={15} aria-hidden="true" /> : <Upload size={15} aria-hidden="true" />}
        {file ? 'Replace' : 'Choose file'}
      </button>
    </div>
  );
};

const PlanRow = ({ label, plan, note }) => (
  <tr>
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

const RunResult = ({ result, job }) => {
  if (!result) return null;
  const steps = job?.steps || [];
  if (result.state === 'processing') {
    return (
      <div className="mb-result is-processing" role="status">
        <h5><Loader2 className="mb-spin" size={16} aria-hidden="true" /> {result.kind === 'close' ? `Closing ${result.month}` : result.kind === 'practice' ? 'Generating practice sales' : `Processing ${result.month}`}</h5>
        <p className="mb-small">This takes a few minutes. A reload is safe: it comes back still running.</p>
        {steps.length > 0 && <RunStages steps={steps} />}
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
      <details className="mb-check-details">
        <summary>Review available details</summary>
        {steps.length > 0 && <RunStages steps={steps} />}
        <p className="mb-small">Job {result.job_id}. The full technical log is saved under local/monthly_batch/logs.</p>
      </details>
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

  const pick = (kind) => (file) => act(async () => {
    await uploadBatchFile(month, kind, file);
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

  return (
    <section className="mb-panel" aria-label="Monthly Data Processing">
      <p className="ui-note is-info" role="note">
        <AlertTriangle size={16} aria-hidden="true" />
        <span>
          <strong>Local practice database.</strong> This runs the real monthly steps on its own copy, not on the live system. The Dashboard and Reorder pages do not read that copy, so nothing done here appears on them.
          {status.synthetic_rows > 0 && ` ${pieces(status.synthetic_rows)} sales rows this month are generated practice data, so nothing here is a real result.`}
        </span>
      </p>

      <header className="mb-head">
        <div>
          <h3 className="mb-title">Monthly Data Processing</h3>
          <p className="mb-small">Upload and validate monthly records before updating inventory analytics.</p>
        </div>
        {workflow && <span className={`badge ${workflow.badge}`} role="status">{workflow.label}</span>}
      </header>

      <dl className="mb-status">
        <div><dt>Processing month</dt><dd>{facts.month}</dd></div>
        <div><dt>Upload</dt><dd>{facts.upload}</dd></div>
        <div><dt>Validation</dt><dd>{facts.validation}</dd></div>
        <div><dt>Processing</dt><dd>{facts.processing}</dd></div>
        <div><dt>Current step</dt><dd>{facts.step}</dd></div>
      </dl>

      {error && <p className="ui-note is-warning" role="alert"><AlertTriangle size={16} aria-hidden="true" /><span>{error}</span></p>}
      {notice && <p className="ui-note is-success" role="status"><CheckCircle2 size={16} aria-hidden="true" /><span>{notice}</span></p>}
      <RunResult result={shownResult} job={job} />

      <ol className="mb-steps">
        <li className="mb-step mb-step-wide" ref={uploadStep}>
          <h4>1. Upload monthly data</h4>
          {status.checks.sales_loaded ? (
            <p className="mb-done"><CheckCircle2 size={16} aria-hidden="true" /> {month} sales are in the database.</p>
          ) : (
            <div className="mb-files">
              <FileSlot label="Sales per product" hint="The Unilever sales-per-SKU file" file={status.files.sales} disabled={inputsLocked} onPick={pick('sales')} />
              <FileSlot label="Stock count (optional)" hint={status.checks.count_loaded ? 'Already loaded for this month' : 'The month\'s stock count'} file={status.files.count} disabled={inputsLocked} onPick={pick('count')} />
              {practiceAvailable && (
                <button
                  type="button"
                  className="btn btn-tertiary btn-sm"
                  disabled={inputsLocked}
                  onClick={() => act(() => generatePracticeMonth(month))}
                >
                  No file? Generate practice sales
                </button>
              )}
            </div>
          )}
        </li>

        <li className="mb-step mb-step-wide">
          <div className="mb-step-head">
            <div>
              <h4>2. Validate</h4>
              <p className="mb-small">Carries over the Reorder page&apos;s decisions and checks any waiting file. It loads nothing.</p>
            </div>
            <button
              type="button"
              className={`btn ${checklist?.workflow === 'ready_for_validation' ? 'btn-primary' : 'btn-secondary'}`}
              disabled={inputsLocked || finished}
              onClick={validate}
            >
              {checklist?.validated ? 'Run Validation Again' : 'Run Validation'}
            </button>
          </div>
          <MonthlyChecklist checklist={checklist} onAction={onCheckAction} busy={inputsLocked} />
        </li>

        <li className="mb-step">
          <h4>3. Run the month</h4>
          <p className="mb-small">Loads any files, then updates ABC, the forecast and the order plan for {status.next_month}. It stops before anything is closed.</p>
          <fieldset className="mb-choice" disabled={inputsLocked || (finished && checklist?.workflow !== 'failed')}>
            <legend>Calendar factor</legend>
            {['on', 'off'].map((value) => (
              <label key={value}>
                <input type="radio" name="calendar-factor" value={value} checked={calendarFactor === value} onChange={() => setCalendarFactor(value)} />
                {' '}{value === 'on' ? 'On (as the live forecast)' : 'Off'}
              </label>
            ))}
          </fieldset>
          <button
            type="button"
            className="btn btn-primary"
            disabled={inputsLocked || !canRun(checklist, calendarFactor)}
            onClick={() => setDialog('run')}
          >
            Run the Month
          </button>
          {hint && !finished && <p className="mb-small">{hint}</p>}
          {checklist?.progress && (
            <ul className="mb-progress" aria-label="What has run for this month">
              {checklist.progress.map((p) => (
                <li key={p.id} className={p.done ? 'is-done' : ''}>
                  {p.done ? <CheckCircle2 size={14} aria-hidden="true" /> : <Circle size={14} aria-hidden="true" />}
                  {p.name}<span className="visually-hidden">{p.done ? ': done' : ': not yet'}</span>
                </li>
              ))}
            </ul>
          )}
        </li>

        <li className="mb-step">
          <h4>4. Review the new plan</h4>
          {finished ? (
            <>
              <div className="mb-table-wrap">
                <table className="mb-table">
                  <thead><tr><th scope="col">Plan</th><th scope="col">Products</th><th scope="col">Ordering</th><th scope="col">Pieces</th><th scope="col">Note</th></tr></thead>
                  <tbody>
                    <PlanRow label={month} plan={status.plan} note="Current" />
                    <PlanRow label={status.next_month} plan={status.next_plan} note={change ? `${change} the current plan` : 'New'} />
                  </tbody>
                </table>
              </div>
              {status.count_lines.slice(0, 1).map((line) => <p className="mb-small" key={line}>{line}</p>)}
              {feedback && <Feedback report={feedback} />}
            </>
          ) : <p className="mb-small">The old and new plans appear here after the run.</p>}
        </li>

        <li className="mb-step mb-step-wide">
          <h4>5. Close {month}</h4>
          {stage === 'closed' ? (
            <p className="mb-done"><CheckCircle2 size={16} aria-hidden="true" /> {month} is closed.</p>
          ) : (
            <>
              {stage === 'review' && closeMissing.length > 0 && (
                <p className="mb-small">Closing will be refused until: {closeMissing.join('; ')}.</p>
              )}
              <label className="mb-confirm">
                <input type="checkbox" checked={reviewed} disabled={stage !== 'review'} onChange={(e) => setReviewed(e.target.checked)} />
                {' '}I have read the plan above{stage === 'review' ? ` (${pieces(expectedTotal)} pieces)` : ''}.
              </label>
              <button
                type="button"
                className="btn btn-primary"
                disabled={stage !== 'review' || !reviewed || !calendarFactorForClose(calendarFactor) || busy}
                onClick={() => act(() => closeBatch(month, calendarFactorForClose(calendarFactor), expectedTotal))}
              >
                Close {month}
              </button>
            </>
          )}
        </li>
      </ol>

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
