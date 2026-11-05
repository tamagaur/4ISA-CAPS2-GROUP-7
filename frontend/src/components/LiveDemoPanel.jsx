import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, FileSpreadsheet, Loader2, Play, RotateCcw, Upload, XCircle, FlaskConical } from 'lucide-react';
import {
  getLiveDemoStatus, runLiveDemo, settleLiveDemoOrders, startLiveDemo, undoLiveDemo, uploadLiveDemoFile,
} from '../api/liveDemo';
import { canRun, demoStage, pieces, planLine, undoSummary, waitingOrders } from '../liveDemoModel';
import './MonthlyBatchPanel.css';
import './LiveDemoPanel.css';

const STAGE_WORDS = {
  closed: 'Not started',
  open: 'Window open, no file yet',
  file: 'File ready to run',
  loaded: 'March loaded',
  ran: 'April plan is on the pages',
  working: 'Working',
  unknown: 'Unknown',
};

// The demonstration month on the database the pages read, and the one button that puts it back.
const LiveDemoPanel = ({ initialStatus }) => {
  const [status, setStatus] = useState(initialStatus);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [rejected, setRejected] = useState(null);
  const input = useRef(null);
  const running = status?.job?.status === 'running';
  const stage = demoStage(status);

  const refresh = useCallback(async () => {
    try {
      setStatus(await getLiveDemoStatus());
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [running, refresh]);

  const act = async (fn) => {
    setError(null);
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      await refresh();
    }
  };

  const pick = (file) => act(async () => {
    setRejected(null);
    try {
      await uploadLiveDemoFile(file);
    } catch (e) {
      setRejected({ name: file.name, message: e.message });
    }
  });

  const state = status.state;
  const session = state.session;
  const locked = running || busy;
  const waiting = waitingOrders(status);
  const lastUndo = undoSummary(status.last_undo);
  const lines = status.job?.lines || [];
  const showLog = lines.length > 0 && (running || status.job?.status === 'failed' || stage === 'ran' || status.job?.kind === 'undo');

  return (
    <section className="mb-panel ld-panel" aria-label="Live demonstration">
      <p className="ui-note is-warning mb-note-raised" role="note">
        <AlertTriangle size={16} aria-hidden="true" />
        <span>
          <strong>This works on {status.target}.</strong> While a demonstration is open, generated March sales (labelled <code>is_demo</code>) go through the real monthly
          steps and the Dashboard and Reorder pages show the April plan that follows. Anything saved while it is open, including decisions on the Reorder page,
          is put back by <strong>Undo</strong>. Nothing shown is a result.
        </span>
      </p>

      <div className="mb-body">
        <header className="mb-head">
          <span className="mb-tile" aria-hidden="true"><FlaskConical size={20} /></span>
          <div>
            <h3 className="mb-title">Live demonstration</h3>
            <p className="mb-small">Load generated March sales, watch the pages become April, then put everything back.</p>
          </div>
          <span className={`badge ${stage === 'closed' ? 'badge-neutral' : 'badge-warning'}`} role="status" data-testid="ld-stage">{STAGE_WORDS[stage]}</span>
        </header>

        {error && <p className="ui-note is-warning mb-note-raised" role="alert"><AlertTriangle size={16} aria-hidden="true" /><span>{error}</span></p>}
        {lastUndo && stage === 'closed' && (
          <p className={`ui-note ${lastUndo.ok ? 'is-success' : 'is-warning'} mb-note-raised`} role="status" data-testid="ld-undo-result">
            {lastUndo.ok ? <CheckCircle2 size={16} aria-hidden="true" /> : <XCircle size={16} aria-hidden="true" />}<span>{lastUndo.text}</span>
          </p>
        )}

        <div className="ld-plans" aria-label="The plan, before and now">
          {session && <div className="ld-plan"><span className="ld-plan-label">Before the demonstration</span><strong>{planLine(`Plan ${session.baseline.cycle}`, { rows: session.baseline.rows, pieces: session.baseline.pieces })}</strong></div>}
          <div className="ld-plan"><span className="ld-plan-label">Newest plan now</span><strong data-testid="ld-plan-now">{planLine(`Plan ${state.newest_cycle ?? 'none'}`, state.plan)}</strong></div>
          <div className="ld-plan"><span className="ld-plan-label">Generated March rows in the database</span><strong>{pieces(state.generated_rows)}</strong></div>
        </div>

        <ol className="mb-steps">
          <li className="mb-step">
            <h4 className="ld-step-title">1. Open the demonstration</h4>
            <p className="mb-small">Copies every table first (about a minute), then opens the window. Undo needs that copy.</p>
            <div><button type="button" className="btn btn-primary btn-sm" disabled={locked || state.open || Boolean(session)} onClick={() => act(startLiveDemo)}>
              {running && status.job.kind === 'open' ? <Loader2 size={15} className="ld-spin" aria-hidden="true" /> : <Play size={15} aria-hidden="true" />} Open the demonstration
            </button></div>
          </li>

          <li className="mb-step">
            <h4 className="ld-step-title">2. Upload the March sales file</h4>
            <p className="mb-small">A .csv of generated sales: sku_code, quantity_sold, net_amount. One is made by <code>python -m scripts.make_demo_sales_file</code> into <code>local/demo/</code>.</p>
            <div className={`mb-file${rejected ? ' is-refused' : ''}`}>
              <div className="mb-file-main">
                <span className="mb-tile is-small" aria-hidden="true"><FileSpreadsheet size={18} /></span>
                <div className="mb-file-text">
                  <span className="mb-file-title"><span className="mb-file-label">March 2026 sales</span>
                    <span className={`badge ${status.file ? 'badge-success' : 'badge-neutral'}`}>{state.generated_rows > 0 ? 'Loaded' : status.file ? 'File ready' : 'Not uploaded'}</span></span>
                  {status.file ? <span className="mb-file-name">{status.file.name}</span> : <span className="mb-file-hint">Generated, labelled is_demo, never real sales</span>}
                </div>
                <input ref={input} type="file" accept=".csv" aria-label="March 2026 sales" style={{ display: 'none' }}
                  onChange={(e) => { if (e.target.files?.[0]) pick(e.target.files[0]); e.target.value = ''; }} />
                <button type="button" className="btn btn-secondary btn-sm mb-file-btn" disabled={locked || !state.open || state.generated_rows > 0} onClick={() => input.current.click()}>
                  <Upload size={15} aria-hidden="true" /> {status.file ? 'Replace' : 'Choose file'}
                </button>
              </div>
              {rejected && <div className="mb-file-refusal" role="alert"><XCircle size={16} aria-hidden="true" /><span><strong>{rejected.name} was not accepted.</strong> {rejected.message}</span></div>}
            </div>
          </li>

          <li className="mb-step">
            <h4 className="ld-step-title">3. Decide the March orders</h4>
            {state.open && waiting > 0
              ? (<>
                <p className="mb-small" data-testid="ld-waiting">{waiting} orders of the {session?.baseline.cycle} plan still wait for a decision. Run is refused until they are accepted or dismissed: decide them on the <Link to="/reorder">Reorder page</Link>, or accept them here at their recommended quantity for the demonstration. Accepted orders count as stock on the way in the April plan, and Undo puts every decision back.</p>
                <div><button type="button" className="btn btn-secondary btn-sm" disabled={locked} onClick={() => act(settleLiveDemoOrders)}>
                  {running && status.job.kind === 'settle' ? <Loader2 size={15} className="ld-spin" aria-hidden="true" /> : <CheckCircle2 size={15} aria-hidden="true" />} Accept the {waiting} orders for the demonstration
                </button></div>
              </>)
              : <p className="mb-small">{state.open ? 'No March order waits for a decision.' : 'Open the demonstration first.'}</p>}
          </li>

          <li className="mb-step">
            <h4 className="ld-step-title">4. Run</h4>
            <p className="mb-small">Loads the file, then runs the ABC, the forecast, the plan and the marts for April, about two minutes. Forecast error is not shown for a month that rests on generated sales.</p>
            <div><button type="button" className="btn btn-primary btn-sm" disabled={locked || !canRun(status)} onClick={() => act(() => runLiveDemo('on'))}>
              {running && status.job.kind === 'run' ? <Loader2 size={15} className="ld-spin" aria-hidden="true" /> : <Play size={15} aria-hidden="true" />} Run
            </button></div>
          </li>

          <li className="mb-step ld-undo-step">
            <h4 className="ld-step-title">5. Undo</h4>
            <p className="mb-small">Puts back every table and every definition in one transaction that rolls back unless each one equals the copy, then checks the plan and the pinned figures.</p>
            <div className="ld-undo-row">
              {!confirming
                ? <button type="button" className="btn ld-undo" disabled={locked || !session} onClick={() => setConfirming(true)}><RotateCcw size={15} aria-hidden="true" /> Undo the demonstration</button>
                : (<>
                  <button type="button" className="btn ld-undo is-armed" disabled={locked} onClick={() => { setConfirming(false); act(undoLiveDemo); }}><RotateCcw size={15} aria-hidden="true" /> Yes, put everything back</button>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => setConfirming(false)}>Keep it open</button>
                </>)}
            </div>
          </li>
        </ol>

        {showLog && (
          <pre className="ld-log" aria-label="What the steps reported" data-testid="ld-log">{lines.join('\n')}</pre>
        )}
      </div>
    </section>
  );
};

export default LiveDemoPanel;
