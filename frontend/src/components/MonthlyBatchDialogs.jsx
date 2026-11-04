import React, { useState } from 'react';
import { AlertTriangle, FileCheck2, Play } from 'lucide-react';
import Modal from './Modal';

const Shell = ({ title, icon: Icon, onClose, closable = true, children, actions }) => (
  <Modal
    isOpen
    onClose={onClose}
    label={title}
    overlayClassName="mb-dialog-overlay"
    containerClassName="mb-dialog"
    closeOnOverlayClick={closable}
    closeOnEscape={closable}
  >
    <div className="mb-dialog-head">
      <span className="mb-dialog-icon"><Icon size={18} aria-hidden="true" /></span>
      <h3>{title}</h3>
    </div>
    <div className="mb-dialog-body">{children}</div>
    <div className="mb-dialog-actions">{actions}</div>
  </Modal>
);

const Fact = ({ term, children }) => (
  <div>
    <dt>{term}</dt>
    <dd>{children}</dd>
  </div>
);

// There is deliberately no way past this dialog: closing it starts nothing, and
// POST /batch/run and scripts.run_month refuse on their own.
export const PendingDecisionsDialog = ({ month, nextMonth, decisions, canReview, onReview, onClose }) => (
  <Shell
    title="Pending Reorder Decisions"
    icon={AlertTriangle}
    onClose={onClose}
    actions={(
      <>
        <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        {canReview && <button type="button" className="btn btn-primary" onClick={onReview}>Review Recommendations</button>}
      </>
    )}
  >
    <p>There are still reorder recommendations awaiting a decision. Please review and resolve them before running the next month&apos;s data.</p>
    <dl className="mb-dialog-facts">
      <Fact term="Awaiting a decision">{decisions.unresolved.toLocaleString('en-US')}</Fact>
      <Fact term="Staff requests awaiting an admin">{decisions.staff_requests.toLocaleString('en-US')}</Fact>
      <Fact term="Processing month">{month}</Fact>
    </dl>
    <p className="mb-small">
      Once the {nextMonth} plan is written, these rows can no longer be decided. Accepted orders count as stock on the way in that plan, so an open decision would change what it orders.
    </p>
    <p className="mb-small">Decisions made on the Reorder Recommendations page are carried over when you run validation again.</p>
    {!canReview && <p className="mb-small">You don&apos;t have access to the Reorder Recommendations page. Ask an admin to settle these.</p>}
  </Shell>
);

export const RunConfirmDialog = ({ month, nextMonth, calendarFactor, warnings, onConfirm, onClose }) => (
  <Shell
    title="Run Monthly Data Processing?"
    icon={Play}
    onClose={onClose}
    actions={(
      <>
        <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-primary" onClick={onConfirm}>Confirm and Run</button>
      </>
    )}
  >
    <p>All required validations have passed. The system is ready to process the latest month&apos;s data.</p>
    <dl className="mb-dialog-facts">
      <Fact term="Processing month">{month}</Fact>
      <Fact term="Writes the plan for">{nextMonth}</Fact>
      <Fact term="Calendar factor">{calendarFactor === 'on' ? 'On (as the live forecast)' : 'Off'}</Fact>
    </dl>
    {warnings > 0 && <p className="mb-small">The checklist has {warnings} warning{warnings === 1 ? '' : 's'} you may want to read first.</p>}
    <p className="mb-small">It stops before anything is closed, so you can review the new plan.</p>
  </Shell>
);

// Approving records this person against these exact files. The loader checks the
// approval against the file when it loads, so a changed file needs a new one.
export const ApproveFileDialog = ({ fileCheck, onApprove, onClose }) => {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const approve = async () => {
    setSaving(true);
    setError('');
    try {
      await onApprove();
    } catch (e) {
      setError(e.message);
      setSaving(false);
    }
  };
  return (
    <Shell
      title="Approve This File?"
      icon={FileCheck2}
      onClose={onClose}
      closable={!saving}
      actions={(
        <>
          <button type="button" className="btn btn-secondary" disabled={saving} onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={saving} onClick={approve}>{saving ? 'Approving' : 'Approve File'}</button>
        </>
      )}
    >
      <p>Approving records your name against these exact files. If a file changes, it needs a new check and a new approval.</p>
      <dl className="mb-dialog-facts">
        <Fact term={fileCheck?.files?.length === 1 ? 'File' : 'Files'}>{(fileCheck?.files || []).join(', ') || 'None'}</Fact>
        {(fileCheck?.slices || []).map((s) => (
          <Fact key={s.table} term={s.table}>
            {s.rows_after == null ? s.status : `${Number(s.rows_before || 0).toLocaleString('en-US')} rows held now, ${Number(s.rows_after).toLocaleString('en-US')} after loading`}
          </Fact>
        ))}
      </dl>
      {error && <p className="ui-note is-warning" role="alert"><AlertTriangle size={16} aria-hidden="true" /><span>{error}</span></p>}
    </Shell>
  );
};
