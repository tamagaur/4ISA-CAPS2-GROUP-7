import React from 'react';
import { AlertTriangle, CheckCircle2, Info, MinusCircle, XCircle } from 'lucide-react';
import { CHECK_STATUS, checklistSummary } from '../utils/monthlyBatchSteps';

const ICONS = { passed: CheckCircle2, failed: XCircle, warning: AlertTriangle, not_checked: MinusCircle };
const TONE_NOTE = { ok: 'is-success', action: 'is-warning', pending: 'is-info', done: 'is-info' };
const TONE_ICON = { ok: CheckCircle2, action: AlertTriangle, pending: Info, done: Info };

// What the loader found for one file or table. Only what the backend sent:
// a dry run keeps no row-level detail, so there is none to show.
const CheckDetails = ({ details }) => (
  <details className="mb-check-details">
    <summary>Review details ({details.length})</summary>
    <ul>
      {details.map((d, i) => (
        <li key={`${d.file}-${d.table}-${i}`}>
          {(d.file || d.table) && <span className="mb-check-file">{[d.file, d.table].filter(Boolean).join(' · ')}</span>}
          <span>{d.reason}</span>
          {d.detail && <span className="mb-small">{d.detail}</span>}
          {d.action && <span className="mb-small">{d.action}</span>}
        </li>
      ))}
    </ul>
  </details>
);

const CheckRow = ({ check, onAction, busy }) => {
  const Icon = ICONS[check.status];
  const words = CHECK_STATUS[check.status];
  return (
    <li className={`mb-check-row is-${check.status}`}>
      <Icon className="mb-check-icon" size={18} aria-hidden="true" />
      <div className="mb-check-text">
        <div className="mb-check-title">
          <span className="mb-check-name">{check.name}</span>
          <span className={`badge ${words.badge}`}>{words.label}</span>
        </div>
        <p className="mb-small">{check.message}</p>
        {check.action && (check.action_id ? (
          <button type="button" className="btn btn-tertiary btn-sm mb-check-action" disabled={busy} onClick={() => onAction(check.action_id)}>
            {check.action}
          </button>
        ) : <p className="mb-small mb-check-hint">{check.action}</p>)}
        {check.details.length > 0 && <CheckDetails details={check.details} />}
      </div>
    </li>
  );
};

// The Monthly Processing Checklist. Every status, count and sentence comes from
// GET /batch/checklist: this only lays it out.
const MonthlyChecklist = ({ checklist, onAction, busy }) => {
  const summary = checklistSummary(checklist);
  const SummaryIcon = summary ? TONE_ICON[summary.tone] : null;
  if (!checklist) return <p className="mb-small" role="status">Reading the checks.</p>;
  const rows = (
    <ul className="mb-check-list">
      {checklist.checks.map((check) => <CheckRow key={check.id} check={check} onAction={onAction} busy={busy} />)}
    </ul>
  );
  return (
    <section className="mb-check" aria-labelledby="mb-check-title">
      <div>
        <h5 id="mb-check-title" className="mb-check-heading">Monthly Processing Checklist</h5>
        <p className="mb-small">
          {checklist.validated || summary.tone === 'done'
            ? 'Review the requirements before running this month\'s data.'
            : 'What the system can see so far. Validation also carries over the latest decisions and checks any waiting file.'}
        </p>
      </div>
      <p className={`ui-note mb-note-raised ${TONE_NOTE[summary.tone]}`} role="status">
        <SummaryIcon size={16} aria-hidden="true" />
        <span><strong>{summary.title}.</strong> {summary.text}</span>
      </p>
      {summary.tone === 'done' ? (
        <details className="mb-check-past">
          <summary>Show the checks</summary>
          {rows}
        </details>
      ) : rows}
    </section>
  );
};

export default MonthlyChecklist;
