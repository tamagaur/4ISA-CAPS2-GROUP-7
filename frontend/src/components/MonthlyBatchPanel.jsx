import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, FileText, Loader2, Upload } from 'lucide-react';
import SectionLede from './ui/SectionLede';
import {
  closeBatch, generatePracticeMonth, getBatchFeedback, getBatchJob, getBatchStatus, runBatch, uploadBatchFile,
} from '../api/monthlyBatch';
import { batchStage, canRun, planChange } from '../utils/monthlyBatchSteps';
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

// The Data Management page's monthly batch. DataUpload shows this only when the
// backend says it is enabled, which today means the local practice database.
const MonthlyBatchPanel = ({ initialStatus }) => {
  const [status, setStatus] = useState(initialStatus);
  const [job, setJob] = useState(initialStatus.job);
  const [feedback, setFeedback] = useState(null);
  const [calendarFactor, setCalendarFactor] = useState(null);
  const [reviewed, setReviewed] = useState(false);
  const [error, setError] = useState('');
  const logEnd = useRef(null);
  const month = status.month;
  const stage = job?.status === 'running' ? 'running' : batchStage({ ...status, job });

  const refresh = useCallback(async (forMonth) => {
    const next = await getBatchStatus(forMonth);
    setStatus(next);
    setJob(next.job);
    return next;
  }, []);

  const act = async (fn) => {
    setError('');
    try {
      await fn();
      setJob(await getBatchJob());
    } catch (e) {
      setError(e.message);
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
          await refresh(month);
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

  // The reason a step stopped is at the end of its output.
  useEffect(() => {
    if (logEnd.current) logEnd.current.scrollTop = logEnd.current.scrollHeight;
  }, [job?.log, job?.status]);

  const pick = (kind) => (file) => act(async () => {
    await uploadBatchFile(month, kind, file);
    await refresh(month);
  });

  const expectedTotal = Math.round(status.next_plan.pieces);
  const change = planChange(status.plan.pieces, status.next_plan.pieces);
  const practiceAvailable = month === status.practice_month && !status.checks.sales_loaded;
  const failed = job?.status === 'failed';

  return (
    <section className="mb-panel" aria-label="Monthly batch">
      <p className="ui-note is-info" role="note">
        <AlertTriangle size={16} aria-hidden="true" />
        <span>
          <strong>Local practice database.</strong> This runs the real monthly steps on its own copy, not on the live system. The Dashboard and Reorder pages do not read that copy, so nothing done here appears on them.
          {status.synthetic_rows > 0 && ` ${pieces(status.synthetic_rows)} sales rows this month are generated practice data, so nothing here is a real result.`}
        </span>
      </p>

      <SectionLede className="is-standalone">Monthly batch for {month}</SectionLede>
      {error && <p className="ui-note is-warning" role="alert"><AlertTriangle size={16} aria-hidden="true" /><span>{error}</span></p>}

      <ol className="mb-steps">
        <li className="mb-step">
          <h4>1. Add the month's data</h4>
          {status.checks.sales_loaded ? (
            <p className="mb-done"><CheckCircle2 size={16} aria-hidden="true" /> {month} sales are in the database.</p>
          ) : (
            <>
              <FileSlot label="Sales per product" hint="The Unilever sales-per-SKU file" file={status.files.sales} disabled={stage === 'running'} onPick={pick('sales')} />
              <FileSlot label="Stock count (optional)" hint={status.checks.count_loaded ? 'Already loaded for this month' : 'The month\'s stock count'} file={status.files.count} disabled={stage === 'running'} onPick={pick('count')} />
              {practiceAvailable && (
                <button
                  type="button"
                  className="btn btn-tertiary btn-sm"
                  disabled={stage === 'running'}
                  onClick={() => act(() => generatePracticeMonth(month))}
                >
                  No file? Generate practice sales
                </button>
              )}
            </>
          )}
        </li>

        <li className="mb-step">
          <h4>2. Run the month</h4>
          <p className="mb-small">Loads any files, then updates ABC, the forecast and the order plan for {status.next_month}. It stops before anything is closed.</p>
          <fieldset className="mb-choice" disabled={stage !== 'ready'}>
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
            disabled={!canRun(stage, calendarFactor)}
            onClick={() => act(() => runBatch(month, calendarFactor))}
          >
            Run {month}
          </button>
        </li>

        <li className="mb-step">
          <h4>3. Review the new plan</h4>
          {stage === 'review' || stage === 'closed' ? (
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

        <li className="mb-step">
          <h4>4. Close {month}</h4>
          {stage === 'closed' ? (
            <p className="mb-done"><CheckCircle2 size={16} aria-hidden="true" /> {month} is closed.</p>
          ) : (
            <>
              <label className="mb-confirm">
                <input type="checkbox" checked={reviewed} disabled={stage !== 'review'} onChange={(e) => setReviewed(e.target.checked)} />
                {' '}I have read the plan above{stage === 'review' ? ` (${pieces(expectedTotal)} pieces)` : ''}.
              </label>
              <button
                type="button"
                className="btn btn-primary"
                disabled={stage !== 'review' || !reviewed || !calendarFactorForClose(calendarFactor)}
                onClick={() => act(() => closeBatch(month, calendarFactorForClose(calendarFactor), expectedTotal))}
              >
                Close {month}
              </button>
            </>
          )}
        </li>
      </ol>

      {(stage === 'running' || failed || job?.log) && (
        <details className="mb-log" open={stage === 'running' || failed}>
          <summary>
            {stage === 'running' && <Loader2 className="mb-spin" size={15} aria-hidden="true" />}
            {stage === 'running' ? ' Running, this takes a few minutes' : failed ? ` The last step stopped (exit ${job.exit_code}). Fix the cause and run again; finished steps are skipped.` : 'Output of the last step'}
          </summary>
          <pre ref={logEnd}>{(job?.log || '').split('\n').slice(-60).join('\n')}</pre>
        </details>
      )}
    </section>
  );
};

// The close does not use the factor; run_month requires the argument on every call.
const calendarFactorForClose = (chosen) => chosen || 'on';

export default MonthlyBatchPanel;
